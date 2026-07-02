from __future__ import annotations

import logging
import uuid
from contextvars import ContextVar

# One request id per inbound HTTP request (see app/middleware.py), set at
# the very start of request handling and cleared at the end. A ContextVar
# (not a module global) because uvicorn serves requests concurrently on
# the same event loop -- a plain global would leak one request's id into
# another's log lines under real concurrent traffic.
_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)


def new_request_id() -> str:
    return uuid.uuid4().hex[:16]


def set_request_id(value: str | None) -> None:
    _request_id.set(value)


def get_request_id() -> str | None:
    return _request_id.get()


class RequestIdFilter(logging.Filter):
    """Attaches the current request id (if any) to every log record so a
    crash report can be grepped straight from a request id a user or the
    frontend's own crash reporter hands back -- see
    api/admin_logs.py and JsonLineFormatter, which reads record.request_id.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_request_id() or "-"
        return True
