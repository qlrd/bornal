"""``bornal.fixtures`` the way pytest uses it.

Each test runs an inner pytest session (``pytester``) whose conftest overrides
``test_factory``; the outer ``spy_popen`` / ``spy_rpc`` still intercept the
process and the JSON-RPC transport, so the inner session's nodes are spied.
"""

import pytest

# This is a inline script so we can apply customized tests. The following strategy
# appears to be an easy and customizable one from a class and call it for
# fixture-style tests
CONFTEST = """
import pytest

from bornal.daemon import free_port
from bornal.node import IntegrationTest


class SimpleTwoBitcoinCoreNodesTest(IntegrationTest):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.state: dict = {}
        self.localhost = "127.0.0.1"
        self.nodes = [
            {"daemon": "bitcoin-core", "p2p_port": free_port()},
            {"daemon": "bitcoin-core", "p2p_port": free_port()},
        ]

    def set_test_params(self):
        for node in self.nodes:
            self.log.info(
                f"Preparing '{node.get('daemon')}' ({self.localhost}:{node.get('p2p_port')})"
            )
            self.add_backend(node.get("daemon"), p2p_port=node.get("p2p_port"))

    def run_test(self):
        self.log.info("Tests running")

    def on_stop_test(self):
        self.log.info("Tests stopped")


@pytest.fixture(scope="module")
def test_factory():
    return SimpleTwoBitcoinCoreNodesTest
"""

MODULE = """

import pytest

from bornal.testing import (
    assert_block_count,
    assert_chain,
    connect_p2p,
    sync_blocks,
)
from bornal.plugins.bitcoind import UNSPENDABLE_ADDRESS


def test_000_assert_chain(integration_test):
    assert len(integration_test.backends) == 2
    for backend in integration_test.backends:
        assert_chain(backend, "regtest")
        with pytest.raises(AssertionError):
            assert_chain(backend, "signet")


def test_001_connect_p2p(integration_test):
    alice, bob = integration_test.backends
    connect_p2p(alice, bob)
    assert alice.client.get_connection_count() == 1


def test_002_block_count(integration_test):
    alice, bob = integration_test.backends
    assert_block_count(alice, 0)
    assert_block_count(bob, 0)

    with pytest.raises(AssertionError):
        assert_block_count(alice, 21)


def test_003_generate_to_address(integration_test):
    alice = integration_test.backends[0]
    hashes = alice.client.generate_to_address(1, UNSPENDABLE_ADDRESS)
    assert len(hashes) == 1
    assert_block_count(alice, 1)


def test_004_sync_blocks(integration_test):
    alice, bob = integration_test.backends
    assert_block_count(alice, 1)
    sync_blocks(alice, bob)
    assert_block_count(bob, 1)


def test_005_sync_back(integration_test):
    alice, bob = integration_test.backends
    bob.client.generate_to_address(2, UNSPENDABLE_ADDRESS)
    sync_blocks(bob, alice)
    assert_block_count(alice, 3)
"""


@pytest.fixture
def setup(monkeypatch, tmp_path):
    monkeypatch.setenv("INTEGRATION_TEMP_DIR", str(tmp_path))
    monkeypatch.delenv("BINARIES_DIR", raising=False)


def _run(pytester):
    return pytester.runpytest_inprocess("-p", "no:cacheprovider")


def test_one_session_per_module(setup, spy_popen, spy_rpc, pytester):
    pytester.makeconftest(CONFTEST)
    pytester.makepyfile(MODULE)
    _run(pytester).assert_outcomes(passed=6)

    is_well = [p.argv[0].endswith("/bitcoind") for p in spy_popen.processes]
    as_expected = [True, True]
    assert is_well == as_expected
    assert all(p.terminated for p in spy_popen.processes)
    assert spy_rpc.calls.count("stop") == 2


def test_data_dir_module_name(setup, spy_popen, spy_rpc, pytester, tmp_path):
    pytester.makeconftest(CONFTEST)
    pytester.makepyfile(test_mod="def test_a(integration_test): pass")
    _run(pytester).assert_outcomes(passed=1)

    datadirs = [
        a for p in spy_popen.processes for a in p.argv if a.startswith("-datadir=")
    ]
    base = tmp_path / "data" / "test_mod"
    assert datadirs == [
        f"-datadir={base}/bitcoin-core0",
        f"-datadir={base}/bitcoin-core1",
    ]


def test_missing_factory(setup, spy_popen, pytester):
    pytester.makepyfile("def test_a(integration_test): pass")
    result = _run(pytester)
    result.assert_outcomes(errors=1)
    result.stdout.fnmatch_lines(["*defines no test_factory fixture*"])
    assert spy_popen.processes == []


def test_rpc_never_comes_up(setup, spy_popen, spy_rpc, pytester, monkeypatch):
    from bornal.client import Client, ClientError

    def never_up(self, *args, **kwargs):
        raise ClientError("rpc never came up")

    monkeypatch.setattr(Client, "wait_until_up", never_up)
    pytester.makeconftest(CONFTEST)
    pytester.makepyfile("def test_a(integration_test): pass")
    result = _run(pytester)
    result.assert_outcomes(errors=1)
    result.stdout.fnmatch_lines(["*rpc never came up*"])
    # the first node was spawned and is stopped before the error surfaces
    assert spy_popen.processes and all(p.terminated for p in spy_popen.processes)
