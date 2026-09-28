"""SMTP notification and configured-run delivery behavior."""

import json
import smtplib
import ssl
from datetime import datetime
from email.message import EmailMessage
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Self

import pytest

from pagewatch.classification import Classification
from pagewatch.cli import main
from pagewatch.mail import NotificationError, notifier_from_env

SMTP_ENV = {
    "PAGEWATCH_SMTP_HOST": "smtp.example.test",
    "PAGEWATCH_SMTP_PORT": "587",
    "PAGEWATCH_SMTP_USERNAME": "sender",
    "PAGEWATCH_SMTP_PASSWORD": "private-password",
    "PAGEWATCH_MAIL_FROM": "sender@example.test",
    "PAGEWATCH_MAIL_TO": "recipient@example.test",
}


@pytest.fixture
def smtp_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in SMTP_ENV.items():
        monkeypatch.setenv(name, value)


def test_smtp_message_is_plain_text_and_sent_after_starttls(
    monkeypatch: pytest.MonkeyPatch, smtp_env: None
) -> None:
    events = []
    sent = []

    class FakeSMTP:
        def __init__(self, host: str, port: int, *, timeout: int) -> None:
            assert (host, port, timeout) == ("smtp.example.test", 587, 20)

        def __enter__(self) -> Self:
            return self

        def __exit__(self, *args: object) -> None:
            pass

        def ehlo(self) -> None:
            events.append("ehlo")

        def starttls(self, *, context: ssl.SSLContext) -> None:
            assert context.check_hostname
            assert context.verify_mode == ssl.CERT_REQUIRED
            events.append("starttls")

        def login(self, username: str, password: str) -> None:
            assert (username, password) == ("sender", "private-password")
            events.append("login")

        def send_message(
            self, message: EmailMessage, *, from_addr: str, to_addrs: list[str]
        ) -> None:
            events.append("send")
            sent.append((message, from_addr, to_addrs))

    monkeypatch.setattr("pagewatch.mail.smtplib.SMTP", FakeSMTP)
    notifier_from_env().send(
        "uekat-biodo",
        "https://example.test/news",
        Classification(True, "Deadline moved", "Matches enrollment dates"),
        "2026-09-27T08:00:00+00:00",
    )

    assert events == ["ehlo", "starttls", "ehlo", "login", "send"]
    message, from_addr, to_addrs = sent[0]
    assert message["Subject"] == "[pagewatch] Relevant change: uekat-biodo"
    assert message["From"] == from_addr == "sender@example.test"
    assert message["To"] == to_addrs[0] == "recipient@example.test"
    assert parsedate_to_datetime(message["Date"]).utcoffset() is not None
    assert message.get_content_type() == "text/plain"
    body = message.get_content()
    assert "Summary:\nDeadline moved" in body
    assert "Reason:\nMatches enrollment dates" in body
    assert "Source:\nhttps://example.test/news" in body
    assert "Detected:\n2026-09-27T08:00:00+00:00" in body


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("PAGEWATCH_SMTP_PORT", "0"),
        ("PAGEWATCH_SMTP_PORT", "not-a-port"),
        ("PAGEWATCH_MAIL_TO", "one@example.test,two@example.test"),
        ("PAGEWATCH_MAIL_FROM", "sender@example.test\nBcc: other@example.test"),
    ],
)
def test_invalid_email_configuration_is_rejected(
    monkeypatch: pytest.MonkeyPatch, smtp_env: None, name: str, value: str
) -> None:
    monkeypatch.setenv(name, value)
    with pytest.raises(NotificationError, match=name):
        notifier_from_env()


