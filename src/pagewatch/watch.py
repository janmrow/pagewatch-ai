"""Persist one watch baseline and report content changes."""

import json
import os
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from difflib import unified_diff
from pathlib import Path

from pagewatch.classification import (
    Classification,
    ClassificationError,
    parse_classification,
)
from pagewatch.content import fetch_text


class WatchError(Exception):
    """The baseline could not be read or saved safely."""


@dataclass(frozen=True)
class WatchResult:
    status: str
    diff: str = ""
    classification: Classification | None = None


def check_watch(
    url: str,
    selector: str,
    state_file: Path,
    *,
    interest: str | None = None,
    classifier: Callable[[str, str], str] | None = None,
    notifier: Callable[[Classification], None] | None = None,
) -> WatchResult:
    """Check one watch; classify a change before handling it when requested."""
    if classifier is not None and (interest is None or not interest.strip()):
        raise ClassificationError("classification requires watch interest")
    if notifier is not None and classifier is None:
        raise ClassificationError("notification requires a classifier")

    previous, pending_text, legacy_pending = _read_baseline(state_file, url, selector)
    if pending_text is not None:
        if classifier is None:
            raise WatchError(
                f"change pending classification or notification: {state_file}"
            )
        current = pending_text
    else:
        if legacy_pending and classifier is None:
            raise WatchError(
                f"change pending classification or notification: {state_file}"
            )
        current = fetch_text(url, selector)
        if previous is None:
            _write_baseline(state_file, url, selector, current)
            return WatchResult("baseline established")
        if current == previous:
            if legacy_pending:
                raise WatchError(
                    f"legacy pending change is no longer available: {state_file}"
                )
            return WatchResult("unchanged")
        if classifier is not None:
            _write_baseline(state_file, url, selector, previous, pending_text=current)

    diff = "\n".join(
        unified_diff(
            previous.split(),
            current.split(),
            fromfile="baseline",
            tofile="current",
            lineterm="",
        )
    )
    if classifier is None:
        _write_baseline(state_file, url, selector, current)
        return WatchResult("changed", diff)

    classification = parse_classification(classifier(interest, diff))
    if not classification.relevant:
        _write_baseline(state_file, url, selector, current)
    elif notifier is not None:
        notifier(classification)
        _write_baseline(state_file, url, selector, current)
    return WatchResult("changed", diff, classification)


def _read_baseline(
    state_file: Path, url: str, selector: str
) -> tuple[str | None, str | None, bool]:
    try:
        data = json.loads(state_file.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, None, False
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WatchError(f"could not read baseline {state_file}: {exc}") from exc

    if (
        not isinstance(data, dict)
        or not all(
            isinstance(data.get(key), str) for key in ("url", "selector", "text")
        )
        or type(data.get("pending", False)) is not bool
        or ("pending_text" in data and not isinstance(data["pending_text"], str))
        or (data.get("pending") is True and "pending_text" in data)
    ):
        raise WatchError(f"invalid baseline file: {state_file}")
    if data["url"] != url or data["selector"] != selector:
        raise WatchError(f"baseline belongs to another URL or selector: {state_file}")
    return data["text"], data.get("pending_text"), data.get("pending", False)


def _write_baseline(
    state_file: Path,
    url: str,
    selector: str,
    text: str,
    *,
    pending_text: str | None = None,
) -> None:
    temporary_path = None
    try:
        state_file.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=state_file.parent,
            prefix=f".{state_file.name}.",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            data = {"url": url, "selector": selector, "text": text}
            if pending_text is not None:
                data["pending_text"] = pending_text
            json.dump(data, temporary)
            temporary.write("\n")
        os.replace(temporary_path, state_file)
    except OSError as exc:
        raise WatchError(f"could not save baseline {state_file}: {exc}") from exc
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass
