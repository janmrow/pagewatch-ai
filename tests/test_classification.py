"""Structured classifier response contract."""

import json
from datetime import UTC, datetime
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


def read_pending_state(state_file: Path) -> tuple[dict[str, str], str]:
    state = json.loads(state_file.read_text())
    detected_at = state.pop("detected_at")
    assert datetime.fromisoformat(detected_at).utcoffset() == UTC.utcoffset(None)
    return state, detected_at


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


def test_relevant_change_is_retried_without_notification(
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
    state, detected_at = read_pending_state(state_file)
    assert state == {
        "url": URL,
        "selector": SELECTOR,
        "text": "Deadline 10",
        "pending_text": "Deadline 11",
    }

    retried = check_watch(
        URL, SELECTOR, state_file, interest="Deadline", classifier=fake_classifier
    )
    assert retried.classification == result.classification
    assert len(calls) == 2
    assert json.loads(state_file.read_text())["pending_text"] == "Deadline 11"
    assert read_pending_state(state_file)[1] == detected_at


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
    state, _ = read_pending_state(state_file)
    assert state == {
        "url": URL,
        "selector": SELECTOR,
        "text": "Before",
        "pending_text": "After",
    }
    retried = check_watch(
        URL,
        SELECTOR,
        state_file,
        interest="Updates",
        classifier=lambda interest, diff: (
            '{"relevant": false, "summary": "Minor", "reason": "Outside interest"}'
        ),
    )
    assert retried.classification == Classification(False, "Minor", "Outside interest")
    assert json.loads(state_file.read_text())["text"] == "After"


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
    state, _ = read_pending_state(state_file)
    assert state == {
        "url": URL,
        "selector": SELECTOR,
        "text": "Before",
        "pending_text": "After",
    }
    retried = check_watch(
        URL,
        SELECTOR,
        state_file,
        interest="Updates",
        classifier=lambda interest, diff: (
            '{"relevant": false, "summary": "Minor", "reason": "Outside interest"}'
        ),
    )
    assert retried.classification == Classification(False, "Minor", "Outside interest")
    assert json.loads(state_file.read_text())["text"] == "After"


def test_notification_error_retries_then_advances_after_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_file = tmp_path / "baseline.json"
    content = {"value": "Before"}
    monkeypatch.setattr(
        "pagewatch.watch.fetch_text", lambda url, selector: content["value"]
    )
    check_watch(URL, SELECTOR, state_file)
    content["value"] = "After"
    calls = []

    def fake_classifier(interest: str, diff: str) -> str:
        calls.append((interest, diff))
        return '{"relevant": true, "summary": "Changed", "reason": "Matches interest"}'

    def failing_notifier(classification: Classification, detected_at: str) -> None:
        assert classification.summary == "Changed"
        assert json.loads(state_file.read_text())["pending_text"] == "After"
        assert detected_at == read_pending_state(state_file)[1]
        raise RuntimeError("SMTP unavailable")

    with pytest.raises(RuntimeError, match="SMTP unavailable"):
        check_watch(
            URL,
            SELECTOR,
            state_file,
            interest="Updates",
            classifier=fake_classifier,
            notifier=failing_notifier,
        )
    state, detected_at = read_pending_state(state_file)
    assert state == {
        "url": URL,
        "selector": SELECTOR,
        "text": "Before",
        "pending_text": "After",
    }

    content["value"] = "Before"
    fetch_calls = []

    def unexpected_fetch(url: str, selector: str) -> str:
        fetch_calls.append((url, selector))
        return content["value"]

    monkeypatch.setattr("pagewatch.watch.fetch_text", unexpected_fetch)
    notified = []

    def record_notification(classification: Classification, time: str) -> None:
        notified.append((classification, time))

    result = check_watch(
        URL,
        SELECTOR,
        state_file,
        interest="Updates",
        classifier=fake_classifier,
        notifier=record_notification,
    )
    assert len(calls) == 2
    assert calls[0] == calls[1]
    assert fetch_calls == []
    assert notified == [(result.classification, detected_at)]
    assert json.loads(state_file.read_text())["text"] == "After"
    content["value"] = "After"
    assert (
        check_watch(
            URL,
            SELECTOR,
            state_file,
            interest="Updates",
            classifier=fake_classifier,
            notifier=record_notification,
        ).status
        == "unchanged"
    )
    assert len(notified) == 1


def test_existing_pending_snapshot_gets_stable_detection_time(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_file = tmp_path / "baseline.json"
    state_file.write_text(
        json.dumps(
            {
                "url": URL,
                "selector": SELECTOR,
                "text": "Before",
                "pending_text": "After",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "pagewatch.watch.fetch_text",
        lambda url, selector: pytest.fail("unexpected fetch"),
    )
    notified = []

    def failing_notifier(decision: Classification, detected_at: str) -> None:
        notified.append(detected_at)
        raise RuntimeError("SMTP unavailable")

    for _ in range(2):
        with pytest.raises(RuntimeError, match="SMTP unavailable"):
            check_watch(
                URL,
                SELECTOR,
                state_file,
                interest="Updates",
                classifier=lambda interest, diff: (
                    '{"relevant": true, "summary": "Changed", "reason": "Matches"}'
                ),
                notifier=failing_notifier,
            )
    state, detected_at = read_pending_state(state_file)
    assert state["pending_text"] == "After"
    assert notified == [detected_at, detected_at]


@pytest.mark.parametrize("legacy", [False, True])
def test_detection_only_watch_cannot_advance_unresolved_change(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    legacy: bool,
) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    state_file = state_dir / "first.json"
    state = {"url": URL, "selector": SELECTOR, "text": "Before"}
    if legacy:
        state["pending"] = True
    else:
        state["pending_text"] = "After"
    state_file.write_text(json.dumps(state), encoding="utf-8")
    original = state_file.read_bytes()
    monkeypatch.setattr(
        "pagewatch.watch.fetch_text",
        lambda url, selector: pytest.fail("unexpected fetch"),
    )

    args = ["watch", URL, "--selector", SELECTOR, "--state-file", str(state_file)]
    assert main(args) == 1
    assert "pending classification or notification" in capsys.readouterr().err
    assert state_file.read_bytes() == original


def test_legacy_pending_marker_is_replaced_with_snapshot_on_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_file = tmp_path / "baseline.json"
    state_file.write_text(
        json.dumps(
            {"url": URL, "selector": SELECTOR, "text": "Before", "pending": True}
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("pagewatch.watch.fetch_text", lambda url, selector: "After")

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
    assert json.loads(state_file.read_text())["pending_text"] == "After"

    result = check_watch(
        URL,
        SELECTOR,
        state_file,
        interest="Updates",
        classifier=lambda interest, diff: (
            '{"relevant": false, "summary": "Minor", "reason": "Outside interest"}'
        ),
    )
    assert result.classification == Classification(False, "Minor", "Outside interest")
    assert json.loads(state_file.read_text()) == {
        "url": URL,
        "selector": SELECTOR,
        "text": "After",
    }


def test_legacy_pending_marker_with_reverted_page_stays_unresolved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_file = tmp_path / "baseline.json"
    state_file.write_text(
        json.dumps(
            {"url": URL, "selector": SELECTOR, "text": "Before", "pending": True}
        ),
        encoding="utf-8",
    )
    original = state_file.read_bytes()
    monkeypatch.setattr("pagewatch.watch.fetch_text", lambda url, selector: "Before")

    with pytest.raises(
        WatchError, match="legacy pending change is no longer available"
    ):
        check_watch(
            URL,
            SELECTOR,
            state_file,
            interest="Updates",
            classifier=lambda interest, diff: pytest.fail("unexpected classification"),
        )
    assert state_file.read_bytes() == original
