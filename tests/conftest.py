import base64
import io
import json
import os
import sys
import urllib.error
from subprocess import TimeoutExpired
from unittest.mock import MagicMock

import pytest

import runpy

from bornal.client import Client
from bornal.daemon import Daemon
from bornal.git import Git
from bornal.paths import Paths
from bornal.plugins import bitcoind, electrs
from bornal.plugins.bitcoind import BitcoindDaemon
from bornal.node import make_backend
from bornal.testing import COINBASE_MATURITY, BASE_COINBASE_SUBSIDY
from bornal import fixtures
from bornal import main

_GIT_ENV = {
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_SYSTEM": os.devnull,
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@t",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@t",
}


class MockClient(Client):
    @property
    def jsonrpc_version(self):
        return "1.0"


class MockDaemon(Daemon):
    client_class = MockClient
    rpc_user = "mocku"
    rpc_password = "liar"

    @property
    def binary_name(self):
        return "mocku"

    def args(self):
        return ["--flag"]


def basic_auth_header(user, password):
    """The ``Authorization`` header value for HTTP basic auth"""
    return "Basic %s" % base64.b64encode(("%s:%s" % (user, password)).encode()).decode()


_BASIC_AUTH = basic_auth_header(MockDaemon.rpc_user, MockDaemon.rpc_password)


class MockedSpyPopen:
    """Spy ``subprocess.Popen`` for ``Daemon`` lifecycle"""

    def __init__(self):
        self.stuck = False
        self.processes = []

    def __call__(self, argv, *args, **kwargs):
        mock_proc = MagicMock()
        mock_proc.argv = list(argv)
        mock_proc.killed = False
        mock_proc.terminated = False
        mock_proc.returncode = None

        def mock_poll():
            return mock_proc.returncode

        def mock_terminate():
            mock_proc.terminated = True
            if not self.stuck:
                mock_proc.returncode = 0

        def mock_kill():
            mock_proc.killed = True
            mock_proc.returncode = -9

        def mock_wait(timeout=0):
            if self.stuck and not mock_proc.killed:
                raise TimeoutExpired(cmd=argv[0], timeout=timeout)
            return mock_proc.returncode

        mock_proc.poll.side_effect = mock_poll
        mock_proc.terminate.side_effect = mock_terminate
        mock_proc.kill.side_effect = mock_kill
        mock_proc.wait.side_effect = mock_wait

        self.processes.append(mock_proc)
        return mock_proc


class MockedSpyRpc:
    """Spy JSON-RPC mocked transport for bitcoind responses."""

    _RESPONSES = {
        "uptime": 1,
        "stop": "Bitcoin Core stopping",
        "getblockchaininfo": {
            "chain": "regtest",
            "blocks": 0,
            "headers": 0,
            "bestblockhash": "0f9188f13cb7b2c71f2a335e3a4fc328"
            "bf5beb436012afca590b1a11466e2206",
            "difficulty": 4.656542373906925e-10,
            "mediantime": 1296688602,
            "verificationprogress": 1,
            "initialblockdownload": True,
            "chainwork": "0" * 63 + "2",
            "size_on_disk": 293,
            "pruned": False,
            "softforks": {},
            "warnings": "",
        },
    }

    def __init__(self, basic_auth=None, responses=None):
        self.basic_auth = basic_auth
        self.stored = {**self._RESPONSES, **(responses or {})}
        self.calls = []
        self.requests = []
        self.bodies = []
        self.height = 0
        self._addresses = []
        self._mined_to = None

    def _new_address(self):
        address = "bcrt1qspy%d" % len(self._addresses)
        self._addresses.append(address)
        return address

    def _list_unspent(self):
        if self.height <= COINBASE_MATURITY:
            return []
        return [{"address": self._mined_to, "amount": BASE_COINBASE_SUBSIDY}]

    @property
    def req(self):
        return self.requests[-1] if self.requests else None

    @property
    def res(self):
        return self.bodies[-1] if self.bodies else None

    def __call__(self, req, timeout=None):
        self.requests.append(req)
        payload = json.loads(req.data)
        method = payload["method"]
        params = payload["params"]
        self.calls.append(method)
        if self.basic_auth and req.get_header("Authorization") != self.basic_auth:
            body = {"result": None, "error": "Not authorized"}
        elif method == "generatetoaddress":
            if 2 <= len(params) <= 3:
                self.height += params[0]
                self._mined_to = params[1]
                body = {
                    "result": ["%064x" % height for height in range(1, params[0] + 1)],
                    "error": None,
                }
            else:
                body = {
                    "result": None,
                    "error": "need 2 or 3 params, provided %d" % len(params),
                }
        elif method in self.stored:
            body = {"result": self.stored[method], "error": None}
        elif method == "getblockcount":
            body = {"result": self.height, "error": None}
        elif method == "createwallet":
            body = {"result": {"name": params[0]}, "error": None}
        elif method == "getnewaddress":
            body = {"result": self._new_address(), "error": None}
        elif method == "getbalance":
            matured = self.height > COINBASE_MATURITY
            body = {"result": BASE_COINBASE_SUBSIDY if matured else 0, "error": None}
        elif method == "listunspent":
            body = {"result": self._list_unspent(), "error": None}
        else:
            body = {"result": None, "error": "not implemented"}
        self.bodies.append(body)
        data = json.dumps(body).encode()
        if body["error"]:
            raise urllib.error.HTTPError(
                req.full_url, 500, "Internal Server Error", {}, io.BytesIO(data)
            )
        return io.BytesIO(data)


