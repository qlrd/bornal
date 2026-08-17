import json
import os
import shutil
import socket
import subprocess
import tempfile

from ..client import Client, ClientError
from ..daemon import Compiler, Daemon, free_port
from ..deps import check_installed
from ..git import Git
from ..logger import LOG, fail

__all__ = ["ElectrsClient", "ElectrsCompiler", "ElectrsDaemon"]

_NAME = "electrs"
_REPO = "https://github.com/romanz/electrs"
_BUILD_META = "electrs.build.json"
_CONF_NAME = "electrs.toml"


def _ref(rev):
    return "v%s" % rev if rev[:1].isdigit() else rev


def _latest_revision():
    versions = []
    for tag in Git.ls_remote_tags(_REPO, "v[0-9]*"):
        parts = tag.lstrip("v").split(".")
        if parts and all(p.isdigit() for p in parts):
            versions.append(tuple(int(p) for p in parts))
    if not versions:
        fail("unable to determine 'latest' for %s", _NAME)
    return ".".join(str(p) for p in max(versions))


def _resolve_revision(rev):
    if rev in (None, "latest"):
        return _latest_revision()
    return rev


def _run(argv, cwd=None):
    LOG.debug("$ %s", " ".join(argv))
    if subprocess.run(argv, cwd=cwd).returncode != 0:
        fail("command failed: %s", " ".join(argv))


def _on_path():
    return shutil.which("electrs")


def _adopt(binaries_dir, electrs):
    os.makedirs(binaries_dir, exist_ok=True)
    out = os.path.join(binaries_dir, "electrs")
    shutil.copy(electrs, out)
    os.chmod(out, 0o755)


def _read_build_meta(binaries_dir):
    """How the cached electrs was built, or ``None`` if unknown or missing."""
    try:
        with open(os.path.join(binaries_dir, _BUILD_META)) as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def _write_build_meta(binaries_dir, meta):
    """Remember how the cached electrs was built"""
    with open(os.path.join(binaries_dir, _BUILD_META), "w") as handle:
        json.dump(meta, handle)


class ElectrsCompiler(Compiler):
    """Builds electrs with cargo. ``--nproc`` is ignored."""

    name = _NAME

    def ensure(self, paths, *args, force=False, revision=None, **kwargs) -> str:
        dest = os.path.join(paths.binaries_dir, "electrs")
        wanted = {"revision": revision or "latest"}
        wants_specific = revision is not None

        if os.path.exists(dest) and not force:
            if not wants_specific or _read_build_meta(paths.binaries_dir) == wanted:
                LOG.info("%s matching build, skip it", self.name)
                return dest
            LOG.info("%s rebuilding", self.name)
        elif not (force or wants_specific):
            found = _on_path()
            if found:
                LOG.info("electrs on PATH: %s", found)
                _adopt(paths.binaries_dir, found)
                _write_build_meta(paths.binaries_dir, {"revision": "path"})
                return dest

        check_installed("git", "cargo", "clang")
        revision = _resolve_revision(revision)

        with tempfile.TemporaryDirectory() as workdir:
            src = os.path.join(workdir, "electrs")

            LOG.info("cloning %s %s", self.name, _ref(revision))
            Git.clone(_REPO, src, branch=_ref(revision), depth=1)

            LOG.info("building %s", _NAME)
            _run(["cargo", "build", "--locked", "--release"], cwd=src)

            out = os.path.join(paths.binaries_dir, "electrs")
            shutil.copy(os.path.join(src, "target", "release", "electrs"), out)
            os.chmod(out, 0o755)

        _write_build_meta(paths.binaries_dir, wanted)
        LOG.info("%s built at %s", self.name, paths.binaries_dir)
        LOG.info(
            "reuse it elsewhere via:\n    export PATH=%s:$PATH", paths.binaries_dir
        )
        return dest

    def env(self, paths):
        bindir = paths.binaries_dir
        return {
            "ELECTRS": os.path.join(bindir, "electrs"),
            "ELECTRS_PATH": bindir,
        }


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
