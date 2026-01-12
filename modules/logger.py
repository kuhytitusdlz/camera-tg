from __future__ import annotations

import os
import re
from datetime import datetime

from dotenv import load_dotenv


# Ensure .env is loaded even if this module is imported outside main.py.
load_dotenv()


def _is_debug() -> bool:
    v = os.getenv("DEBUG", "0").strip().lower()
    return v in {"1", "true", "yes", "y", "on"}


_DEBUG = _is_debug()


def _secret_values() -> list[str]:
    # Intentionally keep the set small and high-signal.
    # We primarily want to prevent leaking tokens/passwords into container logs.
    vals: list[str] = []
    for k in ("TG_TOKEN", "ONVIF_PASS"):
        v = (os.getenv(k, "") or "").strip()
        if v:
            vals.append(v)
    return vals


_SECRETS = _secret_values()


_RE_RTSP_PASSWORD = re.compile(r"(rtsp://[^\s]*?password=)([^&\s]+)", re.IGNORECASE)
_RE_HTTP_PASSWORD_QS = re.compile(r"([?&](?:pass|password|pwd)=)([^&\s]+)", re.IGNORECASE)
_RE_TG_BOT_TOKEN_IN_PATH = re.compile(r"(api\.telegram\.org/bot)([^/\s]+)", re.IGNORECASE)


def _sanitize(text: str) -> str:
    if _DEBUG:
        return text

    out = text

    # Redact known secret values (exact matches).
    for s in _SECRETS:
        out = out.replace(s, "<redacted>")

    # Redact common patterns (best-effort).
    out = _RE_TG_BOT_TOKEN_IN_PATH.sub(r"\1<redacted>", out)
    out = _RE_RTSP_PASSWORD.sub(r"\1<redacted>", out)
    out = _RE_HTTP_PASSWORD_QS.sub(r"\1<redacted>", out)
    return out


def log(message: str):
    msg = _sanitize(message)
    print(f"{datetime.now().isoformat()} {msg}")
