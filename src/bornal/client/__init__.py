import json
import socket
from typing import Any
import urllib.error
import urllib.request

from bornal.client.base import ClientError, BaseClient

__all__ = ["Client", "ElectrumClient"]


class Client(BaseClient):
    """Client to be  JSON-RPC client for a daemon"""

    @property
    def jsonrpc_version(self) -> str:
        return "1.0"

    @property
    def requires_auth(self):
        return True

    @property
    def url(self) -> str:
        return "http://%s:%d" % (self._host, self._port)

    def on_call(self, method, payload) -> dict[str, Any]:
        """POST ``payload`` to ``url`` and return the decoded response body."""
        request = urllib.request.Request(
            self.url,
            data=json.dumps(payload).encode(),
            headers=self.make_headers(),
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.TIMEOUT) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            # Daemons (e.g. bitcoind) return RPC errors as HTTP 500 with a JSON
            # error body; read it so the message survives.
            try:
                return json.load(exc)
            except (ValueError, OSError):
                if not getattr(self, "name", None):
                    raise ClientError(
                        "Abstract client or undefined client without name"
                    )
                raise ClientError(
                    f"{self.name} {method} failed: HTTP {exc.code}"
                ) from exc
        except urllib.error.URLError as exc:
            raise ClientError("rpc %s unreachable: %s" % (method, exc.reason)) from exc

    def is_up(self) -> bool:
        """Whether the RPC server answers a trivial call."""
        try:
            self.call("uptime")
            return True
        except ClientError:
            return False


class ElectrumClient(BaseClient):
    """General Electrum-protocol JSON-RPC client for Electrs and Floresta"""

    @property
    def jsonrpc_version(self) -> str:
        return "2.0"

    @property
    def requires_auth(self):
        return False

    @property
    def url(self) -> str:
        return "tcp://%s:%d" % (self._host, self._port)

    def on_call(self, method, payload) -> dict[str, Any]:
        """Send ``payload`` as one line over TCP."""
        try:
            with socket.create_connection(
                (self._host, self._port), timeout=self.TIMEOUT
            ) as sock:
                sock.sendall(json.dumps(payload).encode() + b"\n")
                with sock.makefile("rb") as reader:
                    raw = reader.readline()
        except OSError as exc:
            raise ClientError("rpc %s unreachable: %s" % (method, exc)) from exc

        if not raw:
            raise ClientError("rpc %s: connection closed" % method)
        try:
            return json.loads(raw)
        except ValueError as exc:
            raise ClientError("rpc %s: invalid response" % method) from exc

    def is_up(self) -> bool:
        """Whether the electrum server answers a trivial call."""
        try:
            self.call("server.ping")
            return True
        except ClientError:
            return False

    def banner(self):
        """Custom elect f"""
        return self.call("server.banner")

    def get_tip(self):
        """Current chain tip"""
        return self.call("blockchain.headers.subscribe")

    def block_header(self, height):
        return self.call("blockchain.block.header", height)

    def estimate_fee(self, blocks=1):
        return self.call("blockchain.estimatefee", blocks)
