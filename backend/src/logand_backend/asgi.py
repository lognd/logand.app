from __future__ import annotations

import argparse

from logand_backend.app.app import App
from logand_backend.app.config import AppConfig

# Module-level ASGI app for `uvicorn logand_backend.asgi:app` (see backend/Dockerfile).
# __main__.py is the CLI entry point for local/dev use; this is the production one,
# since uvicorn's string-import form needs a plain module attribute, not a callable class.
# AppConfig.from_external takes an argparse.Namespace -- pass an empty one so it falls
# back entirely to env vars (loaded via load_dotenv() inside from_external).
app = App(AppConfig.from_external(argparse.Namespace())).__call__()
