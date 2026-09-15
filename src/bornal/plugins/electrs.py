import json
import os
import socket
import tempfile

from ..client import Client, ClientError
from ..daemon import Compiler, CompilerError, Daemon, abort, free_port, run
from ..deps import check_installed
from ..git import Git
from ..logger import LOG

__all__ = ["ElectrsClient", "ElectrsCompiler", "ElectrsDaemon"]

_NAME = "electrs"
_REPO = "https://github.com/romanz/electrs"
_BUILD_META = "electrs.build.json"
_CONF_NAME = "electrs.toml"


def _build_env():
    env = os.environ.copy()
    env["CXXFLAGS"] = ("%s -include cstdint" % env.get("CXXFLAGS", "")).strip()
    return env


class ElectrsCompiler(Compiler):
    """Builds electrs with cargo. ``--nproc`` is ignored."""

    name = _NAME
    repo = _REPO
    binary_name = _NAME
    build_meta = _BUILD_META

    def ensure(self, paths, *args, force=False, revision=None, **kwargs) -> str:
        dest = self.dest(paths)
        wanted = {"revision": revision or "latest"}
        wants_specific = revision is not None

        if os.path.exists(dest) and not force:
            if not wants_specific or self.read_build_meta(paths) == wanted:
                LOG.info("%s matching build, skip it", self.name)
                return dest
            LOG.info("%s rebuilding", self.name)
        elif not (force or wants_specific):
            found = self.on_path()
            if found:
                LOG.info("electrs on PATH: %s", found)
                self.install(paths, found)
                self.write_build_meta(paths, {"revision": "path"})
                return dest

        check_installed("git", "cargo", "clang")
        revision = self.resolve_revision(revision)

        try:
            with tempfile.TemporaryDirectory() as workdir:
                src = os.path.join(workdir, "electrs")

                LOG.info(f"cloning {self.name} {self.git_ref(revision)}")
                Git.clone(_REPO, src, branch=self.git_ref(revision), depth=1)

                LOG.info(f"building {self.name}")
                run(
                    ["cargo", "build", "--locked", "--release"],
                    cwd=src,
                    env=_build_env(),
                )

                self.install(paths, os.path.join(src, "target", "release", "electrs"))
        except CompilerError as exc:
            abort(exc)
        self.write_build_meta(paths, wanted)
        LOG.info(f"{self.name} built at {paths.binaries_dir}")
        LOG.info(
            f"reuse it elsewhere with:\n\texport PATH={paths.binaries_dir}:$PATH\n\n"
        )
        return dest


class ElectrsClient(Client):
    """Electrum-protocol JSON-RPC client, newline-delimited over TCP.

    electrs ships no cli binary and no HTTP endpoint: it serves the Electrum
    wire protocol on a raw TCP socket, one JSON-RPC message per line.
    """

    name = _NAME

    @property
    def jsonrpc_version(self) -> str:
        return "2.0"

    @property
    def url(self) -> str:
        return "tcp://%s:%d" % (self._host, self._port)

    def call(self, method, *params):
        """Perform an Electrum JSON-RPC call over a fresh TCP connection."""
        payload = {
            "jsonrpc": self.jsonrpc_version,
            "id": "bornal",
            "method": method,
            "params": list(params),
        }
        self._log.debug("$ rpc %s %s", method, list(params))
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
            body = json.loads(raw)
        except ValueError as exc:
            raise ClientError("rpc %s: invalid response" % method) from exc

        if body.get("error"):
            raise ClientError("rpc %s error: %s" % (method, body["error"]))
        return body.get("result")

    def is_up(self) -> bool:
        """Whether the electrum server answers a trivial call."""
        try:
            self.call("server.ping")
            return True
        except ClientError:
            return False

    def server_version(self, client="bornal", protocol="1.4") -> list:
        return self.call("server.version", client, protocol)

    def banner(self) -> str:
        return self.call("server.banner")

    def get_tip(self) -> dict:
        """Current chain tip as ``{"height": int, "hex": str}``"""
        return self.call("blockchain.headers.subscribe")

    def block_header(self, height) -> str:
        return self.call("blockchain.block.header", height)

    def estimate_fee(self, blocks=1):
        return self.call("blockchain.estimatefee", blocks)


class ElectrsDaemon(Daemon):
    """Runs ``electrs`` on top of a running bitcoind, serving the Electrum
    protocol; configured through a generated ``electrs.toml``"""

    name = _NAME
    client_class = ElectrsClient

    def __init__(self, *args, bitcoind=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._bitcoind = bitcoind
        # electrs' Prometheus metrics cannot be disabled: reserve a port so
        # parallel runs never collide on the default monitoring address.
        self._monitoring_port = free_port()

    @property
    def binary_name(self) -> str:
        return "electrs"

    @property
    def monitoring_port(self) -> int:
        return self._monitoring_port

    @property
    def conf_file(self) -> str:
        return os.path.join(self.datadir, _CONF_NAME)

    def attach_bitcoind(self, bitcoind):
        """Point this electrs at a started ``BitcoindDaemon``"""
        self._bitcoind = bitcoind
        return self

    def _conf(self) -> str:
        backend = self._bitcoind
        if backend is None:
            raise RuntimeError(
                "electrs needs a bitcoind: pass bitcoind= or attach_bitcoind()"
            )
        if backend.p2p_port is None:
            raise RuntimeError(
                "electrs syncs blocks over p2p: start bitcoind with p2p_port="
            )
        lines = [
            'daemon_dir = "%s"' % backend.datadir,
            'auth = "%s:%s"' % (backend.rpc_user, backend.rpc_password),
            'daemon_rpc_addr = "%s:%d"' % (backend.host, backend.port),
            'daemon_p2p_addr = "%s:%d"' % (backend.host, backend.p2p_port),
            'db_dir = "%s"' % os.path.join(self.datadir, "db"),
            'network = "%s"' % self.network,
            'electrum_rpc_addr = "%s:%d"' % (self.host, self.port),
            'monitoring_addr = "%s:%d"' % (self.host, self._monitoring_port),
            'log_filters = "INFO"',
        ]
        return "\n".join(lines) + "\n"

    def args(self) -> list:
        return ["--conf", self.conf_file]

    def start(self):
        os.makedirs(self.datadir, exist_ok=True)
        with open(self.conf_file, "w") as handle:
            handle.write(self._conf())
        return super().start()


ElectrsCompiler.daemon_class = ElectrsDaemon
