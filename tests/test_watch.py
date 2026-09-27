"""Single-watch baseline and change detection checks."""

import json
from pathlib import Path

import pytest

from pagewatch.cli import main
from pagewatch.content import ContentError
from pagewatch.watch import WatchError, check_watch

URL = "https://example.test/page"
SELECTOR = "main"


def watch_args(state_file: Path) -> list[str]:
    return ["watch", URL, "--selector", SELECTOR, "--state-file", str(state_file)]


def test_baseline_unchanged_and_changed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    state_file = tmp_path / "watch" / "baseline.json"
    content = iter(["Price 10 USD", "Price 10 USD", "Price 11 USD", "Price 11 USD"])
    monkeypatch.setattr(
        "pagewatch.watch.fetch_text", lambda url, selector: next(content)
    )

    assert main(watch_args(state_file)) == 0
    assert capsys.readouterr().out.strip() == "baseline established"
    assert json.loads(state_file.read_text()) == {
        "url": URL,
        "selector": SELECTOR,
        "text": "Price 10 USD",
    }

    assert main(watch_args(state_file)) == 0
    assert capsys.readouterr().out.strip() == "unchanged"

    assert main(watch_args(state_file)) == 0
    diff = capsys.readouterr().out
    assert "--- baseline" in diff
    assert "+++ current" in diff
    assert "-10" in diff
    assert "+11" in diff
    assert json.loads(state_file.read_text())["text"] == "Price 11 USD"

    assert main(watch_args(state_file)) == 0
    assert capsys.readouterr().out.strip() == "unchanged"


def test_failed_fetch_keeps_baseline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    state_file = tmp_path / "baseline.json"
    monkeypatch.setattr("pagewatch.watch.fetch_text", lambda url, selector: "Original")
    assert main(watch_args(state_file)) == 0
    original = state_file.read_bytes()
    capsys.readouterr()

    def fail_fetch(url: str, selector: str) -> str:
        raise ContentError("HTTP 500")

    monkeypatch.setattr("pagewatch.watch.fetch_text", fail_fetch)
    assert main(watch_args(state_file)) == 1
    assert "HTTP 500" in capsys.readouterr().err
    assert state_file.read_bytes() == original


def test_different_watch_cannot_reuse_baseline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_file = tmp_path / "baseline.json"
    monkeypatch.setattr("pagewatch.watch.fetch_text", lambda url, selector: "Original")
    check_watch(URL, SELECTOR, state_file)
    original = state_file.read_bytes()

    with pytest.raises(WatchError, match="another URL or selector"):
        check_watch("https://example.test/other", SELECTOR, state_file)
    assert state_file.read_bytes() == original


def test_invalid_state_is_not_overwritten(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_file = tmp_path / "baseline.json"
    state_file.write_text("{", encoding="utf-8")
    monkeypatch.setattr("pagewatch.watch.fetch_text", lambda url, selector: "New")

    with pytest.raises(WatchError, match="could not read baseline"):
        check_watch(URL, SELECTOR, state_file)
    assert state_file.read_text(encoding="utf-8") == "{"


def test_invalid_utf8_state_reports_error_without_overwrite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    state_file = tmp_path / "baseline.json"
    state_file.write_bytes(b"\xff")
    monkeypatch.setattr(
        "pagewatch.watch.fetch_text",
        lambda url, selector: pytest.fail("unexpected fetch"),
    )

    assert main(watch_args(state_file)) == 1
    error = capsys.readouterr().err
    assert "could not read baseline" in error
    assert "Traceback" not in error
    assert state_file.read_bytes() == b"\xff"


def test_failed_save_keeps_previous_baseline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_file = tmp_path / "baseline.json"
    monkeypatch.setattr("pagewatch.watch.fetch_text", lambda url, selector: "Original")
    check_watch(URL, SELECTOR, state_file)
    original = state_file.read_bytes()
    monkeypatch.setattr("pagewatch.watch.fetch_text", lambda url, selector: "Changed")

    def fail_replace(source: Path, target: Path) -> None:
        raise OSError("save failed")

    monkeypatch.setattr("pagewatch.watch.os.replace", fail_replace)
    with pytest.raises(WatchError, match="could not save baseline"):
        check_watch(URL, SELECTOR, state_file)
    assert state_file.read_bytes() == original
