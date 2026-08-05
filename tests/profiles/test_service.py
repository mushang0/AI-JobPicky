from __future__ import annotations

import asyncio
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

import pypdfium2 as pdfium
import pytest

from jobpicky.contracts import (
    ErrorCode,
    ProfileImportDraft,
    ProfileImportView,
    ProfileSaveRequest,
    ProfileSnapshot,
    RecruitmentType,
)
from jobpicky.errors import ApplicationError
from jobpicky.profiles import (
    ProfileIdempotencyConflictError,
    ProfileSaveCommand,
    ProfileService,
    plan_profile_save,
)
from jobpicky.profiles.resume_files import PROFILE_IMPORT_MAX_PDF_PAGES

NOW = datetime(2026, 8, 1, tzinfo=UTC)


class MemoryProfileStore:
    def __init__(self) -> None:
        self.snapshots: dict[str, list[ProfileSnapshot]] = {}
        self.requests: dict[tuple[str, str], tuple[str, ProfileSnapshot]] = {}

    async def find_current(self, user_id: str) -> ProfileSnapshot | None:
        snapshots = self.snapshots.get(user_id, [])
        return snapshots[-1] if snapshots else None

    async def save_current(self, command: ProfileSaveCommand) -> ProfileSnapshot:
        request_key = (command.user_id, command.idempotency_key)
        replay = self.requests.get(request_key)
        if replay is not None:
            request_hash, snapshot = replay
            if request_hash != command.request_hash:
                raise ProfileIdempotencyConflictError
            return snapshot

        current = await self.find_current(command.user_id)
        snapshot = plan_profile_save(current, command)
        if current is None or snapshot.version != current.version:
            self.snapshots.setdefault(command.user_id, []).append(snapshot)
        self.requests[request_key] = (command.request_hash, snapshot)
        return snapshot


class FakeProfileParser:
    def __init__(self) -> None:
        self.resume_text: str | None = None
        self.image_pages: tuple[bytes, ...] | None = None

    async def parse(self, resume_text: str, extra_request: str | None) -> ProfileImportView:
        self.resume_text = resume_text
        assert extra_request is None
        return self._result()

    async def parse_images(
        self,
        image_pages: Sequence[bytes],
        extra_request: str | None,
    ) -> ProfileImportView:
        self.image_pages = tuple(image_pages)
        assert extra_request is None
        return self._result()

    @staticmethod
    def _result() -> ProfileImportView:
        return ProfileImportView(
            draft=ProfileImportDraft(
                target_roles=["后端工程师"],
                skills=["Python"],
                experience_summary="负责后端接口开发。",
            ),
            warnings=["请确认目标岗位。"],
        )


def request(
    *,
    base_version: int | None = None,
    target_role: str = "Python 后端工程师",
) -> ProfileSaveRequest:
    return ProfileSaveRequest(
        base_version=base_version,
        target_roles=[target_role],
        target_locations=["上海"],
        recruitment_types=[RecruitmentType.SOCIAL],
        skills=["Python"],
        excluded_roles=[],
    )


def service(store: MemoryProfileStore) -> ProfileService:
    return ProfileService(
        store,
        now=lambda: NOW,
        id_factory=lambda: "profile-1",
    )


def test_profile_input_is_normalized_before_versioning_and_hashing() -> None:
    draft = ProfileSaveRequest.model_validate(
        {
            "target_roles": [" Python   Backend ", "python backend"],
            "target_locations": [" 上海市、杭州 ", "上海"],
            "recruitment_types": ["社会招聘", "社招"],
            "skills": [" FastAPI ", "fastapi"],
            "experience_summary": "  有后端项目经验。  ",
            "extra_request": "   ",
        }
    )

    assert draft.target_roles == ["Python Backend"]
    assert draft.target_locations == ["上海", "杭州"]
    assert draft.recruitment_types == [RecruitmentType.SOCIAL]
    assert draft.skills == ["FastAPI"]
    assert draft.experience_summary == "有后端项目经验。"
    assert draft.extra_request is None


def test_create_update_and_unchanged_save_keep_immutable_versions() -> None:
    async def check() -> None:
        store = MemoryProfileStore()
        profiles = service(store)

        first = await profiles.save_current("user-1", request(), "create")
        second = await profiles.save_current(
            "user-1",
            request(base_version=1, target_role="平台后端工程师"),
            "update",
        )
        unchanged = await profiles.save_current(
            "user-1",
            request(base_version=2, target_role="平台后端工程师"),
            "no-change",
        )

        assert (first.id, first.version) == ("profile-1", 1)
        assert (second.id, second.version) == ("profile-1", 2)
        assert unchanged is second
        assert [item.version for item in store.snapshots["user-1"]] == [1, 2]
        assert store.snapshots["user-1"][0].target_roles == ["Python 后端工程师"]

    asyncio.run(check())


