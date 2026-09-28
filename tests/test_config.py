"""Configured watch loading and batch execution checks."""

import json
import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from pagewatch.cli import main
from pagewatch.config import ConfigError, load_watches
from pagewatch.content import ContentError

TWO_WATCHES = """\
[[watches]]
id = "first"
url = "https://example.test/first"
selector = "main"
interest = "Price changes"

[[watches]]
id = "second"
url = "https://example.test/second"
selector = "h1"
interest = "Announcement updates"
"""


@pytest.fixture(autouse=True)
def stub_mailer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("pagewatch.cli.notifier_from_env", lambda: MagicMock())


def fake_classifier(interest: str, diff: str) -> str:
    return '{"relevant": false, "summary": "Minor edit", "reason": "Outside interest"}'


def test_loads_multiple_watches(tmp_path: Path) -> None:
    config = tmp_path / "watches.toml"
    config.write_text(TWO_WATCHES, encoding="utf-8")

    watches = load_watches(config)
    assert [
        (watch.id, watch.url, watch.selector, watch.interest) for watch in watches
    ] == [
        ("first", "https://example.test/first", "main", "Price changes"),
        ("second", "https://example.test/second", "h1", "Announcement updates"),
    ]


@pytest.mark.parametrize(
    "contents",
    [
        "[[watches]]\nid = '../escape'\nurl = 'https://example.test'\nselector = 'main'\ninterest = 'Updates'\n",
        TWO_WATCHES
        + "\n[[watches]]\nid = 'first'\nurl = 'https://example.test'\nselector = 'main'\ninterest = 'Updates'\n",
        "[[watches]]\nid = 'first'\nurl = 'https://example.test'\ninterest = 'Updates'\n",
        "[[watches]]\nid = 'first'\nurl = 'https://example.test'\nselector = 'main'\n",
        "watches = []\n",
        "[[watches]\n",
        "[[watches]]\nid = 'first'\nurl = 'https://example.test'\nselector = 'main'\ninterest = ''\n",
        "[[watches]]\nid = 'first'\nurl = 'https://example.test'\nselector = 'main'\ninterest = 'Updates'\nselektor = 'main'\n",
    ],
)
def test_rejects_invalid_config(tmp_path: Path, contents: str) -> None:
    config = tmp_path / "watches.toml"
    config.write_text(contents, encoding="utf-8")

    with pytest.raises(ConfigError):
        load_watches(config)


