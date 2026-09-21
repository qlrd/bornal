import importlib

import pytest

from bornal.client import Client, ClientError
from bornal.node import (
    IntegrationTest,
    Backend,
    BackendError,
    env_binaries_dir,
    env_data_dir,
    make_backend,
)
from bornal.plugins.bitcoind import BitcoindClient, BitcoindDaemon


class TwoNodes(IntegrationTest):
    # no ``on_stop_test``: the hook is optional; ``run_test`` is a no-op like a
    # session ``BaseTest`` (examples/conftest.py)
    def set_test_params(self):
        self.add_backend("bitcoin-core")
        self.add_backend("bitcoin-core")

    def run_test(self):
        pass


def _second_never_up(monkeypatch):
    """Make the second backend's RPC never come up (first still does)"""
    seen = []

    def wait(self, *args, **kwargs):
        seen.append(self.url)
        if len(seen) == 2:
            raise ClientError("rpc never came up")

    monkeypatch.setattr(Client, "wait_until_up", wait)


class Mixed(IntegrationTest):
    def set_test_params(self):
        self.add_backend("bitcoin-core")
        self.add_backend("no-such-daemon")

    def run_test(self):
        pass


def test_env_binaries_explicit(mocked_explicit_bin):
    assert env_binaries_dir() == "/explicit/bin"


def test_env_binaries_temp_dir(mocked_fallback_bin):
    assert env_binaries_dir() == "/tmp/run/binaries"


def test_env_data_dir(mocked_env_bin):
    assert env_data_dir() == "/tmp/run/data"


def test_reject_plugin(monkeypatch):
    mod = importlib.import_module("bornal.node")
    plugin = type("plugin", (), {"daemon_class": None})()
    monkeypatch.setattr(mod, "get", lambda name: plugin)
    with pytest.raises(ValueError, match="no daemon"):
        make_backend("build-only", "/bin", "/data")


def test_make_node_regtest(spy_popen, spy_rpc, tmp_path):
    node = make_backend("bitcoin-core", "/bin", str(tmp_path))
    node.start()
    try:
        argv = spy_popen.processes[0].argv
        assert argv[0] == "/bin/bitcoind"
        assert "-chain=regtest" in argv
        assert isinstance(node, Backend)
        assert isinstance(node.daemon, BitcoindDaemon)
        assert isinstance(node.client, BitcoindClient)
        assert node.client.get_block_count() == 0
    finally:
        node.stop()
    assert "stop" in spy_rpc.calls
    assert spy_popen.processes[0].terminated


def test_integration_success(spy_popen, spy_rpc, tmp_path):
    class MockTest(IntegrationTest):
        def set_test_params(self):
            self.add_backend("bitcoin-core")

        def run_test(self):
            assert self.backends[0].client.get_block_count() == 0

    MockTest("/bin", str(tmp_path)).main()
    assert "stop" in spy_rpc.calls
    assert spy_popen.processes[0].terminated


def test_integration_fail(spy_popen, spy_rpc, tmp_path):

    class MockTestA(IntegrationTest):
        pass

    class MockTestB(IntegrationTest):
        def set_test_params(self):
            self.add_backend("bitcoin-core")

    class MockTestC(IntegrationTest):
        def run_test(self):
            raise ValueError("mocked")

    class MockTestD(IntegrationTest):
        def set_test_params(self):
            self.add_backend("bitcoin-core")

        def run_test(self):
            raise ValueError("mocked")

    class MockTestE(IntegrationTest):
        def set_test_params(self):
            raise ValueError("mocked")

        def run_test(self):
            pass

    with pytest.raises(TypeError, match="Can't instantiate"):
        MockTestA("/bin", str(tmp_path)).main()

    with pytest.raises(TypeError, match="Can't instantiate"):
        MockTestB("/bin", str(tmp_path)).main()

    with pytest.raises(TypeError, match="Can't instantiate"):
        MockTestC("/bin", str(tmp_path)).main()

    with pytest.raises(ValueError, match="mocked"):
        MockTestD("/bin", str(tmp_path)).main()

    with pytest.raises(ValueError, match="mocked"):
        MockTestE("/bin", str(tmp_path)).main()
    assert spy_popen.processes[0].terminated


def test_session(spy_popen, spy_rpc, tmp_path):
    test = TwoNodes("/bin", str(tmp_path))
    assert test.backends == []

    test._on_set_test_params()
    assert len(test.backends) == 2
    assert test.backends[1].daemon.datadir.endswith("bitcoin-core1")
    assert spy_popen.processes == []

    test._on_run_test()
    assert all(b.client.get_block_count() == 0 for b in test.backends)
    assert [p.terminated for p in spy_popen.processes] == [False, False]

    test._on_stop_test()
    assert test.backends == []
    assert [p.terminated for p in spy_popen.processes] == [True, True]
    assert spy_rpc.calls.count("stop") == 2


def test_stop_on_errors(spy_popen, spy_rpc, tmp_path, monkeypatch):
    test = TwoNodes("/bin", str(tmp_path))
    test._on_set_test_params()
    test._on_run_test()
    _, second = test.backends

    def boom(*args, **kwargs):
        raise RuntimeError("stuck")

    monkeypatch.setattr(second.daemon, "stop", boom)
    with pytest.raises(BackendError, match=r"1 backend\(s\) failed to stop") as info:
        test._on_stop_test()

    assert test.backends == []
    assert spy_popen.processes[0].terminated
    (cause,) = info.value.exceptions
    assert isinstance(cause, RuntimeError)
    assert any("bitcoind" in note for note in cause.__notes__)


def test_run_test_fail(spy_popen, spy_rpc, tmp_path, monkeypatch):
    _second_never_up(monkeypatch)
    test = TwoNodes("/bin", str(tmp_path))
    test._on_set_test_params()
    with pytest.raises(ClientError, match="never came up"):
        test._on_run_test()
    assert test.backends == []
    assert [p.terminated for p in spy_popen.processes] == [True, True]


def test_set_test_params_unknown_plugin(spy_popen, spy_rpc, tmp_path):
    with pytest.raises(SystemExit):
        Mixed("/bin", str(tmp_path))._on_set_test_params()
    assert spy_popen.processes == []


def test_on_stop_test(spy_popen, spy_rpc, tmp_path):
    order = []

    class Hooked(IntegrationTest):
        def set_test_params(self):
            self.add_backend("bitcoin-core")

        def run_test(self):
            order.append(("run_test", spy_popen.processes[0].terminated))

        def on_stop_test(self):
            order.append(("on_stop_test", spy_popen.processes[0].terminated))

    Hooked("/bin", str(tmp_path)).main()
    assert order == [("run_test", False), ("on_stop_test", False)]
    assert spy_popen.processes[0].terminated


def test_on_stop_test_stops(spy_popen, spy_rpc, tmp_path):
    class Hooked(IntegrationTest):
        def set_test_params(self):
            self.add_backend("bitcoin-core")

        def run_test(self):
            pass

        def on_stop_test(self):
            raise AssertionError("final state wrong")

    with pytest.raises(AssertionError, match="final state wrong"):
        Hooked("/bin", str(tmp_path)).main()
    assert spy_popen.processes[0].terminated


def test_on_stop_test_fails(spy_popen, spy_rpc, tmp_path, monkeypatch):
    calls = []

    class Hooked(TwoNodes):
        def on_stop_test(self):
            calls.append(len(self.backends))

    _second_never_up(monkeypatch)
    with pytest.raises(ClientError, match="never came up"):
        Hooked("/bin", str(tmp_path)).main()
    assert calls == [2]
    assert [p.terminated for p in spy_popen.processes] == [True, True]
