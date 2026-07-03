from __future__ import annotations

import json
from functools import lru_cache

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

# Throwaway keypair for tests -- generates a real, structurally valid
# Google service-account key file (the exact shape
# domain/notifications/mailer.py's _build_signed_jwt/_get_gmail_access_token
# expect via json.loads(cfg.gmail_service_account_json)), but with a key
# only this process's test run ever has the private half of. Never a real
# credential; never written anywhere outside test process memory.
#
# @lru_cache -- RSA key generation is not free (tens of milliseconds);
# every test in a session that needs a fake service account gets the SAME
# key, which is fine since no test here exercises key rotation/multiple-
# distinct-identities, only "is this a structurally valid signed JWT."


@lru_cache(maxsize=1)
def _keypair() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def fake_service_account_info(
    client_email: str = "fake-sa@fake-project.iam.gserviceaccount.com",
) -> dict:
    """Returns a dict, not a JSON string -- callers that need the raw
    env-var-shaped string (AppConfig.gmail_service_account_json) should
    json.dumps() this themselves; tests/unit/test_mailer.py's own tests
    of _build_signed_jwt take the dict directly, same as mailer.py's real
    json.loads(...) call site produces.
    """
    private_key_pem = (
        _keypair()
        .private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        .decode("ascii")
    )
    return {
        "type": "service_account",
        "project_id": "fake-project",
        "private_key_id": "fake-key-id",
        "private_key": private_key_pem,
        "client_email": client_email,
        "client_id": "000000000000000000000",
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
    }


def fake_service_account_json(
    client_email: str = "fake-sa@fake-project.iam.gserviceaccount.com",
) -> str:
    return json.dumps(fake_service_account_info(client_email))
