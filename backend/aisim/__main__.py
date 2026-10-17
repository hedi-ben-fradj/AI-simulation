"""Run the server: ``python -m aisim``.

Reads settings from the environment and from a ``.env`` file (in the current
directory or ``backend/``) without overriding variables that are already set.
If the frontend has been built (``frontend/dist``), it is served on the same
port, so the whole app is at http://HOST:PORT.
"""

import logging
import os
from pathlib import Path

import uvicorn

BACKEND_DIR = Path(__file__).resolve().parents[1]


def load_dotenv() -> list[Path]:
    loaded = []
    for path in (Path.cwd() / ".env", BACKEND_DIR / ".env"):
        if not path.is_file() or path in loaded:
            continue
        for raw in path.read_text().splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key, value = key.strip().removeprefix("export ").strip(), value.strip().strip('"').strip("'")
            if key and value and key not in os.environ:
                os.environ[key] = value
        loaded.append(path)
    return loaded


def main() -> None:
    loaded = load_dotenv()
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO").upper(),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    log = logging.getLogger("aisim")
    for path in loaded:
        log.info("loaded settings from %s", path)
    host, port = os.environ.get("HOST", "127.0.0.1"), int(os.environ.get("PORT", "8000"))
    from .api.app import default_static_dir

    if default_static_dir():
        log.info("open http://%s:%d in your browser", "localhost" if host in ("127.0.0.1", "0.0.0.0") else host, port)
    else:
        log.info("API on http://%s:%d (frontend not built: run 'npm run build' in frontend/, "
                 "or use the dev server on http://localhost:5173)", host, port)
    # timeout_graceful_shutdown: Ctrl+C never waits more than a few seconds for slow requests.
    uvicorn.run("aisim.api.main:app", host=host, port=port, log_level=os.environ.get("LOG_LEVEL", "info").lower(),
                timeout_graceful_shutdown=5)


if __name__ == "__main__":
    main()
