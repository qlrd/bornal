import os
from subprocess import TimeoutExpired
from unittest.mock import MagicMock

import pytest

from bornal.cli import Cli
from bornal.daemon import Daemon
from bornal.git import Git
from bornal.paths import Paths

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