def test_run_requires_email_settings_before_fetch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config = tmp_path / "watches.toml"
    config.write_text(
        '[[watches]]\nid = "news"\nurl = "https://example.test/news"\n'
        'selector = "main"\ninterest = "Deadlines"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr("pagewatch.cli.classifier_from_env", lambda: lambda *args: "")
    for name in SMTP_ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(
        "pagewatch.watch.fetch_text",
        lambda url, selector: pytest.fail("unexpected fetch"),
    )

    assert main(["run", "--config", str(config), "--state-dir", str(tmp_path)]) == 1
    assert "missing email configuration" in capsys.readouterr().err


def test_starttls_failure_prevents_login_and_send(
    monkeypatch: pytest.MonkeyPatch, smtp_env: None
) -> None:
    class FakeSMTP:
        def __init__(self, host: str, port: int, *, timeout: int) -> None:
            pass

        def __enter__(self) -> Self:
            return self

        def __exit__(self, *args: object) -> None:
            pass

        def ehlo(self) -> None:
            pass

        def starttls(self, *, context: ssl.SSLContext) -> None:
            raise smtplib.SMTPNotSupportedError("STARTTLS unavailable")

        def login(self, username: str, password: str) -> None:
            pytest.fail("login before STARTTLS")

        def send_message(self, message: EmailMessage, **kwargs: object) -> None:
            pytest.fail("send before STARTTLS")

    monkeypatch.setattr("pagewatch.mail.smtplib.SMTP", FakeSMTP)
    with pytest.raises(NotificationError, match="could not send email") as exc:
        notifier_from_env().send(
            "news",
            "https://example.test/news",
            Classification(True, "Changed", "Matches"),
            "2026-09-27T08:00:00+00:00",
        )
    assert "private-password" not in str(exc.value)


def test_invalid_message_text_is_a_notification_error(
    monkeypatch: pytest.MonkeyPatch, smtp_env: None
) -> None:
    monkeypatch.setattr(
        "pagewatch.mail.smtplib.SMTP",
        lambda *args, **kwargs: pytest.fail("unexpected SMTP connection"),
    )
    with pytest.raises(NotificationError, match="could not send email"):
        notifier_from_env().send(
            "news",
            "https://example.test/news",
            Classification(True, "\ud800", "Matches"),
            "2026-09-27T08:00:00+00:00",
        )


def test_run_retries_failed_delivery_and_continues_other_watches(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    smtp_env: None,
) -> None:
    config = tmp_path / "watches.toml"
    config.write_text(
        """\
[[watches]]
id = "first"
url = "https://example.test/first"
selector = "main"
interest = "Dates"
[[watches]]
id = "second"
url = "https://example.test/second"
selector = "main"
interest = "Prices"
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "pagewatch.cli.classifier_from_env",
        lambda: (
            lambda interest, diff: json.dumps(
                {"relevant": True, "summary": "Changed", "reason": "Matches interest"}
            )
        ),
    )
    content = {"first": "Before", "second": "Before"}
    monkeypatch.setattr(
        "pagewatch.watch.fetch_text",
        lambda url, selector: content[url.rsplit("/", 1)[-1]],
    )
    failed = {"first": True}
    sent = []

    class FakeSMTP:
        def __init__(self, host: str, port: int, *, timeout: int) -> None:
            pass

        def __enter__(self) -> Self:
            return self

        def __exit__(self, *args: object) -> None:
            pass

        def ehlo(self) -> None:
            pass

        def starttls(self, *, context: ssl.SSLContext) -> None:
            pass

        def login(self, username: str, password: str) -> None:
            pass

        def send_message(self, message: EmailMessage, **kwargs: object) -> None:
            if message["Subject"].endswith("first") and failed["first"]:
                raise smtplib.SMTPDataError(451, b"try later")
            sent.append(message)

    monkeypatch.setattr("pagewatch.mail.smtplib.SMTP", FakeSMTP)
    state_dir = tmp_path / "state"
    args = ["run", "--config", str(config), "--state-dir", str(state_dir)]
    assert main(args) == 0
    assert "baseline established" in capsys.readouterr().out
    assert sent == []

    content.update(first="After", second="After")
    assert main(args) == 1
    output = capsys.readouterr()
    assert "ERROR watch=first notification failed" in output.err
    assert "INFO watch=second classification relevant=true" in output.err
    assert output.out.strip() == "second: changed"
    first_state = json.loads((state_dir / "first.json").read_text())
    detected_at = first_state["detected_at"]
    assert datetime.fromisoformat(detected_at).utcoffset() is not None
    assert first_state["text"] == "Before"
    assert first_state["pending_text"] == "After"
    assert json.loads((state_dir / "second.json").read_text())["text"] == "After"
    assert len(sent) == 1

    failed["first"] = False
    content["first"] = "Before"
    assert main(args) == 0
    retry_output = capsys.readouterr()
    assert retry_output.out.strip() == "first: changed\nsecond: unchanged"
    assert "INFO watch=first notification sent" in retry_output.err
    assert json.loads((state_dir / "first.json").read_text()) == {
        "url": "https://example.test/first",
        "selector": "main",
        "text": "After",
    }
    assert len(sent) == 2
    assert f"Detected:\n{detected_at}" in sent[-1].get_content()
