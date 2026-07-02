from __future__ import annotations

import socket
from email import message_from_bytes, policy
from email.message import EmailMessage

from aiosmtpd.controller import Controller
from aiosmtpd.smtp import Envelope, Session


def _free_port() -> int:
    # Controller's own port=0 "pick an ephemeral port" doesn't work here --
    # it tries to verify startup by connecting to `port` BEFORE the OS has
    # actually assigned one for port=0, which always fails with
    # ConnectionRefusedError. Picking a free port ourselves first (bind,
    # read it back, close) and passing that concrete port to Controller
    # sidesteps that chicken-and-egg problem, same trick used to pick free
    # ports for the fake_stripe/fake_paypal uvicorn doubles in tests.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# A real local SMTP server (aiosmtpd), not a mock of smtplib -- same
# reasoning as testing/fake_stripe.py and testing/fake_paypal.py: the real
# code in domain/notifications/mailer.py runs its actual smtplib.SMTP
# client against this, exercising the real SMTP wire protocol (EHLO,
# STARTTLS negotiation skipped since this double doesn't advertise it,
# MAIL FROM/RCPT TO/DATA) instead of mocking mailer.send_email away.
#
# TLS is deliberately NOT offered here -- AppConfig.smtp_use_tls must be
# False for tests pointed at this double, since aiosmtpd's plain Controller
# doesn't advertise STARTTLS and a client that tries it would just hang
# waiting on a capability this server never announces.


class _RecordingHandler:
    def __init__(self) -> None:
        self.messages: list[EmailMessage] = []

    async def handle_DATA(self, server, session: Session, envelope: Envelope) -> str:
        # decode_data defaults to False, so this is always real bytes --
        # the `bytes | str` typed as Envelope.content only reflects that
        # aiosmtpd's stub covers both configurations, not that this
        # handler's DATA is ever str.
        content = envelope.content
        assert isinstance(content, bytes)
        # policy=policy.default (not the module default compat32) -- gives
        # back real EmailMessage instances with .get_body()/.iter_attachments(),
        # matching what mailer.py actually constructs and sends.
        self.messages.append(message_from_bytes(content, policy=policy.default))
        return "250 Message accepted for delivery"


class FakeSmtpServer:
    """Started/stopped per-test (see tests/system/test_notifications.py) --
    Controller runs the SMTP server on a real background thread bound to
    an ephemeral or explicit port, exactly like the fake_stripe/fake_paypal
    uvicorn-based doubles run on their own thread/process.
    """

    def __init__(self, host: str = "127.0.0.1", port: int | None = None) -> None:
        self.handler = _RecordingHandler()
        self._port = port if port is not None else _free_port()
        self._controller = Controller(self.handler, hostname=host, port=self._port)

    def start(self) -> None:
        self._controller.start()

    def stop(self) -> None:
        self._controller.stop()

    @property
    def port(self) -> int:
        return self._port

    @property
    def messages(self) -> list[EmailMessage]:
        return self.handler.messages
