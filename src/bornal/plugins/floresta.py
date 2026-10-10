import glob
import os
import re
import shutil
import subprocess
import tempfile

from ..client import Client, ElectrumClient
from ..daemon import Compiler, CompilerError, Daemon, abort, free_port, run
from ..deps import check_installed
from ..git import Git
from ..logger import LOG

__all__ = [
    "FlorestaClient",
    "FlorestaCompiler",
    "FlorestaDaemon",
    "FlorestaElectrumClient",
]

_NAME = "floresta"
_BINARY = "florestad"
_REPO = "https://github.com/getfloresta/Floresta"
_BUILD_META = "florestad.build.json"

MIN_REVISION = (0, 9, 0)
"""Oldest functional Floresta release bornal builds"""

BOOST_BREAKS_AT = {
    # libbitcoinkernel-sys 0.2.0 bundles an unreleased Bitcoin Core 30.99
    # snapshot whose txmempool.h multi_index container fails with Boost 1.92
    # (builds with 1.85)
    (0, 9): (1, 92),
}
"""First Boost release that breaks a Floresta (major, minor) line"""

# Bitcoin Core's AddBoostIfNeeded.cmake sets Boost_ROOT from
# `brew --prefix boost` on macOS, overriding CMAKE_PREFIX_PATH: neutralize the
# lookup and point cmake at the chosen Boost instead
_TOOLCHAIN = """\
set(HOMEBREW_EXECUTABLE "{true}" CACHE FILEPATH "bornal: no brew boost lookup" FORCE)
list(PREPEND CMAKE_PREFIX_PATH "{root}")
"""


SYSTEM_PREFIXES = ["/usr/local", "/usr"]
"""Where cmake finds Boost without hints, in its search order"""


def parse_revision(rev):
    """``"v0.9.1"`` -> ``(0, 9, 1)``; ``None`` for branches and commits"""
    parts = rev.lstrip("v").split(".")
    if parts and all(p.isdigit() for p in parts):
        return tuple(int(p) for p in parts)
    return None


