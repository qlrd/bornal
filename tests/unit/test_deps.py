import pytest

from bornal import deps

"""
These are just smoke tests, more real tests will be in ``tests/functional``

Basically smoking testing if we have some binaries or not:

- git
- cmake
- make
- automake
- autoconf
- gcc
- clang
- cmake
"""


def test_check_installed_passes_when_present(monkeypatch):
    monkeypatch.setattr(deps, "which", lambda n: "/usr/bin/%s" % n)
    deps.check_installed("git", "cmake", "make", "automake", "autoconf", "gcc", "clang")


def test_check_installed_exits_when_missing(monkeypatch):
    monkeypatch.setattr(deps, "which", lambda n: None)

    # process returned exit(1)
    with pytest.raises(SystemExit):
        deps.check_installed("selfcustody")
