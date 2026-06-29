import base64
import json
import time
import urllib.error
import urllib.request
from abc import ABC, abstractmethod

from .logger import LOG

__all__ = ["Cli", "CliError"]


class CliError(RuntimeError):
    """A JSON-RPC call failed (transport error or an error response)."""


class Cli(ABC):
    """Abstract JSON-RPC client for a daemon"""

    TIMEOUT = 30

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
    def url(self) -> str:
        return "http://%s:%d" % (self._host, self._port)

    def _headers(self):
        headers = {"Content-Type": "application/json"}
        if self._user is not None and self._password is not None:
            headers["Authorization"] = (
                "Basic %s"
                % base64.b64encode(
                    ("%s:%s" % (self._user, self._password)).encode()
                ).decode()
            )
        return headers

    def call(self, method, *params):
        """Perform a JSON-RPC call."""
        payload = {
            "jsonrpc": self.jsonrpc_version,
            "id": "bornal",
            "method": method,
            "params": list(params),
        }
        request = urllib.request.Request(
            self.url,
            data=json.dumps(payload).encode(),
            headers=self._headers(),
            method="POST",
        )
        self._log.debug("$ rpc %s %s", method, list(params))
        try:
            with urllib.request.urlopen(request, timeout=self.TIMEOUT) as response:
                body = json.load(response)
        except urllib.error.HTTPError as exc:
            # Daemons (e.g. bitcoind) return RPC errors as HTTP 500 with a JSON
            # error body; read it so the message survives. A non-JSON body
            # (e.g. warmup 503) just becomes a transport error.
            try:
                body = json.load(exc)
            except (ValueError, OSError):
                raise CliError("rpc %s failed: HTTP %s" % (method, exc.code)) from exc
        except urllib.error.URLError as exc:
            raise CliError("rpc %s unreachable: %s" % (method, exc.reason)) from exc

        if body.get("error"):
            raise CliError("rpc %s error: %s" % (method, body["error"]))
        return body.get("result")

    def is_up(self) -> bool:
        """Whether the RPC server answers a trivial call."""
        try:
            self.call("uptime")
            return True
        except CliError:
            return False

    def wait_until_up(self, timeout=30, interval=0.25):
        """Block until the RPC server responds, or raise ``CliError`` on timeout."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.is_up():
                return
            time.sleep(interval)
        raise CliError("rpc server at %s not up after %ss" % (self.url, timeout))
