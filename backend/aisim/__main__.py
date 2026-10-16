"""Run the API server: ``python -m aisim`` (honours HOST, PORT, DATABASE_URL)."""

import logging
import os

import uvicorn


def main() -> None:
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    uvicorn.run("aisim.api.main:app", host=os.environ.get("HOST", "127.0.0.1"),
                port=int(os.environ.get("PORT", "8000")), log_level=os.environ.get("LOG_LEVEL", "info").lower())


if __name__ == "__main__":
    main()
