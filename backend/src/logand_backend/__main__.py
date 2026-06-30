from __future__ import annotations

import argparse

import uvicorn

from logand_backend.app.app import App
from logand_backend.app.config import AppConfig


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="logand-backend")
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--database-url", dest="database_url", default=None)
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    cfg = AppConfig.from_external(args)
    uvicorn.run(App(cfg)(), host=cfg.host, port=cfg.port)


if __name__ == "__main__":
    main()