def test_run_uses_separate_baselines(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config = tmp_path / "watches.toml"
    config.write_text(TWO_WATCHES, encoding="utf-8")
    state_dir = tmp_path / "state"
    content = {"first": "Price 10", "second": "News today"}
    monkeypatch.setattr(
        "pagewatch.watch.fetch_text",
        lambda url, selector: content[url.rsplit("/", 1)[-1]],
    )
    monkeypatch.setattr("pagewatch.cli.classifier_from_env", lambda: fake_classifier)
    args = ["run", "--config", str(config), "--state-dir", str(state_dir)]

    assert main(args) == 0
    assert capsys.readouterr().out.splitlines() == [
        "first: baseline established",
        "second: baseline established",
    ]
    assert json.loads((state_dir / "first.json").read_text())["text"] == "Price 10"
    assert json.loads((state_dir / "second.json").read_text())["text"] == "News today"

    content["first"] = "Price 11"
    assert main(args) == 0
    output = capsys.readouterr()
    assert output.out.splitlines() == ["first: changed", "second: unchanged"]
    assert "INFO watch=first change detected" in output.err
    assert "Price 11" not in output.err
    assert json.loads((state_dir / "first.json").read_text())["text"] == "Price 11"
    assert json.loads((state_dir / "second.json").read_text())["text"] == "News today"


def test_one_failed_watch_does_not_stop_others(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config = tmp_path / "watches.toml"
    config.write_text(TWO_WATCHES, encoding="utf-8")
    state_dir = tmp_path / "state"
    monkeypatch.setattr("pagewatch.cli.classifier_from_env", lambda: fake_classifier)

    def fetch(url: str, selector: str) -> str:
        if url.endswith("/first"):
            raise ContentError("HTTP 500")
        return "News today"

    monkeypatch.setattr("pagewatch.watch.fetch_text", fetch)
    assert main(["run", "--config", str(config), "--state-dir", str(state_dir)]) == 1
    output = capsys.readouterr()
    assert "ERROR watch=first fetch failed" in output.err
    assert "HTTP 500" not in output.err
    assert "second: baseline established" in output.out
    assert not (state_dir / "first.json").exists()
    assert (state_dir / "second.json").exists()


def test_run_reports_state_failure_after_notification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config = tmp_path / "watches.toml"
    config.write_text(
        '[[watches]]\nid = "first"\nurl = "https://example.test/first"\n'
        'selector = "main"\ninterest = "Updates"\n',
        encoding="utf-8",
    )
    state_dir = tmp_path / "state"
    content = {"value": "Before"}
    monkeypatch.setattr(
        "pagewatch.watch.fetch_text", lambda url, selector: content["value"]
    )
    monkeypatch.setattr(
        "pagewatch.cli.classifier_from_env",
        lambda: (
            lambda interest, diff: (
                '{"relevant": true, "summary": "Changed", "reason": "Matches"}'
            )
        ),
    )
    mailer = MagicMock()
    monkeypatch.setattr("pagewatch.cli.notifier_from_env", lambda: mailer)
    args = ["run", "--config", str(config), "--state-dir", str(state_dir)]
    assert main(args) == 0
    capsys.readouterr()

    content["value"] = "After"
    replace = os.replace
    calls = 0

    def fail_final_replace(source: Path, target: Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("disk unavailable")
        replace(source, target)

    monkeypatch.setattr("pagewatch.watch.os.replace", fail_final_replace)
    assert main(args) == 1
    output = capsys.readouterr()
    assert output.out == ""
    assert "INFO watch=first notification sent" in output.err
    assert "ERROR watch=first state operation failed" in output.err
    assert "INFO watch=first state advanced" not in output.err
    assert "disk unavailable" not in output.err
    assert mailer.send.call_count == 1
    assert json.loads((state_dir / "first.json").read_text())["pending_text"] == (
        "After"
    )


def test_url_encoding_error_does_not_stop_other_watches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config = tmp_path / "watches.toml"
    config.write_text(
        TWO_WATCHES.replace("https://example.test/first", "https://example.test/é"),
        encoding="utf-8",
    )
    state_dir = tmp_path / "state"
    monkeypatch.setattr("pagewatch.cli.classifier_from_env", lambda: fake_classifier)
    response = MagicMock()
    response.__enter__.return_value = response
    response.read.return_value = b"<h1>News today</h1>"
    response.headers.get_content_charset.return_value = "utf-8"

    def open_page(url: str, timeout: int) -> MagicMock:
        if url.endswith("/é"):
            raise UnicodeEncodeError("ascii", "é", 0, 1, "ordinal not in range(128)")
        return response

    monkeypatch.setattr("pagewatch.content.urlopen", open_page)
    assert main(["run", "--config", str(config), "--state-dir", str(state_dir)]) == 1
    output = capsys.readouterr()
    assert "ERROR watch=first fetch failed" in output.err
    assert "Traceback" not in output.err
    assert "second: baseline established" in output.out
    assert not (state_dir / "first.json").exists()
    assert (state_dir / "second.json").exists()


def test_invalid_config_stops_before_running_watches(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = tmp_path / "watches.toml"
    config.write_text(
        TWO_WATCHES.replace('id = "second"', 'id = "first"'), encoding="utf-8"
    )
    state_dir = tmp_path / "state"

    assert main(["run", "--config", str(config), "--state-dir", str(state_dir)]) == 1
    assert "duplicate watch id" in capsys.readouterr().err
    assert not state_dir.exists()
