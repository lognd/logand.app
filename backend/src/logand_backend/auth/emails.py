from __future__ import annotations

import re

# Deliberately conservative and deliberately NOT an RFC 5322 parser. The only
# job here is to reject input that could never be delivered -- a missing "@",
# whitespace, no dot in the domain -- before it becomes a `users` row and a
# bounced send. Anything that looks plausibly deliverable is accepted; the
# authoritative test of an address is whether the verification mail to it is
# ever clicked, which is exactly the proof this whole feature is built on
# (see docs/design/17).
#
# Not using pydantic's EmailStr: that pulls in the `email-validator`
# dependency for a check this strict-but-shallow, and the real gate is the
# emailed token, not the regex.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$")

# Postgres `text` has no length cap, but an unbounded address is a cheap way
# to bloat a row and every log line that ever mentions it. 254 is the RFC 5321
# limit on a forward path.
_MAX_EMAIL_LENGTH = 254


def normalize_email(raw: str) -> str:
    """The single definition of "the same email address" for this codebase.

    Lookups compare `func.lower(User.email)` against this, and every write
    stores this, so a normalization that lived in four call sites (it did)
    is a desync waiting to hand one person two accounts.
    """
    return raw.strip().lower()


def is_valid_email(email: str) -> bool:
    """True when `email` is plausibly deliverable.

    Called before creating a `users` row from untrusted input -- self
    registration and, importantly, an admin typing a `customer_email` on an
    invoice. Without it a typo silently becomes a permanent contact row that
    can never be invoiced successfully, never receives its claim link, and
    can never be deleted once an invoice references it
    (invoices.customer_id is ON DELETE RESTRICT).
    """
    return len(email) <= _MAX_EMAIL_LENGTH and bool(_EMAIL_RE.match(email))
