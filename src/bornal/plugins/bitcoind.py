import json
import os
import shutil
import subprocess
import tempfile

from ..cli import Cli
from ..daemon import Compiler, Daemon
from ..deps import check_installed
from ..git import Git
from ..logger import LOG, fail

__all__ = ["BitcoindCli", "BitcoindDaemon", "CoreCompiler"]

_NAME = "bitcoin-core"
_REPO = "https://github.com/bitcoin/bitcoin"
_CMAKE_SINCE_MAJOR = 29
_BUILD_META = "bitcoind.build.json"


def _check_compiler():
    if not (shutil.which("gcc") or shutil.which("clang")):
        fail("you must have either gcc or clang installed to build %s!", _NAME)


def _ref(revision):
    return "v%s" % revision if revision[:1].isdigit() else revision


def _uses_cmake(revision):
    major = revision.lstrip("v").split(".")[0]
    return not major.isdigit() or int(major) >= _CMAKE_SINCE_MAJOR


def _latest_revision():
    """Newest ``vMAJOR.MINOR[.PATCH]`` release tag in the bitcoin core repo"""
    versions = []
    for tag in Git.ls_remote_tags(_REPO, "v[0-9]*"):
        parts = tag.lstrip("v").split(".")
        if parts and all(p.isdigit() for p in parts):
            versions.append(tuple(int(p) for p in parts))
    if not versions:
        fail("could not determine the latest %s release", _NAME)
    return ".".join(str(p) for p in max(versions))


def _resolve_revision(revision):
    """Pin an explicit revision"""
    if revision in (None, "latest"):
        return _latest_revision()
    return revision


def _run(argv, cwd=None):
    LOG.debug("$ %s", " ".join(argv))
    if subprocess.run(argv, cwd=cwd).returncode != 0:
        fail("command failed: %s", " ".join(argv))


def _on_path():
    """Locate an already-installed ``bitcoind`` on ``$PATH`` (or ``None``)"""
    return shutil.which("bitcoind")


def _adopt(binaries_dir, bitcoind):
    """Copy an externally-provided ``bitcoind`` into the cache"""
    os.makedirs(binaries_dir, exist_ok=True)
    out = os.path.join(binaries_dir, "bitcoind")
    shutil.copy(bitcoind, out)
    os.chmod(out, 0o755)


def _read_build_meta(binaries_dir):
    """How the cached bitcoind was built, or ``None`` if unknown/missing."""
    try:
        with open(os.path.join(binaries_dir, _BUILD_META)) as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def _write_build_meta(binaries_dir, meta):
    """Record how the cached bitcoind was built"""
    with open(os.path.join(binaries_dir, _BUILD_META), "w") as handle:
        json.dump(meta, handle)


def _build_cmake(src, wallet, nprocs):
    check_installed("cmake")
    build = os.path.join(src, "build")

    LOG.info("minimal configuration (wallet=%s)", "on" if wallet else "off")
    _run(
        [
            "cmake",
            "-S",
            src,
            "-B",
            build,
            "-DCMAKE_BUILD_TYPE=MinSizeRel",
            "-DBUILD_DAEMON=ON",
            "-DBUILD_CLI=OFF",
            "-DBUILD_GUI=OFF",
            "-DBUILD_TESTS=OFF",
            "-DBUILD_BENCH=OFF",
            "-DENABLE_EXTERNAL_SIGNER=OFF",
            "-DENABLE_IPC=OFF",
            "-DINSTALL_MAN=OFF",
            "-DENABLE_WALLET=%s" % ("ON" if wallet else "OFF"),
        ]
    )

    LOG.info("building %s (-j%s)", _NAME, nprocs)
    _run(["cmake", "--build", build, "--target", "bitcoind", "-j", nprocs])
    return os.path.join(build, "bin")


