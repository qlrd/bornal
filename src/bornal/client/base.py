import base64
import time

from abc import ABC, abstractmethod
from typing import Any, Literal

from bornal.logger import LOG

__all__ = ["ClientError", "BaseClient"]


class ClientError(RuntimeError):
    """A JSON-RPC call failed (transport error or an error response)."""


class BaseClient(ABC):
    """Abstract JSON-RPC client for a daemon"""

    TIMEOUT = 30

    _id = -1
    """Current id property of payload used in ``Client.call``"""

    def __init__(self, host, port, user=None, password=None, log=None):
        self._host = host
        self._port = port
        self._user = user
        self._password = password
        self._log = log or LOG

    @property
    @abstractmethod
    def jsonrpc_version(self) -> str:
        """The JSON-RPC dialect the daemon speaks (e.g. ``"1.0"``)."""

    @property
    @abstractmethod
    def name(
        self,
    ) -> (
        Literal["bitcoin-core"]
        | Literal["electrs"]
        | Literal["floresta"]
        | Literal["btcd"]
        | Literal["utreexo"]
        | Literal["Liana"]
        | Literal["frigate"]
    ):
        """Name of client for inherited classes"""

    @property
    @abstractmethod
    def url(self) -> str:
        """endpoint for requests"""

    @property
    @abstractmethod
    def requires_auth(self) -> bool:
        """Refuse to send a call without basic-auth credentials"""

    @abstractmethod
    def on_call(self, method, payload) -> dict[str, Any]:
        """Perform JSONRPC calls or TCP socket calls. This will implement the
        current `call`."""

    @abstractmethod
    def is_up(self) -> bool:
        """Perform some call that verifies that node is up"""

    def call(self, method, *params):
        """Perform a JSON-RPC call over the transport ``_send`` implements."""
        if self.requires_auth and "Authorization" not in self.make_headers():
            raise ClientError("Not authorized")

        self._id += 1
        payload = {
            "jsonrpc": self.jsonrpc_version,
            "id": self._id,
            "method": method,
            "params": list(params),
        }
        self._log.debug(f"{method} {list(params)}")
        body = self.on_call(method, payload)

        try:
            err = body.get("error")
            if err:
                raise ClientError(f"rpc {method} error: {err}")
            return body.get("result")

        except Exception as exc:
            raise ClientError(f"Unknown error: {exc}") from exc

    def wait_until_up(self, timeout=30, interval=0.25):
        """Block until the RPC server responds, or raise ``ClientError`` on timeout."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.is_up():
                return
            time.sleep(interval)
        raise ClientError("rpc server at %s not up after %ss" % (self.url, timeout))

    def make_headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._user is not None and self._password is not None:
            headers["Authorization"] = (
                "Basic %s"
                % base64.b64encode(
                    ("%s:%s" % (self._user, self._password)).encode()
                ).decode()
            )
        return headers
