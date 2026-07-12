import importlib

import pytest

from bornal.node import (
    IntegrationTest,
    Node,
    env_binaries_dir,
    env_data_dir,
    make_node,
)
from bornal.plugins.bitcoind import BitcoindCli, BitcoindDaemon


def test_env_binaries_dir_prefers_explicit(mocked_explicit_bin):
    assert env_binaries_dir() == "/explicit/bin"


def test_env_binaries_dir_falls_back_to_temp_dir(mocked_fallback_bin):
    assert env_binaries_dir() == "/tmp/run/binaries"


def test_env_data_dir(mocked_env_bin):
    assert env_data_dir() == "/tmp/run/data"


def test_reject_build_plugin(monkeypatch):
    mod = importlib.import_module("bornal.node")
    plugin = type("plugin", (), {"daemon_class": None})()
    monkeypatch.setattr(mod, "get", lambda name: plugin)
    with pytest.raises(ValueError, match="no daemon"):
        make_node("build-only", "/bin", "/data")


def test_make_node_regtest(spy_popen, spy_rpc, tmp_path):
    node = make_node("bitcoin-core", "/bin", str(tmp_path))
    node.start()
    try:
        argv = spy_popen.processes[0].argv
        assert argv[0] == "/bin/bitcoind"
        assert "-chain=regtest" in argv
        assert isinstance(node, Node)
        assert isinstance(node.daemon, BitcoindDaemon)
        assert isinstance(node.cli, BitcoindCli)
        assert node.cli.get_block_count() == 0
    finally:
        node.stop()
    assert "stop" in spy_rpc.calls
    assert spy_popen.processes[0].terminated


def test_integration_success(spy_popen, spy_rpc, tmp_path):
    class MockTest(IntegrationTest):
        def set_test_params(self):
            self.add_node("bitcoin-core")

        def run_test(self):
            assert self.nodes[0].cli.get_block_count() == 0

    MockTest("/bin", str(tmp_path)).main()
    assert "stop" in spy_rpc.calls
    assert spy_popen.processes[0].terminated


def test_integration_fail(spy_popen, spy_rpc, tmp_path):
    class MockTest(IntegrationTest):
        def set_test_params(self):
            self.add_node("bitcoin-core")

        def run_test(self):
            raise ValueError("mocked")

    with pytest.raises(ValueError, match="mocked"):
        MockTest("/bin", str(tmp_path)).main()
    assert spy_popen.processes[0].terminated
