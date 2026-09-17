import os
import tempfile

from ..client import Client
from ..daemon import Compiler, CompilerError, Daemon, run, abort
from ..deps import check_installed
from ..git import Git
from ..logger import LOG

__all__ = ["BitcoindClient", "BitcoindDaemon", "CoreCompiler"]

_NAME = "bitcoin-core"
_REPO = "https://github.com/bitcoin/bitcoin"
_CMAKE_SINCE_MAJOR = 29
_BUILD_META = "bitcoind.build.json"

UNSPENDABLE_ADDRESS = "bcrt1qqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqq3xueyj"


def uses_cmake(rev):
    """Helper for Autotools to CMake when using bitcoin at v29"""
    maj = rev.lstrip("v").split(".")[0]
    return not maj.isdigit() or int(maj) >= _CMAKE_SINCE_MAJOR


def build_cmake(src, wallet, nprocs, paths):
    check_installed("cmake")
    build = os.path.join(src, "build")

    LOG.info("minimal configuration (wallet=%s)", "on" if wallet else "off")
    run(
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
        ],
        src,
    )

    LOG.info("building %s (-j%s)", _NAME, nprocs)
    run(["cmake", "--build", build, "--target", "bitcoind", "-j", nprocs])
    return os.path.join(build, "bin")


def build_autotools(src, wallet, nprocs, paths):
    """Configure and build with Autotools (<= v28.x)."""
    check_installed("make", "autoconf", "automake", "libtool")
    LOG.info(
        "configuring %s with autotools (wallet=%s, minimal)",
        _NAME,
        "on" if wallet else "off",
    )

    run(["./autogen.sh"], cwd=src)
    run(
        [
            "./configure",
            "--without-gui",
            "--disable-tests",
            "--disable-bench",
            "--enable-wallet" if wallet else "--disable-wallet",
        ],
        cwd=src,
    )

    LOG.info("building %s (-j%s)", src, nprocs)
    run(["make", "-j", nprocs], cwd=src)
    return os.path.join(src, "src")


class CoreCompiler(Compiler):
    """Builds bitcoind from source, minimally, for wallet, basic p2p and mine
    procedures"""

    name = _NAME
    build_flag = "--build-bitcoin"
    binary_name = "bitcoind"
    repo = _REPO
    build_meta = _BUILD_META

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

        # find first in already compiled binaries at cache
        if os.path.exists(dest) and not force:
            if not wants_specific or self.read_build_meta(paths) == wanted:
                LOG.info("%s already present (matching build), skipping", self.name)
                return dest
            LOG.info("%s present but built differently — rebuilding", self.name)
        elif not (force or wants_specific):
            found = self.on_path()
            if found:
                LOG.info("using bitcoind from PATH (%s)", found)
                self.install(paths, found)
                self.write_build_meta(paths, {"revision": "path", "wallet": None})
                return dest

        check_installed("git")
        revision = self.resolve_revision(revision)
        if n_proc is not None:
            nprocs = str(n_proc)
        else:
            nprocs = os.environ.get("BUILD_BITCOIND_NPROCS", "4")

        try:
            self.check_compiler("gcc", "clang")
            with tempfile.TemporaryDirectory() as workdir:
                src = os.path.join(workdir, "bitcoin")
                LOG.info(f"cloning {self.name} {revision}")
                Git.clone(_REPO, src, branch=self.git_ref(revision), depth=1)

                if uses_cmake(revision):
                    bindir = build_cmake(src, wallet, nprocs, paths)
                else:
                    bindir = build_autotools(src, wallet, nprocs, paths)

                self.install(paths, os.path.join(bindir, "bitcoind"))
        except CompilerError as exc:
            abort(exc)

        self.write_build_meta(paths, wanted)
        LOG.info(f"{self.name} built at {paths.binaries_dir}")
        LOG.info(
            f"reuse it elsewhere with:\n\texport PATH={paths.binaries_dir}:$PATH\n\n"
        )
        return dest


class BitcoindClient(Client):
    """JSON-RPC client for bitcoind"""

    name = _NAME

    @property
    def jsonrpc_version(self) -> str:
        return "1.0"

    def get_blockchain_info(self) -> dict:
        return self.call("getblockchaininfo")

    def get_block_count(self) -> int:
        return self.call("getblockcount")

    def create_wallet(
        self, alias, disable_private_keys: bool = False, blank: bool = False
    ):
        return self.call("createwallet", alias, disable_private_keys, blank)

    def get_new_address(self) -> str:
        return self.call("getnewaddress")

    def generate_to_address(self, nblocks, address) -> list:
        return self.call("generatetoaddress", nblocks, address)

    def get_balance(self):
        return self.call("getbalance")

    def list_unspent(self) -> list:
        return self.call("listunspent")

    def list_wallets(self) -> list:
        return self.call("listwallets")

    def get_wallet_info(self) -> dict:
        return self.call("getwalletinfo")

    def import_descriptors(self, req: list[dict]) -> list:
        return self.call("importdescriptors", req)

    def add_node(self, node: str, command: str = "onetry") -> None:
        return self.call("addnode", node, command)

    def finalize_psbt(self, psbt: str, extract: bool = True) -> dict:
        return self.call("finalizepsbt", psbt, extract)

    def analyze_psbt(self, psbt: str) -> dict:
        return self.call("analyzepsbt", psbt)

    def test_mempool_accept(
        self, rawtxs: list, maxfeerate: int | float = 0.1
    ) -> list[dict]:
        return self.call("testmempoolaccept", rawtxs, maxfeerate)

    def send_raw_transaction(self, hexstr: str, maxfeerate: int | float = 0.1) -> str:
        return self.call("sendrawtransaction", hexstr, maxfeerate)

    def get_address_info(self, address: str) -> dict:
        return self.call("getaddressinfo", address)

    def get_balances(self) -> dict:
        return self.call("getbalances")

    def get_connection_count(self) -> int:
        return self.call("getconnectioncount")


class BitcoindDaemon(Daemon):
    """Runs ``bitcoind`` with RPC enabled; the chain is set by ``network``
    (default: regtest)"""

    name = _NAME
    client_class = BitcoindClient
    rpc_user = _NAME.lower()
    rpc_password = _NAME.lower()

    def __init__(self, *args, p2p_port=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._p2p_port = p2p_port

    @property
    def binary_name(self) -> str:
        return "bitcoind"

    @property
    def p2p_port(self):
        """p2p listen port, or ``None`` when p2p is disabled"""
        return self._p2p_port

    def args(self) -> list:
        argv = [
            "-chain=%s" % self.network,
            "-datadir=%s" % self.datadir,
            "-rpcport=%d" % self.port,
            "-rpcuser=%s" % self.rpc_user,
            "-rpcpassword=%s" % self.rpc_password,
            "-fallbackfee=0.0002",
            "-server=1",
        ]
        if self._p2p_port is None:
            argv.append("-listen=0")
        else:
            argv += ["-listen=1", "-bind=%s:%d" % (self.host, self._p2p_port)]
        if self.network != "regtest":
            argv.append("-connect=0")
        return argv


CoreCompiler.daemon_class = BitcoindDaemon
