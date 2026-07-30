from __future__ import annotations

import json
from functools import lru_cache
from importlib.resources import files
from typing import Any

_PACKAGE = "jobpicky.infrastructure"


@lru_cache(maxsize=1)
def load_evaluation_input_schema() -> dict[str, Any]:
    return _load_schema("schemas/recommendation_evaluator_input.json")


@lru_cache(maxsize=1)
def load_evaluation_output_schema() -> dict[str, Any]:
    return _load_schema("schemas/recommendation_evaluator_output.json")


@lru_cache(maxsize=1)
def load_evaluation_prompt() -> str:
    template = _read_text("prompts/recommendation_evaluator.txt")
    return template.replace(
        "{{INPUT_SCHEMA}}",
        json.dumps(load_evaluation_input_schema(), ensure_ascii=False, indent=2),
    ).replace(
        "{{OUTPUT_SCHEMA}}",
        json.dumps(load_evaluation_output_schema(), ensure_ascii=False, indent=2),
    )


def _load_schema(resource: str) -> dict[str, Any]:
    value = json.loads(_read_text(resource))
    if not isinstance(value, dict):
        raise ValueError(f"evaluation schema must be a JSON object: {resource}")
    return value


def _read_text(resource: str) -> str:
    return files(_PACKAGE).joinpath(resource).read_text(encoding="utf-8")


__all__ = [
    "load_evaluation_input_schema",
    "load_evaluation_output_schema",
    "load_evaluation_prompt",
]
