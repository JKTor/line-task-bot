"""Where this app thinks it lives.

Every module used to read APP_BASE_URL on its own, so one stale value broke four
things at once: the LINE Login redirect_uri (LINE answers 400), the keep-alive
self-ping (silently hitting a dead host, letting Render sleep), the upgrade link,
and the Secure-cookie decision.

Render always injects RENDER_EXTERNAL_URL with the service's real URL, so trust
that first — it cannot drift when the service is renamed. APP_BASE_URL stays as
the manual override for anywhere else.
"""
import os

_FALLBACK = "http://localhost:8000"


def base_url() -> str:
    url = (os.getenv("RENDER_EXTERNAL_URL")
           or os.getenv("APP_BASE_URL")
           or _FALLBACK)
    return url.rstrip("/")


APP_BASE_URL = base_url()

_manual = (os.getenv("APP_BASE_URL") or "").rstrip("/")
if _manual and _manual != APP_BASE_URL:
    print(f"[config] ignoring APP_BASE_URL={_manual!r} — the platform reports {APP_BASE_URL!r}")
