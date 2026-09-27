"""Persist one watch baseline and report content changes."""

import json
import os
import tempfile
from difflib import unified_diff
from pathlib import Path

from pagewatch.content import fetch_text


class WatchError(Exception):
    """The baseline could not be read or saved safely."""


def check_watch(url: str, selector: str, state_file: Path) -> tuple[str, str]:
    """Return a status and diff for one watch, updating its baseline if needed."""
    previous = _read_baseline(state_file, url, selector)
    current = fetch_text(url, selector)

    if previous is None:
        _write_baseline(state_file, url, selector, current)
        return "baseline established", ""
    if current == previous:
        return "unchanged", ""

    diff = "\n".join(
        unified_diff(
            previous.split(),
            current.split(),
            fromfile="baseline",
            tofile="current",
            lineterm="",
        )
    )
    _write_baseline(state_file, url, selector, current)
    return "changed", diff


def _read_baseline(state_file: Path, url: str, selector: str) -> str | None:
    try:
        data = json.loads(state_file.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WatchError(f"could not read baseline {state_file}: {exc}") from exc

    if not isinstance(data, dict) or not all(
        isinstance(data.get(key), str) for key in ("url", "selector", "text")
    ):
        raise WatchError(f"invalid baseline file: {state_file}")
    if data["url"] != url or data["selector"] != selector:
        raise WatchError(f"baseline belongs to another URL or selector: {state_file}")
    return data["text"]


def _write_baseline(state_file: Path, url: str, selector: str, text: str) -> None:
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
            json.dump({"url": url, "selector": selector, "text": text}, temporary)
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