class MockedSpyBuild:
    """Spy the daemon builds' shell output (cmake/make/cargo/go)"""

    def __init__(self):
        self.calls = []

    def __iter__(self):
        return iter(self.calls)

    @staticmethod
    def _setup(bindir, binary="bitcoind"):
        os.makedirs(bindir, exist_ok=True)
        open(os.path.join(bindir, binary), "w").close()

    def run(self, argv, cwd=None):
        self.calls.append(argv)
        if argv[:2] == ["cmake", "--build"]:
            self._setup(os.path.join(argv[2], "bin"))
        elif argv[0] == "make":
            self._setup(os.path.join(cwd, "src"))
        elif argv[:2] == ["cargo", "build"]:
            self._setup(os.path.join(cwd, "target", "release"), "electrs")

    def clone(self, repo, dest, branch=None, depth=None):
        argv = ["git", "clone"]
        if depth:
            argv += ["--depth", str(depth)]
        if branch:
            argv += ["--branch", branch]
        argv += [repo, dest]
        self.calls.append(argv)
        os.makedirs(dest, exist_ok=True)
        return dest


class _MockElectrumSock:
    """One mocked TCP connection with buffers that spy's reply for reads"""

    def __init__(self, spy):
        self._spy = spy
        self._buffer = io.BytesIO()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def sendall(self, data):
        self._buffer = io.BytesIO(self._spy.respond(data))

    def makefile(self, mode):
        return self._buffer


class MockedSpyElectrumRpc:
    """Spy Electrum JSON-RPC over a mocked TCP transport."""

    # similar to blockchain, mock electrum standart default responses
    _RESPONSES = {
        "server.ping": None,
        "server.banner": "mocked electrs",
        "server.version": ["electrs/0.10.10", "1.4"],
        "blockchain.headers.subscribe": {"height": 0, "hex": "00" * 80},
        "blockchain.block.header": "00" * 80,
        "blockchain.estimatefee": 0.0001,
    }

    def __init__(self, responses=None):
        self.stored = {**self._RESPONSES, **(responses or {})}
        self.calls = []
        self.down = False
        self.raw_response = None

    def __call__(self, address, timeout=None):
        if self.down:
            raise ConnectionRefusedError("mocked down")
        return _MockElectrumSock(self)

    def respond(self, data):
        payload = json.loads(data)
        method = payload["method"]
        self.calls.append(method)
        if self.raw_response is not None:
            return self.raw_response
        if method in self.stored:
            body = {"id": payload["id"], "result": self.stored[method]}
        else:
            body = {
                "id": payload["id"],
                "error": {"code": -32601, "message": "unknown method"},
            }
        return json.dumps(body).encode() + b"\n"


class MockPytestConfig:
    """Minimal config for pytest"""

    def __init__(self, **opts):
        self._opts = opts

    def getoption(self, name, default=None):
        return self._opts.get(name, default)


@pytest.fixture
def git_repo(tmp_path, monkeypatch):
    """A git repo with an 'init' commit, seeded through the ``Git`` wrapper."""
    for key, value in _GIT_ENV.items():
        monkeypatch.setenv(key, value)
    repo = tmp_path / "repo"
    git = Git.init(str(repo))
    file = repo / "test.txt"
    file.write_text("hello\n")
    git.add(str(file))
    git.commit("init: initial commit")
    return repo


