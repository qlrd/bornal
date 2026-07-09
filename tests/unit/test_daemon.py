import os

import pytest

from bornal import daemon
from bornal.daemon import Compiler, free_port


def test_register_bitcoind():
    registred = daemon.registry()
    assert "bitcoin-core" in registred
    assert isinstance(registred["bitcoin-core"], Compiler)
    assert "bitcoin-core" in daemon.names()


def test_no_daemon_exits():
    with pytest.raises(SystemExit):
        daemon.get("does-not-exist")


# Below are just the idealized ones for this project to check just
# the construction of the flag string
@pytest.mark.parametrize(
    "implementation",
    [
        "bitcoin-core",
        "utreexod",
        "floresta",
        "liana",
    ],
)
def test_flag_plugin(implementation):
    impl = implementation.split("-")[0]
    assert daemon.build_flag_for(implementation) == "--build-%s" % impl


# a abstract plugin that does nothing and didnt set anything on build_flag
def test_compiler_build_flag_default():
    assert Compiler.build_flag is None


def test_export_core_path(paths):
    env = daemon.get("bitcoin-core").env(paths)
    assert env["BITCOIN_CORE_PATH"] == paths.binaries_dir
    assert env["BITCOIND"] == os.path.join(paths.binaries_dir, "bitcoind")
    assert "BITCOIN_CLI" not in env  # not built with env


def test_free_port():
    port = free_port()
    assert isinstance(port, int)
    assert 1 <= port <= 65535


def test_daemon_start(spy_popen, mocked_daemon):
    mocked_daemon.start()
    assert mocked_daemon.is_running
    assert mocked_daemon.binary == "/bin/mocku"
    assert spy_popen.processes[0].argv == ["/bin/mocku", "--flag", "-extra"]


def test_daemon_fail_start_twice(spy_popen, mocked_daemon):
    mocked_daemon.start()
    with pytest.raises(RuntimeError, match="already running"):
        mocked_daemon.start()


def test_daemon_stop(spy_popen, mocked_daemon):
    mocked_daemon.start()
    mocked_daemon.stop()
    assert not mocked_daemon.is_running
    assert spy_popen.processes[0].terminated


def test_daemon_stop_without_start(spy_popen, mocked_daemon):
    # In this case nothing is raised because we not started
    mocked_daemon.stop()
    assert not mocked_daemon.is_running
    assert not len(spy_popen.processes)


def test_daemon_kill_on_timeout(spy_popen, mocked_daemon):
    spy_popen.stuck = True
    mocked_daemon.start()
    mocked_daemon.stop()
    assert mocked_daemon._process is None
    assert spy_popen.processes[0].killed
    assert spy_popen.processes[0].returncode == -9


def test_network_default_regtest(mocked_daemon):
    assert mocked_daemon.network == "regtest"


def test_endpoint(mocked_daemon):
    assert mocked_daemon.make_cli().url == "http://127.0.0.1:5555"


def test_make_cli_without_cli(tmp_path, mocked_daemon):
    class _NoCli(mocked_daemon.__class__):
        cli_class = None

    with pytest.raises(NotImplementedError):
        _NoCli("/bin", str(tmp_path), port=5555).make_cli()
