import os

import pytest

from bornal.git import Git


def test_revparse_returns_toplevel(git_repo):
    g = Git(str(git_repo))
    assert g.revparse(show_toplevel=True) == os.path.realpath(str(git_repo))


def test_log_returns_commit_dicts(git_repo):
    g = Git(str(git_repo))
    commits = g.log(oneline=True)
    assert len(commits) == 1
    assert len(commits[0]["commit"]) == 7


def test_tip_is_the_latest_commit(git_repo):
    g = Git(str(git_repo))
    assert g.tip()["message"] == "init: initial commit"


def test_log_with_line_range_attaches_diff(git_repo):
    g = Git(str(git_repo))
    commits = g.log(L="1,1:test.txt")
    assert len(commits) == 1
    assert "diff" in commits[0]
    assert any(line.startswith("@@") for line in commits[0]["diff"])


def test_failed_git_command_exits(tmp_path):
    with pytest.raises(SystemExit):
        Git(str(tmp_path / "not-a-repo")).revparse(show_toplevel=True)


def test_clone_checks_out_repo(git_repo, tmp_path):
    branch = Git(str(git_repo)).branch(show_current=True)
    dest = str(tmp_path / "cloned")
    assert Git.clone(str(git_repo), dest, branch=branch, depth=1) == dest
    assert os.path.exists(os.path.join(dest, "test.txt"))


def test_clone_failure_exits(tmp_path):
    with pytest.raises(SystemExit):
        Git.clone(str(tmp_path / "missing-source"), str(tmp_path / "out"))


def test_ls_remote_tags_parses_tag_names(monkeypatch):
    out = "narcelio\trefs/tags/v30.2\nwashere\trefs/tags/v29.1"
    monkeypatch.setattr("bornal.git._exec", lambda argv: out)

    assert Git.ls_remote_tags("https://example/repo", "v*") == ["v30.2", "v29.1"]
