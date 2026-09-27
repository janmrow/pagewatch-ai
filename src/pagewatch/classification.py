"""Validate structured relevance decisions returned by a classifier."""

import json
from dataclasses import dataclass


class ClassificationError(Exception):
    """The classifier did not return a usable decision."""


@dataclass(frozen=True)
class Classification:
    relevant: bool
    summary: str
    reason: str


def parse_classification(response: str) -> Classification:
    """Require a JSON object with the three agreed fields and exact types."""
    if not isinstance(response, str):
        raise ClassificationError("classifier response must be JSON text")
    try:
        value = json.loads(response)
    except json.JSONDecodeError as exc:
        raise ClassificationError(f"invalid classifier JSON: {exc}") from exc

    if not isinstance(value, dict) or set(value) != {"relevant", "summary", "reason"}:
        raise ClassificationError("classifier response needs relevant, summary, reason")
    if type(value["relevant"]) is not bool:
        raise ClassificationError("classifier relevant must be a boolean")
    if not all(
        isinstance(value[key], str) and value[key].strip()
        for key in ("summary", "reason")
    ):
        raise ClassificationError("classifier summary and reason must be nonempty text")
    return Classification(
        relevant=value["relevant"],
        summary=value["summary"],
        reason=value["reason"],
    )
