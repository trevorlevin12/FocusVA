"""OAuth2 authentication for Gmail (Web Application flow)."""

import json
import secrets
import time
from pathlib import Path

import config

SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]

_pending_states: dict[str, float] = {}


def get_oauth_flow():
    from google_auth_oauthlib.flow import Flow
    return Flow.from_client_secrets_file(
        config.GMAIL_CREDENTIALS_PATH,
        scopes=SCOPES,
        redirect_uri=config.GMAIL_REDIRECT_URI,
    )


def is_authenticated() -> bool:
    """True if a valid (or refreshable) token exists on disk."""
    if not config.GMAIL_CREDENTIALS_PATH:
        return False
    if not Path(config.GMAIL_TOKEN_PATH).exists():
        return False
    try:
        creds = _load_credentials()
        return creds.valid or (creds.expired and creds.refresh_token is not None)
    except Exception:
        return False


def get_credentials():
    """Load token, refresh if expired, return google.oauth2.credentials.Credentials."""
    from google.auth.transport.requests import Request
    creds = _load_credentials()
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        _save_credentials(creds)
    return creds


def get_auth_url() -> str:
    """Generate Google consent URL. Stores CSRF state with 5-minute TTL."""
    global _pending_states
    now = time.time()
    _pending_states = {s: t for s, t in _pending_states.items() if now - t < 300}
    state = secrets.token_hex(16)
    _pending_states[state] = now
    flow = get_oauth_flow()
    url, _ = flow.authorization_url(
        state=state,
        access_type="offline",
        prompt="consent",
    )
    return url


def exchange_code(code: str, state: str) -> None:
    """Validate CSRF state, exchange auth code for tokens, save to disk."""
    now = time.time()
    if state not in _pending_states or now - _pending_states[state] > 300:
        raise ValueError("Invalid or expired OAuth state. Please try signing in again.")
    del _pending_states[state]
    flow = get_oauth_flow()
    flow.fetch_token(code=code)
    _save_credentials(flow.credentials)


def _load_credentials():
    from google.oauth2.credentials import Credentials
    with open(config.GMAIL_TOKEN_PATH) as f:
        data = json.load(f)
    return Credentials(
        token=data.get("token"),
        refresh_token=data.get("refresh_token"),
        token_uri=data.get("token_uri"),
        client_id=data.get("client_id"),
        client_secret=data.get("client_secret"),
        scopes=data.get("scopes"),
    )


def _save_credentials(creds) -> None:
    data = {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": list(creds.scopes) if creds.scopes else SCOPES,
    }
    with open(config.GMAIL_TOKEN_PATH, "w") as f:
        json.dump(data, f)
