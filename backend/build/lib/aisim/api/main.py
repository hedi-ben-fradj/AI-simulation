"""ASGI entrypoint: ``uvicorn aisim.api.main:app``."""

from .app import create_app

app = create_app()
