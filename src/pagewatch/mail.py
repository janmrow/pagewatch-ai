"""Send relevant-change notices through authenticated SMTP with STARTTLS."""

import os
import smtplib
import ssl
from dataclasses import dataclass
from datetime import UTC, datetime
from email.errors import HeaderParseError
from email.headerregistry import Address
from email.message import EmailMessage
from email.utils import format_datetime

from pagewatch.classification import Classification


class NotificationError(Exception):
    """Email configuration or delivery failed."""


@dataclass(frozen=True)
class SMTPNotifier:
    host: str
    port: int
    username: str
    password: str
    mail_from: str
    mail_to: str

    def send(
        self, watch_id: str, source_url: str, decision: Classification, detected_at: str
    ) -> None:
        try:
            message = EmailMessage()
            message["From"] = self.mail_from
            message["To"] = self.mail_to
            message["Date"] = format_datetime(datetime.now(UTC))
            message["Subject"] = f"[pagewatch] Relevant change: {watch_id}"
            message.set_content(
                f"A relevant change was detected for {watch_id}.\n\n"
                f"Summary:\n{decision.summary}\n\n"
                f"Reason:\n{decision.reason}\n\n"
                f"Source:\n{source_url}\n\n"
                f"Detected:\n{detected_at}\n"
            )
            with smtplib.SMTP(self.host, self.port, timeout=20) as smtp:
                smtp.ehlo()
                smtp.starttls(context=ssl.create_default_context())
                smtp.ehlo()
                smtp.login(self.username, self.password)
                smtp.send_message(
                    message, from_addr=self.mail_from, to_addrs=[self.mail_to]
                )
        except (OSError, RuntimeError, ValueError) as exc:
            raise NotificationError("could not send email") from exc


def notifier_from_env() -> SMTPNotifier:
    """Require one recipient and SMTP settings before any watch runs."""
    names = (
        "PAGEWATCH_SMTP_HOST",
        "PAGEWATCH_SMTP_PORT",
        "PAGEWATCH_SMTP_USERNAME",
        "PAGEWATCH_SMTP_PASSWORD",
        "PAGEWATCH_MAIL_FROM",
        "PAGEWATCH_MAIL_TO",
    )
    values = {name: os.environ.get(name, "") for name in names}
    missing = [name for name in names if not values[name].strip()]
    if missing:
        raise NotificationError(f"missing email configuration: {', '.join(missing)}")

    host = values["PAGEWATCH_SMTP_HOST"].strip()
    if any(char.isspace() for char in host):
        raise NotificationError("PAGEWATCH_SMTP_HOST must be a hostname")
    try:
        port = int(values["PAGEWATCH_SMTP_PORT"].strip())
    except ValueError as exc:
        raise NotificationError(
            "PAGEWATCH_SMTP_PORT must be between 1 and 65535"
        ) from exc
    if not 1 <= port <= 65535:
        raise NotificationError("PAGEWATCH_SMTP_PORT must be between 1 and 65535")

    addresses = []
    for name in ("PAGEWATCH_MAIL_FROM", "PAGEWATCH_MAIL_TO"):
        value = values[name].strip()
        try:
            address = Address(addr_spec=value)
        except (ValueError, HeaderParseError) as exc:
            raise NotificationError(f"{name} must be one email address") from exc
        if str(address) != value or not address.username or not address.domain:
            raise NotificationError(f"{name} must be one email address")
        addresses.append(value)

    return SMTPNotifier(
        host,
        port,
        values["PAGEWATCH_SMTP_USERNAME"].strip(),
        values["PAGEWATCH_SMTP_PASSWORD"],
        *addresses,
    )