def boost_version(root):
    """``(major, minor)`` of the Boost headers under ``root``, or ``None``"""
    try:
        with open(os.path.join(root, "include", "boost", "version.hpp")) as f:
            found = re.search(r"#define\s+BOOST_VERSION\s+(\d+)", f.read())
    except OSError:
        return None
    if found is None:
        return None
    number = int(found.group(1))
    return (number // 100000, number // 100 % 1000)


def _brew_prefix():
    brew = shutil.which("brew")
    if brew is None:
        return None
    out = subprocess.run([brew, "--prefix"], capture_output=True, text=True)
    return out.stdout.strip() or None


def boost_roots():
    """Prefixes holding Boost headers, the one cmake picks by default first:
    ``$BOOST_ROOT``, brew's ``boost`` then ``boost@*`` (newest first),
    ``/usr/local``, ``/usr``"""
    roots = []
    if os.environ.get("BOOST_ROOT"):
        roots.append(os.environ["BOOST_ROOT"])
    prefix = _brew_prefix()
    if prefix:
        roots.append(os.path.join(prefix, "opt", "boost"))
        kegs = glob.glob(os.path.join(prefix, "opt", "boost@*"))
        roots += sorted(kegs, key=lambda r: boost_version(r) or (0, 0), reverse=True)
    roots += SYSTEM_PREFIXES
    # brew keeps stale ``boost@<old>`` links to the current keg
    unique, seen = [], set()
    for root in roots:
        real = os.path.realpath(root)
        if real not in seen and boost_version(root):
            seen.add(real)
            unique.append(root)
    return unique


def _fmt(version):
    return ".".join(str(v) for v in version)


class FlorestaCompiler(Compiler):
    """Builds florestad with cargo. ``--nproc`` is ignored."""

    name = _NAME
    repo = _REPO
    binary_name = _BINARY
    build_meta = _BUILD_META

    def check_revision(self, revision):
        """Refuse releases older than ``MIN_REVISION``"""
        version = parse_revision(revision)
        if version is None:
            LOG.warning("%s %s is not a release: unchecked", self.name, revision)
        elif version < MIN_REVISION:
            raise CompilerError(
                "%s >= %s is required" % (self.name, _fmt(MIN_REVISION)),
                [Exception("requested %s" % revision)],
            )

    def select_boost(self, revision):
        """Boost prefix to build ``revision`` with; ``None`` when cmake's
        default pick is fine"""
        roots = boost_roots()
        if not roots:
            raise CompilerError(
                "%s needs Boost headers" % self.name,
                [Exception("no boost/version.hpp under $BOOST_ROOT, brew or /usr")],
            )
        version = parse_revision(revision)
        breaks_at = BOOST_BREAKS_AT.get(version[:2]) if version else None
        explicit = bool(os.environ.get("BOOST_ROOT"))
        usable = [r for r in roots if breaks_at is None or boost_version(r) < breaks_at]
        if not usable:
            causes = [
                Exception("Boost %s at %s" % (_fmt(boost_version(r)), r)) for r in roots
            ]
            causes.append(
                Exception("install an older one (e.g. `brew install boost@1.85`)")
            )
            raise CompilerError(
                "%s %s does not build with Boost >= %s"
                % (self.name, revision, _fmt(breaks_at)),
                causes,
            )
        if usable[0] == roots[0] and not explicit:
            return None
        if explicit and usable[0] != roots[0]:
            raise CompilerError(
                "$BOOST_ROOT does not build %s %s" % (self.name, revision),
                [
                    Exception(
                        "Boost %s >= %s"
                        % (_fmt(boost_version(roots[0])), _fmt(breaks_at))
                    )
                ],
            )
        return usable[0]

    def build_env(self, revision, workdir):
        """Env for cargo: steer the bundled Bitcoin Core to a compatible Boost"""
        root = self.select_boost(revision)
        if root is None:
            return None
        LOG.info(
            "building %s against Boost %s (%s)",
            self.name,
            _fmt(boost_version(root)),
            root,
        )
        toolchain = os.path.join(workdir, "bornal-boost.cmake")
        with open(toolchain, "w") as handle:
            handle.write(
                _TOOLCHAIN.format(
                    true=shutil.which("true") or "/usr/bin/true", root=root
                )
            )
        return {**os.environ, "CMAKE_TOOLCHAIN_FILE": toolchain}

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
                LOG.info("florestad on PATH: %s", found)
                self.install(paths, found)
                self.write_build_meta(paths, {"revision": "path"})
                return dest
        check_installed("git", "cargo", "cmake")
        revision = self.resolve_revision(revision)

        try:
            self.check_revision(revision)
            self.check_compiler("g++", "clang++")
            with tempfile.TemporaryDirectory() as workdir:
                src = os.path.join(workdir, "floresta")
                env = self.build_env(revision, workdir)

                LOG.info(f"cloning {self.name} {self.git_ref(revision)}")
                Git.clone(_REPO, src, branch=self.git_ref(revision), depth=1)

                LOG.info(f"building {self.name}")
                run(
                    ["cargo", "build", "--locked", "--release", "--bin", _BINARY],
                    cwd=src,
                    env=env,
                )

                self.install(paths, os.path.join(src, "target", "release", _BINARY))
        except CompilerError as exc:
            abort(exc)
        self.write_build_meta(paths, wanted)
        LOG.info(f"{self.name} built at {paths.binaries_dir}")
        LOG.info(
            f"reuse it elsewhere with:\n\texport PATH={paths.binaries_dir}:$PATH\n\n"
        )
        return dest


class FlorestaClient(Client):
    """florestad JSON-RPC client; the server takes no credentials"""

    @property
    def name(self):
        return _NAME

    @property
    def requires_auth(self):
        return False

    @property
    def jsonrpc_version(self) -> str:
        return "2.0"

    def get_blockchain_info(self):
        return self.call("getblockchaininfo")

    def get_block_count(self):
        return self.call("getblockcount")

    def get_best_block_hash(self):
        return self.call("getbestblockhash")

    def get_block_hash(self, height: int):
        return self.call("getblockhash", height)

    def get_block_header(self, block_hash: str):
        return self.call("getblockheader", block_hash)

    def get_block(self, block_hash: str, verbosity: int = 1):
        return self.call("getblock", block_hash, verbosity)

    def get_roots(self):
        return self.call("getroots")

    def get_peer_info(self):
        return self.call("getpeerinfo")

    def add_node(self, node: str, command: str = "onetry", v2transport: bool = False):
        return self.call("addnode", node, command, v2transport)

    def disconnect_node(self, node: str):
        return self.call("disconnectnode", node)

    def uptime(self):
        return self.call("uptime")

    def ping(self):
        return self.call("ping")

    def stop(self):
        return self.call("stop")


class FlorestaElectrumClient(ElectrumClient):
    """Client for florestad's built-in Electrum server.

    florestad only indexes the scripts of its own wallet (see ``--wallet-xpub``,
    ``--wallet-descriptor`` or the ``loaddescriptor`` rpc), so scripthash and
    ``transaction.get`` calls only see those."""

    @property
    def name(self):
        return _NAME

    def server_version(self, protocol="1.4"):
        return self.call("server.version", "Floresta", protocol)

    def features(self):
        return self.call("server.features")

    def relay_fee(self):
        return self.call("blockchain.relayfee")

    def block_headers(self, start_height: int, count: int):
        """``{"count", "hex", "max"}``"""
        return self.call("blockchain.block.headers", start_height, count)

    def get_balance(self, scripthash: str):
        return self.call("blockchain.scripthash.get_balance", scripthash)

    def get_history(self, scripthash: str):
        return self.call("blockchain.scripthash.get_history", scripthash)

    def list_unspent(self, scripthash: str):
        return self.call("blockchain.scripthash.listunspent", scripthash)

    def get_transaction(self, txid: str):
        return self.call("blockchain.transaction.get", txid)

    def broadcast(self, hextx: str):
        return self.call("blockchain.transaction.broadcast", hextx)


class FlorestaDaemon(Daemon):
    """Runs ``florestad``; it never listens for p2p, so it reaches a peer
    through ``connect`` (``host:port``) or the ``addnode`` rpc"""

    name = _NAME
    client_class = FlorestaClient

    def __init__(self, *args, electrum_port=None, connect=None, **kwargs):
        super().__init__(*args, **kwargs)
        # florestad always serves electrum (regtest default: 20001): reserve
        # a port so several nodes never collide on it
        self._electrum_port = electrum_port or free_port()
        self._connect = connect

    @property
    def binary_name(self) -> str:
        return _BINARY

    @property
    def electrum_port(self) -> int:
        return self._electrum_port

    def make_electrum_client(self):
        """A ``FlorestaElectrumClient`` wired to this daemon's Electrum server"""
        return FlorestaElectrumClient(
            host=self.host, port=self._electrum_port, log=self._log
        )

    @property
    def connect(self):
        """The only peer florestad dials at start, or ``None``"""
        return self._connect

    def args(self) -> list:
        argv = [
            "--network=%s" % self.network,
            "--data-dir=%s" % self.datadir,
            "--rpc-address=%s:%d" % (self.host, self.port),
            "--electrum-address=%s:%d" % (self.host, self._electrum_port),
            "--disable-dns-seeds",
            # keep <datadir>/<network>/debug.log around for failed runs
            "--log-to-file",
        ]
        if self._connect is not None:
            argv.append("--connect=%s" % self._connect)
        return argv


setattr(FlorestaCompiler, "daemon_class", FlorestaDaemon)
