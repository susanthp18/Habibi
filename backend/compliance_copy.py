"""Statutory disclosures, composed in one place.

RBI's amendment (¶100AA) requires the grievance redressal officer's name,
email and telephone number in **all recovery communications**. Not most of
them, not the ones with a payment link, not the ones a template happened to
carry — all of them.

The reason this is a module rather than a string in each sender is that the
failure mode is silent and additive. ``voice/amd.py`` had the defect and it was
found. ``treatment/enact.py`` had it too, and its docstring cheerfully claimed
otherwise:

    RBI's Digital Lending Guidelines require the regulated entity, the loan
    reference and a grievance route to be identifiable on any collections
    communication.

The body it returned ended ``"Queries: reply to this message."`` — which is a
reply-to, not a grievance route, and the docstring made it look handled. A
channel added next year would have been written by copying one of those two.

So: one renderer, and every recovery communication in the system asks it for a
footer. A sender that cannot get one does not send. That is the same call made
for the voicemail path, made once, and it is deliberately the strict reading —
the duty is not "name the officer when convenient", and a recovery message that
omits the disclosure is a defect whether it went by voice or by SMS.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

#: Recorded on whatever the sender writes when it refuses to send.
NO_GRIEVANCE_CONTACT = "no_grievance_contact"


def tenant_contacts(tenant_id: str | None = None) -> dict[str, Any]:
    """Issuer name, grievance officer and callback number. Never raises.

    Returns ``{}`` when the tenant is unreadable or absent, which callers must
    treat as "no disclosure available" rather than as an empty-but-fine result.
    """
    try:
        import db as dbmod
        from sqlalchemy import text

        tid = (tenant_id or "").strip() or dbmod.current_tenant()
        with dbmod.engine.connect() as conn:
            row = (
                conn.execute(
                    text(
                        "SELECT name, grievance_officer, contact_number "
                        "FROM tenants WHERE id = :id"
                    ),
                    {"id": tid},
                )
                .mappings()
                .first()
            )
        if row is None:
            return {}
        officer = row["grievance_officer"]
        if not isinstance(officer, dict):
            officer = {}
        return {
            "issuer": row["name"],
            "officer": officer,
            "contactNumber": row["contact_number"],
        }
    except Exception:
        logger.debug("tenant contacts unreadable", exc_info=True)
        return {}


def spoken_number(raw: str | None) -> str:
    """Digits, spaced, so TTS reads them out rather than as one huge integer."""
    digits = "".join(ch for ch in str(raw or "") if ch.isdigit())
    return " ".join(digits) if digits else ""


def officer_of(contacts: dict[str, Any] | None) -> dict[str, str]:
    """The officer's name/phone/email, or ``{}`` when incomplete.

    Name **and** phone are the minimum; an officer with a name and no way to
    reach them is not a grievance route. Email is included when present and is
    not required, because a borrower on a feature phone reading an SMS has a
    phone number and may have no mailbox.
    """
    officer = (contacts or {}).get("officer")
    if not isinstance(officer, dict):
        return {}
    name = str(officer.get("name") or "").strip()
    phone = str(officer.get("phone") or "").strip()
    if not name or not phone:
        return {}
    out = {"name": name, "phone": phone}
    email = str(officer.get("email") or "").strip()
    if email:
        out["email"] = email
    return out


def written_footer(contacts: dict[str, Any] | None = None) -> str | None:
    """The disclosure as it appears on an SMS or WhatsApp body.

    ``None`` means the tenant has no grievance officer on file and the message
    must not be sent. Callers record :data:`NO_GRIEVANCE_CONTACT`.
    """
    resolved = contacts if contacts is not None else tenant_contacts()
    officer = officer_of(resolved)
    if not officer:
        logger.warning(
            "recovery communication suppressed: tenant has no grievance officer "
            "on file (RBI para 100AA requires one in every recovery communication)"
        )
        return None
    parts = [f"Grievance officer: {officer['name']}, {officer['phone']}"]
    if officer.get("email"):
        parts.append(officer["email"])
    return " · ".join(parts) + "."


def spoken_footer(contacts: dict[str, Any] | None = None) -> str | None:
    """The same disclosure, said aloud.

    Digits are spaced because TTS otherwise reads ``18002026161`` as a number in
    the billions, and an email address is omitted because nobody has ever
    successfully transcribed one from a voicemail.
    """
    resolved = contacts if contacts is not None else tenant_contacts()
    officer = officer_of(resolved)
    if not officer:
        return None
    return (
        "If you have any concerns you can reach our grievance officer, "
        f"{officer['name']}, on {spoken_number(officer['phone'])}."
    )
