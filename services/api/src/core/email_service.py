import asyncio
import json
import logging
import smtplib
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import formataddr
from pathlib import Path

from .config import (
    EMAIL_DELIVERY_MODE,
    EMAIL_ENABLED,
    EMAIL_FROM,
    EMAIL_FROM_NAME,
    EMAIL_MOCK_OUTPUT_DIR,
    EMAIL_PROVIDER,
    EMAIL_REPLY_TO,
    SMTP_HOST,
    SMTP_PASSWORD,
    SMTP_PORT,
    SMTP_TIMEOUT_SECONDS,
    SMTP_USERNAME,
    SMTP_USE_SSL,
    SMTP_USE_TLS,
)

logger = logging.getLogger(__name__)


class EmailServiceError(RuntimeError):
    pass


@dataclass
class OutboundEmail:
    subject: str
    recipient: str
    text_body: str
    html_body: str
    purpose: str = ""
    action_url: str = ""
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class SmtpEmailService:
    async def send(self, payload: OutboundEmail) -> None:
        await asyncio.to_thread(self._send_sync, payload)

    def _send_sync(self, payload: OutboundEmail) -> None:
        message = EmailMessage()
        message["Subject"] = payload.subject
        message["From"] = formataddr((EMAIL_FROM_NAME, EMAIL_FROM))
        message["To"] = payload.recipient
        if EMAIL_REPLY_TO:
            message["Reply-To"] = EMAIL_REPLY_TO
        message.set_content(payload.text_body)
        message.add_alternative(payload.html_body, subtype="html")

        if SMTP_USE_SSL:
            server = smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=SMTP_TIMEOUT_SECONDS)
        else:
            server = smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=SMTP_TIMEOUT_SECONDS)

        try:
            if SMTP_USE_TLS and not SMTP_USE_SSL:
                server.starttls()
            if SMTP_USERNAME and SMTP_PASSWORD:
                server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.send_message(message)
        finally:
            try:
                server.quit()
            except Exception:
                pass


class MockEmailService:
    def __init__(self, output_dir: str):
        self._output_dir = Path(output_dir)

    async def send(self, payload: OutboundEmail) -> None:
        await asyncio.to_thread(self._write_sync, payload)

    def _write_sync(self, payload: OutboundEmail) -> None:
        self._output_dir.mkdir(parents=True, exist_ok=True)
        safe_purpose = (payload.purpose or "generic").replace("/", "-").replace("\\", "-")
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        file_path = self._output_dir / f"{stamp}_{safe_purpose}_{uuid.uuid4().hex[:8]}.json"
        body = {
            **asdict(payload),
            "delivery_mode": "mock",
            "from": EMAIL_FROM,
            "reply_to": EMAIL_REPLY_TO,
        }
        file_path.write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info(
            "Mock password email written: recipient=%s subject=%s purpose=%s action_url=%s file=%s",
            payload.recipient,
            payload.subject,
            payload.purpose,
            payload.action_url,
            file_path,
        )


def get_email_service():
    if not EMAIL_ENABLED:
        raise EmailServiceError("Email delivery is not enabled in the current DEV configuration.")
    if str(EMAIL_PROVIDER or "").strip().lower() != "smtp":
        raise EmailServiceError("Only SMTP email delivery is supported in DEV.")

    delivery_mode = str(EMAIL_DELIVERY_MODE or "smtp").strip().lower()
    if delivery_mode in {"mock", "file"}:
        if not str(EMAIL_FROM or "").strip():
            raise EmailServiceError("Email delivery is not fully configured: missing EMAIL_FROM")
        return MockEmailService(EMAIL_MOCK_OUTPUT_DIR)

    if delivery_mode != "smtp":
        raise EmailServiceError(f"Unsupported EMAIL_DELIVERY_MODE: {EMAIL_DELIVERY_MODE}")

    missing = [
        key
        for key, value in (
            ("EMAIL_FROM", EMAIL_FROM),
            ("SMTP_HOST", SMTP_HOST),
            ("SMTP_USERNAME", SMTP_USERNAME),
            ("SMTP_PASSWORD", SMTP_PASSWORD),
        )
        if not str(value or "").strip()
    ]
    if missing:
        raise EmailServiceError(f"Email delivery is not fully configured: missing {', '.join(missing)}")
    return SmtpEmailService()


def build_password_email(
    *,
    recipient: str,
    subject: str,
    heading: str,
    intro: str,
    cta_label: str,
    action_url: str,
    expiry_hint: str,
    purpose: str,
) -> OutboundEmail:
    text_body = "\n".join(
        [
            heading,
            "",
            intro,
            action_url,
            "",
            expiry_hint,
            "",
            "If you did not request this email, you can ignore it.",
        ]
    )
    html_body = f"""
    <html>
      <body style="font-family: Arial, sans-serif; background:#f6f7fb; padding:24px; color:#223;">
        <div style="max-width:560px; margin:0 auto; background:#ffffff; border-radius:20px; padding:32px; box-shadow:0 18px 44px rgba(15,23,42,0.08);">
          <p style="margin:0 0 12px; font-size:12px; letter-spacing:0.14em; color:#8a93a6;">YS</p>
          <h1 style="margin:0 0 16px; font-size:28px; color:#10253f;">{heading}</h1>
          <p style="margin:0 0 24px; font-size:15px; line-height:1.7; color:#44546a;">{intro}</p>
          <a href="{action_url}" style="display:inline-block; background:#9b1c16; color:#ffffff; text-decoration:none; padding:14px 22px; border-radius:999px; font-weight:700;">
            {cta_label}
          </a>
          <p style="margin:24px 0 0; font-size:13px; line-height:1.7; color:#6c778c;">{expiry_hint}</p>
          <p style="margin:12px 0 0; font-size:13px; line-height:1.7; color:#6c778c;">
            If the button does not work, copy and paste this link into your browser:<br />
            <a href="{action_url}">{action_url}</a>
          </p>
        </div>
      </body>
    </html>
    """.strip()
    logger.info(
        "Prepared password email: recipient=%s subject=%s purpose=%s action_url=%s",
        recipient,
        subject,
        purpose,
        action_url,
    )
    return OutboundEmail(
        subject=subject,
        recipient=recipient,
        text_body=text_body,
        html_body=html_body,
        purpose=purpose,
        action_url=action_url,
    )
