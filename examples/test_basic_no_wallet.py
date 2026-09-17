"""
Two ``bitcoin-core`` regtest nodes without wallet support and basic operations
with chain, p2p, mining and sync blocks.

The ``base_test`` fixture survives between tests if ``stop=False``; with
``stop=True`` the ``TAG``ged session is stopped right after that test.

Blocks are mined to ``UNSPENDABLE_ADDRESS``, so no wallet is needed.

To run:

    pytest --build-bitcoin latest examples/test_basic_no_wallet.py
"""

import pytest

from bornal.testing import (
    assert_block_count,
    assert_chain,
    connect_p2p,
    sync_blocks,
)
from bornal.plugins.bitcoind import UNSPENDABLE_ADDRESS

TAG = "example-no-wallet"


def test_000_assert_chain(base_test):
    test = base_test(TAG, stop=False)
    assert len(test.backends) == 2
    for backend in test.backends:
        assert_chain(backend, "regtest")
        with pytest.raises(AssertionError):
            assert_chain(backend, "signet")


def test_001_connect_p2p(base_test):
    test = base_test(TAG, stop=False)
    alice = test.backends[0]
    bob = test.backends[1]
    connect_p2p(alice, bob)
    assert alice.client.get_connection_count() == 1


def test_002_block_count(base_test):
    test = base_test(TAG, stop=False)
    alice, bob = test.backends
    assert_block_count(alice, 0)
    assert_block_count(bob, 0)

    with pytest.raises(AssertionError):
        assert_block_count(alice, 21)


def test_003_generate_to_address(base_test):
    test = base_test(TAG, stop=False)
    alice = test.backends[0]
    hashes = alice.client.generate_to_address(1, UNSPENDABLE_ADDRESS)
    assert len(hashes) == 1
    assert_block_count(alice, 1)


def test_004_sync_blocks(base_test):
    test = base_test(TAG, stop=False)
    alice, bob = test.backends
    assert_block_count(alice, 1)
    sync_blocks(alice, bob)
    assert_block_count(bob, 1)


def test_005_sync_back(base_test):
    test = base_test(TAG, stop=True)
    alice, bob = test.backends
    bob.client.generate_to_address(2, UNSPENDABLE_ADDRESS)
    sync_blocks(bob, alice)
    assert_block_count(alice, 3)
