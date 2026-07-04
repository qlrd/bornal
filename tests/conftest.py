import os

import pytest

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
