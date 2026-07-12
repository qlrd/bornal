import base64
import io
import json
import os
import urllib.error
from subprocess import TimeoutExpired
from unittest.mock import MagicMock

import pytest

from bornal.cli import Cli
from bornal.daemon import Daemon
from bornal.git import Git
from bornal.paths import Paths
from bornal.plugins.bitcoind import BitcoindDaemon

_GIT_ENV = {
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_SYSTEM": os.devnull,
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@t",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@t",
}


class MockCli(Cli):
    @property
    def jsonrpc_version(self):
        return "1.0"


class MockDaemon(Daemon):
    cli_class = MockCli
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
        "getblockcount": 0,
        "stop": "Bitcoin Core stopping",
        "getblockchaininfo": {
            "chain": "mocktest",
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
        else:
            body = {"result": None, "error": "not implemented"}
        self.bodies.append(body)
        data = json.dumps(body).encode()
        if body["error"]:
            raise urllib.error.HTTPError(
                req.full_url, 500, "Internal Server Error", {}, io.BytesIO(data)
            )
        return io.BytesIO(data)


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
    """Initialize some mocked daemon and cli for the unit tests."""
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
def mocked_rpc(monkeypatch):
    """Spy ``urllib.request.urlopen``, enforcing ``MockDaemon`` credentials."""
    spy = MockedSpyRpc(basic_auth=_BASIC_AUTH, responses={"getblockcount": 21})
    monkeypatch.setattr("urllib.request.urlopen", spy)
    return spy


@pytest.fixture
def mocked_cli(mocked_daemon, spy_popen, mocked_rpc):
    """A started ``MockDaemon``'s CLI, with process and transport mocked."""
    cli = mocked_daemon.make_cli()
    mocked_daemon.start()
    try:
        yield cli
    finally:
        mocked_daemon.stop()


@pytest.fixture
def mocked_cli_noauth(mocked_daemon, spy_popen, mocked_rpc):
    """A started credential-less daemon's CLI, over the mocked transport."""
    mocked_daemon.rpc_user = None
    mocked_daemon.rpc_password = None
    cli = mocked_daemon.make_cli()
    mocked_daemon.start()
    try:
        yield cli
    finally:
        mocked_daemon.stop()


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