@pytest.fixture
def paths(git_repo, tmp_path, monkeypatch):
    """A ``Paths`` rooted at ``git_repo``, with the temp dir under ``tmp_path``."""
    monkeypatch.setenv("BORNAL_TEMP_DIR", str(tmp_path / "src"))
    return Paths(str(git_repo))


@pytest.fixture
def clear_cache_env(monkeypatch):
    """Drop the temp-dir env vars so the default cache path is exercised."""
    monkeypatch.delenv("BORNAL_TEMP_DIR", raising=False)
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)


@pytest.fixture
def mocked_daemon(tmp_path):
    """Initialize some mocked daemon and client for the unit tests."""
    return MockDaemon(
        binaries_dir="/bin", datadir=str(tmp_path), port=5555, extra_args=["-extra"]
    )


@pytest.fixture
def spy_popen(monkeypatch):
    """Spy subprocess so we can test many situations"""
    popen = MockedSpyPopen()
    monkeypatch.setattr("subprocess.Popen", popen)
    return popen


@pytest.fixture
def spy_build(monkeypatch):
    """Spy the daemon builds"""
    # the real ``ensure`` methods run (revision parsing, build dispatch,
    # binary copy), but the shell-out boundary is intercepted by
    # ``MockedSpyBuild`` and host/network lookups are stubbed.
    spy = MockedSpyBuild()
    monkeypatch.setattr(bitcoind, "_on_path", lambda: None)
    monkeypatch.setattr(bitcoind, "_check_compiler", lambda: None)
    monkeypatch.setattr(bitcoind, "check_installed", lambda *a: None)
    monkeypatch.setattr(bitcoind, "_run", spy.run)
    monkeypatch.setattr(bitcoind.Git, "clone", staticmethod(spy.clone))
    monkeypatch.setattr(bitcoind, "_latest_revision", lambda: "30.2")
    monkeypatch.setattr(electrs, "_on_path", lambda: None)
    monkeypatch.setattr(electrs, "check_installed", lambda *a: None)
    monkeypatch.setattr(electrs, "_run", spy.run)
    monkeypatch.setattr(electrs, "_latest_revision", lambda: "0.10.10")
    return spy


@pytest.fixture
def spy_electrum(monkeypatch):
    """Spy the Electrum TCP transport so electrs client tests can assert calls"""
    spy = MockedSpyElectrumRpc()
    monkeypatch.setattr("socket.create_connection", spy)
    return spy


@pytest.fixture
def mocked_rpc(monkeypatch):
    """Spy ``urllib.request.urlopen``, enforcing ``MockDaemon`` credentials."""
    spy = MockedSpyRpc(basic_auth=_BASIC_AUTH, responses={"getblockcount": 21})
    monkeypatch.setattr("urllib.request.urlopen", spy)
    return spy


@pytest.fixture
def mocked_client(mocked_daemon, spy_popen, mocked_rpc):
    """A started ``MockDaemon``'s client, with process and transport mocked."""
    client = mocked_daemon.make_client()
    mocked_daemon.start()
    try:
        yield client
    finally:
        mocked_daemon.stop()


@pytest.fixture
def mocked_client_noauth(mocked_daemon, spy_popen, mocked_rpc):
    """A started credential-less daemon's client, over the mocked transport."""
    mocked_daemon.rpc_user = None
    mocked_daemon.rpc_password = None
    client = mocked_daemon.make_client()
    mocked_daemon.start()
    try:
        yield client
    finally:
        mocked_daemon.stop()


@pytest.fixture
def mock_bitcoind_cache(paths):
    """Pre-populate ``binaries_dir`` with a fake compiled bitcoind"""

    def _wrap(revision=None, wallet=True):
        os.makedirs(paths.binaries_dir, exist_ok=True)
        dest = os.path.join(paths.binaries_dir, "bitcoind")
        with open(dest, "w") as handle:
            handle.write("cached")
        if revision is not None:
            bitcoind._write_build_meta(
                paths.binaries_dir, {"revision": revision, "wallet": wallet}
            )
        return dest

    return _wrap


@pytest.fixture
def mock_bitcoind_bin_path(monkeypatch, tmp_path):
    """Put a fake bitcoind 'on PATH' via the ``_on_path`` seam"""

    def _wrap(p):
        binary = tmp_path / p / "bitcoind"
        binary.parent.mkdir()
        binary.write_text("mockuo")
        monkeypatch.setattr(bitcoind, "_on_path", lambda: str(binary))
        return binary

    return _wrap


@pytest.fixture
def electrs_compiler():
    """The electrs compiler plugin"""
    return electrs.ElectrsCompiler()


