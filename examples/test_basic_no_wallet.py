"""
Two ``bitcoin-core`` regtest nodes without wallet support and basic operations
with chain, p2p, mining and sync blocks.

Fixtures use "one session per module" strategy. An integration test will only
finish on the last test (keep numbering helps since it depends on
block and sync).

Blocks are mined to ``UNSPENDABLE_ADDRESS``, so no wallet is needed.

To run:

    pytest --build-bitcoin latest examples/test_basic_no_wallet.py
"""

import pytest

from bornal.testing import (
    assert_block_count,
    assert_chain,
    connect_p2p,
    generate_to_address,
    sync_blocks,
)
from bornal.plugins.bitcoind import UNSPENDABLE_ADDRESS


def test_000_assert_chain(integration_test):
    assert len(integration_test.backends) == 2
    for backend in integration_test.backends:
        assert_chain(backend, "regtest")
        with pytest.raises(AssertionError):
            assert_chain(backend, "signet")


def test_001_connect_p2p(alice, bob):
    connect_p2p(alice, bob)
    assert alice.client.get_connection_count() == 1


def test_002_block_count(alice, bob):
    assert_block_count(alice, 0)
    assert_block_count(bob, 0)

    with pytest.raises(AssertionError):
        assert_block_count(alice, 21)


def test_003_generate_to_address(alice):
    hashes = generate_to_address(alice, UNSPENDABLE_ADDRESS, 1)
    assert len(hashes) == 1
    assert_block_count(alice, 1)


def test_004_sync_blocks(alice, bob):
    assert_block_count(alice, 1)
    sync_blocks(alice, bob)
    assert_block_count(bob, 1)


def test_005_sync_back(alice, bob):
    bob.client.generate_to_address(2, UNSPENDABLE_ADDRESS)
    sync_blocks(bob, alice)
    assert_block_count(alice, 3)