def _build_autotools(src, wallet, nprocs):
    """Configure and build with Autotools (<= v28.x)."""
    check_installed("make", "autoconf", "automake", "libtool")

    LOG.info(
        "configuring %s with autotools (wallet=%s, minimal)",
        _NAME,
        "on" if wallet else "off",
    )
    _run(["./autogen.sh"], cwd=src)
    _run(
        [
            "./configure",
            "--without-gui",
            "--disable-tests",
            "--disable-bench",
            "--enable-wallet" if wallet else "--disable-wallet",
        ],
        cwd=src,
    )

    LOG.info("building %s (-j%s)", _NAME, nprocs)
    _run(["make", "-j", nprocs], cwd=src)
    return os.path.join(src, "src")


class CoreCompiler(Compiler):
    """Builds bitcoind from source, minimally, for wallet, basic p2p and mine
    procedures"""

    name = _NAME
    build_flag = "--build-bitcoin"

    def ensure(
        self,
        paths,
        *args,
        force=False,
        wallet=False,
        n_proc=None,
        revision=None,
        **kwargs,
    ) -> str:
        dest = os.path.join(paths.binaries_dir, "bitcoind")
        wanted = {"revision": revision or "latest", "wallet": bool(wallet)}
        wants_specific = wallet or revision is not None

        if not (force or wants_specific):
            found = _on_path()
            if found:
                LOG.info("using bitcoind from PATH (%s)", found)
                _adopt(paths.binaries_dir, found)
                _write_build_meta(
                    paths.binaries_dir, {"revision": "path", "wallet": None}
                )
                return dest

        if os.path.exists(dest) and not force:
            if not wants_specific or _read_build_meta(paths.binaries_dir) == wanted:
                LOG.info("%s already present (matching build), skipping", self.name)
                return dest
            LOG.info("%s present but built differently — rebuilding", self.name)

        _check_compiler()
        check_installed("git")
        revision = _resolve_revision(revision)
        if n_proc is not None:
            nprocs = str(n_proc)
        else:
            nprocs = os.environ.get("BUILD_BITCOIND_NPROCS", "4")

        with tempfile.TemporaryDirectory() as workdir:
            src = os.path.join(workdir, "bitcoin")

            LOG.info("cloning %s %s", self.name, _ref(revision))
            Git.clone(_REPO, src, branch=_ref(revision), depth=1)

            if _uses_cmake(revision):
                bindir = _build_cmake(src, wallet, nprocs)
            else:
                bindir = _build_autotools(src, wallet, nprocs)

            out = os.path.join(paths.binaries_dir, "bitcoind")
            shutil.copy(os.path.join(bindir, "bitcoind"), out)
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
            "BITCOIND": os.path.join(bindir, "bitcoind"),
            "BITCOIN_CORE_PATH": bindir,
        }


class BitcoindCli(Cli):
    """JSON-RPC client for bitcoind"""

    name = _NAME

    @property
    def jsonrpc_version(self) -> str:
        return "1.0"

    def get_blockchain_info(self) -> dict:
        return self.call("getblockchaininfo")

    def get_block_count(self) -> int:
        return self.call("getblockcount")

    def create_wallet(self, alias):
        return self.call("createwallet", alias)

    def get_new_address(self) -> str:
        return self.call("getnewaddress")

    def generate_to_address(self, nblocks, address) -> list:
        return self.call("generatetoaddress", nblocks, address)

    def get_balance(self):
        return self.call("getbalance")

    def list_unspent(self) -> list:
        return self.call("listunspent")


class BitcoindDaemon(Daemon):
    """Runs ``bitcoind`` with RPC enabled; the chain is set by ``network``
    (default: regtest)"""

    name = _NAME
    cli_class = BitcoindCli
    rpc_user = _NAME.lower()
    rpc_password = _NAME.lower()

    @property
    def binary_name(self) -> str:
        return "bitcoind"

    def args(self) -> list:
        argv = [
            "-chain=%s" % self.network,
            "-datadir=%s" % self.datadir,
            "-rpcport=%d" % self.port,
            "-rpcuser=%s" % self.rpc_user,
            "-rpcpassword=%s" % self.rpc_password,
            "-listen=0",
            "-fallbackfee=0.0002",
            "-server=1",
        ]
        if self.network != "regtest":
            argv.append("-connect=0")
        return argv


CoreCompiler.daemon_class = BitcoindDaemon
