import os


def test_bornal_create(run, git_repo):
    run("create")
    dest = os.path.join(
        os.path.realpath(str(git_repo)),
        "tests",
        "integration",
        "test_bitcoin_core.py",
    )
    assert os.path.exists(dest)
