import importlib

import pytest

fixtures = importlib.import_module("bornal.fixtures")


@pytest.fixture
def setup(monkeypatch, tmp_path):
    monkeypatch.setenv("INTEGRATION_TEMP_DIR", str(tmp_path))
    monkeypatch.delenv("BINARIES_DIR", raising=False)


@pytest.fixture
def setup_error(setup, monkeypatch):
    from bornal.client import Client, ClientError

    def never_up(self, *a, **k):
        raise ClientError("rpc never came up")

    monkeypatch.setattr(Client, "wait_until_up", never_up)


def test_started_node_runs_and_stops_real_node(setup, spy_popen, spy_rpc):
    with fixtures._started_node("bitcoin-core") as node:
        assert node.client.get_block_count() == 0
        assert spy_popen.processes[0].argv[0].endswith("/bitcoind")

    assert spy_popen.processes[0].terminated


def test_started_node_stops_on_exception(setup, spy_popen, spy_rpc):
    try:
        with fixtures._started_node("bitcoin-core"):
            raise RuntimeError("boom")
    except RuntimeError:
        pass

    assert spy_popen.processes[0].terminated


def test_started_node_stops_when_rpc_never_comes_up(setup_error, spy_popen):
    from bornal.client import ClientError

    with pytest.raises(ClientError):
        with fixtures._started_node("bitcoin-core"):
            pass

    assert spy_popen.processes
    assert spy_popen.processes[0].terminated


def test_node_factory_fixture_opens_real_node(setup, node, spy_popen, spy_rpc):
    opened = node("bitcoin-core")
    assert opened.client.get_block_count() == 0
    assert spy_popen.processes