@pytest.fixture
def backend_daemon(tmp_path):
    """A p2p-enabled bitcoind daemon for electrs to ride on but not started"""
    return BitcoindDaemon("/bin", str(tmp_path / "b"), port=18443, p2p_port=18444)


@pytest.fixture
def electrs_daemon(tmp_path, backend_daemon):
    """An electrs daemon wired to ``backend_daemon`` but not started"""
    return electrs.ElectrsDaemon(
        "/bin", str(tmp_path / "e"), port=50001, bitcoind=backend_daemon
    )


@pytest.fixture
def electrs_client(spy_electrum):
    """An ``ElectrsClient`` over the mocked Electrum TCP transport"""
    return electrs.ElectrsClient(host="127.0.0.1", port=50001)


@pytest.fixture
def mocked_explicit_bin(monkeypatch):
    monkeypatch.setenv("BINARIES_DIR", "/explicit/bin")
    monkeypatch.setenv("INTEGRATION_TEMP_DIR", "/tmp/run")


@pytest.fixture
def mocked_fallback_bin(monkeypatch):
    monkeypatch.delenv("BINARIES_DIR", raising=False)
    monkeypatch.setenv("INTEGRATION_TEMP_DIR", "/tmp/run")


@pytest.fixture
def mocked_env_bin(monkeypatch):
    monkeypatch.setenv("INTEGRATION_TEMP_DIR", "/tmp/run")


@pytest.fixture
def spy_rpc(monkeypatch):
    """Spy the RPC transport so node tests can assert the calls made"""
    spy = MockedSpyRpc(
        basic_auth=basic_auth_header(
            BitcoindDaemon.rpc_user, BitcoindDaemon.rpc_password
        )
    )
    monkeypatch.setattr("urllib.request.urlopen", spy)
    return spy


@pytest.fixture
def pytestconfig_minimal(monkeypatch, git_repo, tmp_path):
    def _wrap(**over):
        for var in (
            "BINARIES_DIR",
            "INTEGRATION_TEMP_DIR",
            "BITCOIND",
            "BITCOIN_CORE_PATH",
        ):
            monkeypatch.setenv(var, "")

        base = dict(
            verbose=0,
            bornal_proj_path=str(git_repo),
            bornal_tmp_path=str(tmp_path / "out"),
            bornal_wallet=False,
            bornal_force_build=False,
            bornal_preserve_data=False,
            bornal_nproc=None,
            bornal_build_bitcoin_core=None,
        )
        base.update(over)
        return MockPytestConfig(**base)

    return _wrap


@pytest.fixture
def prepare_run_minimal(monkeypatch, pytestconfig_minimal):
    def _wrap(version, wallet=False, force=False, nproc=None, preserve=False):
        calls = []
        monkeypatch.setattr(
            fixtures, "ensure_daemons", lambda paths, **kw: calls.append(kw)
        )
        config = pytestconfig_minimal(
            bornal_build_bitcoin_core=version,
            bornal_wallet=wallet,
            bornal_force_build=force,
            bornal_nproc=nproc,
            bornal_preserve_data=preserve,
        )
        tmp = config.getoption("bornal_tmp_path")
        paths = fixtures.prepare_run(config, {"bitcoin-core": version})
        return calls, tmp, paths

    return _wrap


@pytest.fixture
def run_backend(tmp_path):
    def _wrap(name):
        node = make_backend(name, "/bin", str(tmp_path))
        node.start()
        return node

    return _wrap


@pytest.fixture
def run_cli(monkeypatch):
    def _wrap(*argv):
        monkeypatch.setattr(sys, "argv", ["bornal", *argv])
        main()

    return _wrap


@pytest.fixture
def integrate(git_repo, tmp_path, run_cli):
    def _wrap(name, *args):
        tmp = str(tmp_path / "out")
        run_cli("--proj-path", str(git_repo), "--tmp-path", tmp, "create", *args)
        return os.path.join(
            os.path.realpath(str(git_repo)), "tests", "integration", name
        )

    return _wrap


@pytest.fixture
def run(git_repo, tmp_path, monkeypatch):
    """`python -m bornal --proj-path <path> --tmp-path <tmp> <cmd>`"""

    def _wrap(*args):
        tmp = str(tmp_path / "out")
        monkeypatch.setattr(
            sys,
            "argv",
            ["bornal", "--proj-path", str(git_repo), "--tmp-path", tmp, *args],
        )
        runpy.run_module("bornal", run_name="__main__")

    return _wrap
