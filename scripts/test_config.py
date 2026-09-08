"""Where does the app think it lives?

    venv\\Scripts\\python.exe scripts\\test_config.py

Regression guard for the 2026-09-09 bug: APP_BASE_URL on Render still said
line-task-bot.onrender.com after the service became line-task-bot-u5vn, so the
LINE Login redirect_uri pointed at a host that 404s and LINE answered 400.
RENDER_EXTERNAL_URL is injected by the platform and cannot drift, so it wins.
"""
import importlib
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

passed = failed = 0


def check(name, got, want):
    global passed, failed
    if got == want:
        passed += 1
        print(f"  PASS  {name}")
    else:
        failed += 1
        print(f"  FAIL  {name}: got {got!r}, want {want!r}")


def base_url_with(**env):
    for k in ("RENDER_EXTERNAL_URL", "APP_BASE_URL"):
        os.environ.pop(k, None)
    os.environ.update({k: v for k, v in env.items() if v is not None})
    import app.config
    importlib.reload(app.config)
    return app.config.base_url()


REAL = "https://line-task-bot-u5vn.onrender.com"
STALE = "https://line-task-bot.onrender.com"

check("platform URL wins over a stale manual one",
      base_url_with(RENDER_EXTERNAL_URL=REAL, APP_BASE_URL=STALE), REAL)
check("platform URL alone", base_url_with(RENDER_EXTERNAL_URL=REAL), REAL)
check("manual URL when not on Render", base_url_with(APP_BASE_URL=STALE), STALE)
check("neither set -> localhost", base_url_with(), "http://localhost:8000")
check("trailing slash stripped",
      base_url_with(RENDER_EXTERNAL_URL=REAL + "/"), REAL)
check("no double slash in the callback URL",
      base_url_with(RENDER_EXTERNAL_URL=REAL + "/") + "/auth/callback",
      REAL + "/auth/callback")

# auth.py builds CALLBACK_URL at import time — make sure it follows config.
os.environ["RENDER_EXTERNAL_URL"] = REAL
os.environ["APP_BASE_URL"] = STALE
import app.config
importlib.reload(app.config)
import app.auth
importlib.reload(app.auth)
check("auth.CALLBACK_URL follows config", app.auth.CALLBACK_URL, REAL + "/auth/callback")

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
