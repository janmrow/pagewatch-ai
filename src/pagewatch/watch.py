"""Persist one watch baseline and report content changes."""

import json
import logging
import os
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from difflib import unified_diff
from pathlib import Path

from pagewatch.classification import (
    Classification,
    ClassificationError,
    parse_classification,
)
from pagewatch.content import fetch_text

_LOG = logging.getLogger("pagewatch.runtime")


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
    notifier: Callable[[Classification, str], None] | None = None,
    watch_id: str | None = None,
) -> WatchResult:
    """Check one watch; classify a change before handling it when requested."""
    if watch_id is not None:
        _LOG.info("watch=%s check started", watch_id)
    if classifier is not None and (interest is None or not interest.strip()):
        raise ClassificationError("classification requires watch interest")
    if notifier is not None and classifier is None:
        raise ClassificationError("notification requires a classifier")

    previous, pending_text, detected_at, legacy_pending = _read_baseline(
        state_file, url, selector
    )
    if pending_text is not None:
        if classifier is None:
            raise WatchError(
                f"change pending classification or notification: {state_file}"
            )
        current = pending_text
        if detected_at is None:
            detected_at = datetime.now(UTC).isoformat(timespec="seconds")
            _write_baseline(
                state_file,
                url,
                selector,
                previous,
                pending_text=current,
                detected_at=detected_at,
            )
    else:
        if legacy_pending and classifier is None:
            raise WatchError(
                f"change pending classification or notification: {state_file}"
            )
        current = fetch_text(url, selector)
        if watch_id is not None:
            _LOG.info("watch=%s fetch succeeded", watch_id)
        if previous is None:
            _write_baseline(state_file, url, selector, current)
            if watch_id is not None:
                _LOG.info("watch=%s state advanced", watch_id)
            return WatchResult("baseline established")
        if current == previous:
            if legacy_pending:
                raise WatchError(
                    f"legacy pending change is no longer available: {state_file}"
                )
            if watch_id is not None:
                _LOG.info("watch=%s unchanged", watch_id)
            return WatchResult("unchanged")
        if classifier is not None:
            detected_at = datetime.now(UTC).isoformat(timespec="seconds")
            _write_baseline(
                state_file,
                url,
                selector,
                previous,
                pending_text=current,
                detected_at=detected_at,
            )

    if watch_id is not None:
        _LOG.info("watch=%s change detected", watch_id)

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
        if watch_id is not None:
            _LOG.info("watch=%s state advanced", watch_id)
        return WatchResult("changed", diff)

    try:
        response = classifier(interest, diff)
    except ClassificationError:
        if watch_id is not None:
            _LOG.error("watch=%s classifier request failed", watch_id)
        raise
    try:
        classification = parse_classification(response)
    except ClassificationError:
        if watch_id is not None:
            _LOG.error("watch=%s classification response invalid", watch_id)
        raise
    if watch_id is not None:
        _LOG.info(
            "watch=%s classification relevant=%s",
            watch_id,
            str(classification.relevant).lower(),
        )
    if not classification.relevant:
        _write_baseline(state_file, url, selector, current)
        if watch_id is not None:
            _LOG.info("watch=%s state advanced", watch_id)
    elif notifier is not None:
        notifier(classification, detected_at)
        if watch_id is not None:
            _LOG.info("watch=%s notification sent", watch_id)
        _write_baseline(state_file, url, selector, current)
        if watch_id is not None:
            _LOG.info("watch=%s state advanced", watch_id)
    return WatchResult("changed", diff, classification)


def _read_baseline(
    state_file: Path, url: str, selector: str
) -> tuple[str | None, str | None, str | None, bool]:
    try:
        data = json.loads(state_file.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, None, None, False
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WatchError(f"could not read baseline {state_file}: {exc}") from exc

    if (
        not isinstance(data, dict)
        or not all(
            isinstance(data.get(key), str) for key in ("url", "selector", "text")
        )
        or type(data.get("pending", False)) is not bool
        or ("pending_text" in data and not isinstance(data["pending_text"], str))
        or ("detected_at" in data and "pending_text" not in data)
        or ("detected_at" in data and not isinstance(data["detected_at"], str))
        or (data.get("pending") is True and "pending_text" in data)
    ):
        raise WatchError(f"invalid baseline file: {state_file}")
    if data["url"] != url or data["selector"] != selector:
        raise WatchError(f"baseline belongs to another URL or selector: {state_file}")
    detected_at = data.get("detected_at")
    if detected_at is not None:
        try:
            detected = datetime.fromisoformat(detected_at)
        except ValueError as exc:
            raise WatchError(f"invalid baseline file: {state_file}") from exc
        if detected.utcoffset() is None:
            raise WatchError(f"invalid baseline file: {state_file}")
    return (
        data["text"],
        data.get("pending_text"),
        detected_at,
        data.get("pending", False),
    )


def _write_baseline(
    state_file: Path,
    url: str,
    selector: str,
    text: str,
    *,
    pending_text: str | None = None,
    detected_at: str | None = None,
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
                if detected_at is not None:
                    data["detected_at"] = detected_at
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
