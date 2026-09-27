"""Structured classifier response contract."""

import json
from pathlib import Path

import pytest

from pagewatch.classification import (
    Classification,
    ClassificationError,
    parse_classification,
)
from pagewatch.cli import main
from pagewatch.watch import WatchError, check_watch

URL = "https://example.test/page"
SELECTOR = "main"


def test_accepts_structured_decision() -> None:
    assert parse_classification(
        '{"relevant": true, "summary": "A deadline changed", "reason": "Matches the watch interest"}'
    ) == Classification(
        relevant=True,
        summary="A deadline changed",
        reason="Matches the watch interest",
    )


@pytest.mark.parametrize(
    "response",
    [
        "not JSON",
        "[]",
        '{"relevant": 1, "summary": "Change", "reason": "Match"}',
        '{"relevant": true, "summary": " ", "reason": "Match"}',
        '{"relevant": true, "summary": "Change"}',
        '{"relevant": true, "summary": "Change", "reason": "Match", "extra": 1}',
        None,
    ],
)
def test_rejects_invalid_decisions(response: object) -> None:
    with pytest.raises(ClassificationError):
        parse_classification(response)


def test_fake_classifier_receives_diff_only_and_handles_irrelevant_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_file = tmp_path / "baseline.json"
    prefix = " ".join(f"before{i}" for i in range(20))
    suffix = " ".join(f"after{i}" for i in range(20))
    original = f"{prefix} deadline 10 {suffix}"
    current = f"{prefix} deadline 11 {suffix}"
    content = {"value": original}
    monkeypatch.setattr(
        "pagewatch.watch.fetch_text", lambda url, selector: content["value"]
    )
    calls = []

    def fake_classifier(interest: str, diff: str) -> str:
        calls.append((interest, diff))
        return json.dumps(
            {"relevant": False, "summary": "Minor edit", "reason": "Outside interest"}
        )

    first = check_watch(
        URL,
        SELECTOR,
        state_file,
        interest="Enrollment dates",
        classifier=fake_classifier,
    )
    assert first.status == "baseline established"
    assert first.classification is None
    assert calls == []

    content["value"] = current
    changed = check_watch(
        URL,
        SELECTOR,
        state_file,
        interest="Enrollment dates",
        classifier=fake_classifier,
    )
    assert changed.status == "changed"
    assert changed.classification == Classification(
        False, "Minor edit", "Outside interest"
    )
    assert calls[0][0] == "Enrollment dates"
    assert calls[0][1] == changed.diff
    assert "-10" in changed.diff and "+11" in changed.diff
    assert "before0" not in changed.diff
    assert json.loads(state_file.read_text())["text"] == current

    assert (
        check_watch(
            URL,
            SELECTOR,
            state_file,
            interest="Enrollment dates",
            classifier=fake_classifier,
        ).status
        == "unchanged"
    )
    assert len(calls) == 1


def test_relevant_change_stays_pending_without_notification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_file = tmp_path / "baseline.json"
    content = {"value": "Deadline 10"}
    monkeypatch.setattr(
        "pagewatch.watch.fetch_text", lambda url, selector: content["value"]
    )
    calls = []

    def fake_classifier(interest: str, diff: str) -> str:
        calls.append(diff)
        return '{"relevant": true, "summary": "Deadline moved", "reason": "Matches interest"}'

    check_watch(
        URL, SELECTOR, state_file, interest="Deadline", classifier=fake_classifier
    )
    content["value"] = "Deadline 11"

    result = check_watch(
        URL, SELECTOR, state_file, interest="Deadline", classifier=fake_classifier
    )
    assert result.classification == Classification(
        True, "Deadline moved", "Matches interest"
    )
    assert json.loads(state_file.read_text()) == {
        "url": URL,
        "selector": SELECTOR,
        "text": "Deadline 10",
        "pending": True,
    }

    with pytest.raises(WatchError, match="pending"):
        check_watch(
            URL, SELECTOR, state_file, interest="Deadline", classifier=fake_classifier
        )
    assert len(calls) == 1


def test_failed_classification_keeps_detected_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_file = tmp_path / "baseline.json"
    content = {"value": "Before"}
    monkeypatch.setattr(
        "pagewatch.watch.fetch_text", lambda url, selector: content["value"]
    )
    check_watch(URL, SELECTOR, state_file)
    content["value"] = "After"

    with pytest.raises(ClassificationError, match="invalid classifier JSON"):
        check_watch(
            URL,
            SELECTOR,
            state_file,
            interest="Updates",
            classifier=lambda interest, diff: "not JSON",
        )
    assert json.loads(state_file.read_text()) == {
        "url": URL,
        "selector": SELECTOR,
        "text": "Before",
        "pending": True,
    }


def test_classifier_error_keeps_detected_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_file = tmp_path / "baseline.json"
    content = {"value": "Before"}
    monkeypatch.setattr(
        "pagewatch.watch.fetch_text", lambda url, selector: content["value"]
    )
    check_watch(URL, SELECTOR, state_file)
    content["value"] = "After"

    def failing_classifier(interest: str, diff: str) -> str:
        raise ClassificationError("provider unavailable")

    with pytest.raises(ClassificationError, match="provider unavailable"):
        check_watch(
            URL,
            SELECTOR,
            state_file,
            interest="Updates",
            classifier=failing_classifier,
        )
    assert json.loads(state_file.read_text()) == {
        "url": URL,
        "selector": SELECTOR,
        "text": "Before",
        "pending": True,
    }


@pytest.mark.parametrize("command", ["watch", "run"])
def test_cli_cannot_advance_pending_change(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    command: str,
) -> None:
    state_dir = tmp_path / "state"
    state_file = state_dir / "first.json"
    content = {"value": "Before"}
    monkeypatch.setattr(
        "pagewatch.watch.fetch_text", lambda url, selector: content["value"]
    )
    check_watch(URL, SELECTOR, state_file)
    content["value"] = "After"
    check_watch(
        URL,
        SELECTOR,
        state_file,
        interest="Updates",
        classifier=lambda interest, diff: (
            '{"relevant": true, "summary": "Changed", "reason": "Matches interest"}'
        ),
    )
    pending_state = state_file.read_bytes()

    if command == "watch":
        args = ["watch", URL, "--selector", SELECTOR, "--state-file", str(state_file)]
    else:
        config = tmp_path / "watches.toml"
        config.write_text(
            "\n".join(
                [
                    "[[watches]]",
                    'id = "first"',
                    f'url = "{URL}"',
                    f'selector = "{SELECTOR}"',
                    'interest = "Updates"',
                    "",
                    "[[watches]]",
                    'id = "second"',
                    'url = "https://example.test/second"',
                    'selector = "main"',
                    'interest = "Updates"',
                ]
            ),
            encoding="utf-8",
        )
        args = ["run", "--config", str(config), "--state-dir", str(state_dir)]

    assert main(args) == 1
    output = capsys.readouterr()
    assert "pending classification or notification" in output.err
    assert "Traceback" not in output.err
    assert state_file.read_bytes() == pending_state
    if command == "run":
        assert "second: baseline established" in output.out
        assert (state_dir / "second.json").exists()
