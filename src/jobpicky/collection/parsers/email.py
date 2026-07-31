"""Email application links are not public job facts."""

from __future__ import annotations


def parse(_url: str) -> list[dict[str, object]]:
    """Fail explicitly instead of inventing a job from an email address."""
    raise ValueError("email link is an application method, not a public job source")


__all__ = ["parse"]
