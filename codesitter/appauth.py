"""GitHub App authentication — generates installation tokens.

Uses the org's `kyanitelabs` GitHub App (ID 3592379, installation 129423294)
so every codesitter interaction shows as `kyanitelabs[bot]` — its own badge,
avatar, and identity, separate from any personal account.

The private key lives at ~/.sinter/forgejo/github-app-key.pem (never committed).
Token generation: JWT from the app key → installation token → use as Bearer.
Tokens expire in 1 hour; regenerate per cycle.
"""

from __future__ import annotations

import json
import time
import urllib.request
from pathlib import Path

APP_ID = 3592379
INSTALLATION_ID = 129423294
KEY_PATH = Path.home() / ".sinter" / "forgejo" / "github-app-key.pem"


def _make_jwt() -> str:
    """Create a JWT signed with the app's private key (RS256)."""
    import jwt  # PyJWT

    private_key = KEY_PATH.read_text()
    now = int(time.time())
    payload = {"iat": now - 60, "exp": now + 600, "iss": str(APP_ID)}
    return jwt.encode(payload, private_key, algorithm="RS256")


def get_installation_token() -> str:
    """Generate a fresh installation token (1h expiry). Returns the token string."""
    jwt_token = _make_jwt()
    req = urllib.request.Request(
        f"https://api.github.com/app/installations/{INSTALLATION_ID}/access_tokens",
        method="POST",
        headers={
            "Authorization": f"Bearer {jwt_token}",
            "Accept": "application/vnd.github+json",
        },
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode())
    return data["token"]


def install_token_to_env() -> None:
    """Generate a token and set it as CODESITTER_GITHUB_TOKEN (replaces the PAT)."""
    import os

    token = get_installation_token()
    os.environ["CODESITTER_GITHUB_TOKEN"] = token
    # Also set GH_TOKEN so gh CLI uses it for any subsidiary calls
    os.environ["GH_TOKEN"] = token
