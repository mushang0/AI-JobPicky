from __future__ import annotations

from functools import lru_cache
from importlib.resources import files

_PACKAGE = "jobpicky.infrastructure"


@lru_cache(maxsize=1)
def load_profile_import_prompt() -> str:
    return files(_PACKAGE).joinpath("prompts/profile_import.txt").read_text(encoding="utf-8")


__all__ = ["load_profile_import_prompt"]
