import os

from bornal.paths import Paths


def test_explicit(git_repo, tmp_path, monkeypatch):
    monkeypatch.setenv("BORNAL_TEMP_DIR", str(tmp_path / "from-env"))
    explicit = str(tmp_path / "explicit")
    assert Paths(str(git_repo), temp_dir=explicit).temp_dir == explicit


def test_no_explicit(git_repo, tmp_path, monkeypatch):
    env_dir = str(tmp_path / "from-env")
    monkeypatch.setenv("BORNAL_TEMP_DIR", env_dir)
    assert Paths(str(git_repo)).temp_dir == env_dir


def test_default_xdg(git_repo, tmp_path, clear_cache_env, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    expected = os.path.join(str(tmp_path / "cache"), "bornal", "repo")
    assert Paths(str(git_repo)).temp_dir == expected


def test_default_home(git_repo, tmp_path, clear_cache_env, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    expected = os.path.join(str(tmp_path / "home"), ".cache", "bornal", "repo")
    assert Paths(str(git_repo)).temp_dir == expected


def test_layout(paths, git_repo):
    assert paths.proj_dir == os.path.realpath(str(git_repo))
    assert paths.proj_name == "repo"
    assert paths.binaries_dir == os.path.join(paths.temp_dir, "binaries")
    assert paths.data_dir == os.path.join(paths.temp_dir, "data")
    assert paths.logs_dir == os.path.join(paths.temp_dir, "logs")
    assert paths.integration_dir == os.path.join(paths.proj_dir, "tests", "integration")


def test_ensure_binaries(paths):
    assert not os.path.isdir(paths.binaries_dir)
    paths.ensure()
    assert os.path.isdir(paths.binaries_dir)


def test_clean(paths):
    os.makedirs(paths.data_dir)
    os.makedirs(paths.logs_dir)
    open(os.path.join(paths.data_dir, "stale"), "w").close()
    open(os.path.join(paths.logs_dir, "stale"), "w").close()

    paths.reset_state()

    assert os.listdir(paths.data_dir) == []
    assert os.listdir(paths.logs_dir) == []