def test_idempotency_replay_precedes_current_version_check() -> None:
    async def check() -> None:
        store = MemoryProfileStore()
        profiles = service(store)
        original_request = request()
        first = await profiles.save_current("user-1", original_request, "create")
        await profiles.save_current(
            "user-1",
            request(base_version=1, target_role="平台后端工程师"),
            "update",
        )

        replay = await profiles.save_current("user-1", original_request, "create")

        assert replay == first
        assert replay.version == 1
        assert len(store.snapshots["user-1"]) == 2

    asyncio.run(check())


def test_stale_version_and_changed_idempotency_payload_have_distinct_errors() -> None:
    async def check() -> None:
        store = MemoryProfileStore()
        profiles = service(store)
        await profiles.save_current("user-1", request(), "create")

        with pytest.raises(ApplicationError) as stale:
            await profiles.save_current(
                "user-1",
                request(base_version=2, target_role="其他岗位"),
                "stale",
            )
        assert stale.value.code == str(ErrorCode.PROFILE_VERSION_CONFLICT)
        assert stale.value.status_code == 409

        with pytest.raises(ApplicationError) as reused:
            await profiles.save_current(
                "user-1",
                request(target_role="其他岗位"),
                "create",
            )
        assert reused.value.code == str(ErrorCode.IDEMPOTENCY_CONFLICT)
        assert reused.value.status_code == 409

    asyncio.run(check())


def test_missing_profile_and_invalid_idempotency_key_are_explicit() -> None:
    async def check() -> None:
        profiles = service(MemoryProfileStore())
        with pytest.raises(ApplicationError) as missing:
            await profiles.get_current("user-1")
        assert missing.value.code == str(ErrorCode.PROFILE_NOT_FOUND)
        assert missing.value.status_code == 404

        for key in ("", "x" * 129, "不可打印"):
            with pytest.raises(ApplicationError) as invalid:
                await profiles.save_current("user-1", request(), key)
            assert invalid.value.code == str(ErrorCode.VALIDATION_ERROR)
            assert invalid.value.status_code == 422

    asyncio.run(check())


def test_resume_import_returns_a_draft_without_saving_a_profile() -> None:
    async def check() -> None:
        store = MemoryProfileStore()
        parser = FakeProfileParser()
        profiles = ProfileService(store, parser=parser)

        result = await profiles.import_resume(
            "user-1",
            "resume.txt",
            "text/plain",
            "使用 Python 和 FastAPI 负责后端接口及异步任务开发。".encode(),
        )

        assert result.draft.skills == ["Python"]
        assert parser.resume_text is not None
        assert store.snapshots == {}

    asyncio.run(check())


def test_pdf_resume_import_renders_pages_for_the_multimodal_parser() -> None:
    async def check() -> None:
        store = MemoryProfileStore()
        parser = FakeProfileParser()
        profiles = ProfileService(store, parser=parser)

        document = pdfium.PdfDocument.new()
        document.new_page(width=612, height=792)
        with TemporaryDirectory() as directory:
            path = Path(directory) / "resume.pdf"
            document.save(path)
            content = path.read_bytes()
        document.close()

        result = await profiles.import_resume("user-1", "resume.pdf", "application/pdf", content)

        assert result.draft.skills == ["Python"]
        assert parser.resume_text is None
        assert parser.image_pages is not None
        assert len(parser.image_pages) == 1
        assert parser.image_pages[0].startswith(b"\x89PNG\r\n\x1a\n")
        assert store.snapshots == {}

    asyncio.run(check())


def test_pdf_resume_import_rejects_more_than_four_pages_before_model_call() -> None:
    async def check() -> None:
        store = MemoryProfileStore()
        parser = FakeProfileParser()
        profiles = ProfileService(store, parser=parser)

        document = pdfium.PdfDocument.new()
        for _ in range(PROFILE_IMPORT_MAX_PDF_PAGES + 1):
            document.new_page(width=612, height=792)
        with TemporaryDirectory() as directory:
            path = Path(directory) / "resume.pdf"
            document.save(path)
            content = path.read_bytes()
        document.close()

        with pytest.raises(ApplicationError) as rejected:
            await profiles.import_resume("user-1", "resume.pdf", "application/pdf", content)

        assert rejected.value.code == str(ErrorCode.PROFILE_PARSE_FAILED)
        assert rejected.value.details["max_pdf_pages"] == 4
        assert parser.image_pages is None
        assert store.snapshots == {}

    asyncio.run(check())
