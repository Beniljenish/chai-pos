"""Sending text through Twilio (README, "9.20"): SMS for phone codes, WhatsApp for the owner's
daily message. One small client, behind a seam so tests (and only tests) swap the connection.

What this does not cover: Twilio needs the account's own approvals before a message reaches an
Indian phone. SMS to India must use a sender and message wording registered with the telecom
regulator (DLT); WhatsApp needs a business sender, and a message the owner has not recently
written to the sender needs an approved template. Those are set up in Twilio's console by the
account owner; until then Twilio refuses the message and the app says so.
"""

import logging
import re

import httpx

from app.core.config import get_settings

log = logging.getLogger(__name__)
API = "https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"


class SendError(Exception):
    """Twilio refused the message or could not be reached. Never carries a phone number."""


def sms_on() -> bool:
    s = get_settings()
    return bool(s.twilio_account_sid and s.twilio_auth_token and s.twilio_sms_from)


def whatsapp_on() -> bool:
    s = get_settings()
    return bool(s.twilio_account_sid and s.twilio_auth_token and s.twilio_whatsapp_from)


def _scrub(text: str) -> str:
    return re.sub(r"\+?\d[\d\s-]{8,}\d", "[number]", text)[:200]


def _post(url: str, data: dict, auth: tuple[str, str]) -> httpx.Response:
    return httpx.post(url, data=data, auth=auth, timeout=8)


def send(to_e164: str, body: str, channel: str = "sms") -> str:
    """Send one message; returns Twilio's message id. `channel` is "sms" or "whatsapp"."""
    s = get_settings()
    if channel == "whatsapp":
        if not whatsapp_on():
            raise SendError("WhatsApp sending is not set up")
        sender, to = f"whatsapp:{s.twilio_whatsapp_from}", f"whatsapp:{to_e164}"
    else:
        if not sms_on():
            raise SendError("SMS sending is not set up")
        sender, to = s.twilio_sms_from, to_e164
    data = {"To": to, "Body": body}
    # A Messaging Service id and a plain number go in different fields.
    data["MessagingServiceSid" if sender.startswith("MG") else "From"] = sender
    try:
        r = _post(
            API.format(sid=s.twilio_account_sid), data, (s.twilio_account_sid, s.twilio_auth_token)
        )
    except httpx.HTTPError as e:
        raise SendError(f"Twilio not reachable ({type(e).__name__})") from None
    if r.status_code >= 400:
        try:
            why = r.json().get("message", "")
        except ValueError:
            why = r.text
        log.warning("twilio refused a message: %s", _scrub(str(why)))
        raise SendError(f"Twilio {r.status_code}: {_scrub(str(why))}")
    return str(r.json().get("sid", ""))
