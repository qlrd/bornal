"""
Two ``bitcoin-core`` regtest nodes built with wallet support, a hot wallet on
``backends[0]`` (alice) and a watch-only wallet on ``backends[1]`` (bob) that
imports the same hot wallet's public descriptor (like a backup)

One session per module: ``integration_test`` starts the two nodes that
``test_factory`` in ``conftest.py`` declares and stops them after the last
test, so the numbering matters. What one test produces for the next travels in
``integration_test.state``.

To run:

    pytest --build-bitcoin latest --wallet examples/test_basic_wallet.py
"""

import pytest
from bornal.plugins.bitcoind import UNSPENDABLE_ADDRESS
from bornal.testing import (
    BASE_COINBASE_SUBSIDY,
    COINBASE_MATURITY,
    assert_block_count,
    assert_finalized,
    assert_mempool_accepts,
    assert_mempool_rejects,
    assert_next_role,
    assert_not_finalized,
    assert_send_rawtx_accepts,
    assert_send_rawtx_rejects,
    assert_wallet_info,
    connect_p2p,
    create_wallet,
    generate_to_address,
    get_new_address,
    sync_blocks,
    wait_wallet_synced,
)

ALICE = "alice"
BOB = "bob"
PAYMENT = 1


def test_000_create_hot_wallet(alice):
    res = create_wallet(alice, ALICE)

    assert res["name"] == ALICE
    assert alice.client.list_wallets() == [ALICE]
    assert_wallet_info(alice, ALICE)
    with pytest.raises(AssertionError, match=f"Expected wallet '{BOB}', got '{ALICE}'"):
        assert_wallet_info(alice, BOB)
    with pytest.raises(AssertionError, match="Expected a watch-only wallet"):
        assert_wallet_info(alice, ALICE, watchonly=True)


def test_001_create_watchonly_wallet(alice, bob):
    descriptors = alice.client.call("listdescriptors")["descriptors"]
    external_wpkh = next(
        d["desc"]
        for d in descriptors
        if d["desc"].startswith("wpkh(") and not d["internal"]
    )
    imports = [
        {"desc": external_wpkh, "active": True, "range": [0, 10], "timestamp": "now"}
    ]

    create_wallet(bob, BOB, watchonly=True, descriptors=imports)
    assert_wallet_info(bob, BOB, watchonly=True)
    with pytest.raises(AssertionError, match="Expected a hot wallet"):
        assert_wallet_info(bob, BOB, False)

    alice_addr = alice.client.get_new_address(
        f"{ALICE}::test_basic_wallet::test_001_create_watch_only_wallet", "bech32"
    )
    bob_addr = bob.client.get_new_address(
        f"{BOB}::test_basic_wallet::test_001_create_watch_only_wallet", "bech32"
    )
    assert alice_addr.startswith("bcrt")
    assert bob_addr.startswith("bcrt")
    assert alice_addr == bob_addr


def test_002_connect_and_sync(integration_test):
    alice, bob = integration_test.backends
    connect_p2p(alice, bob)
    assert_block_count(alice, 0)
    assert_block_count(bob, 0)


def test_003_mine(alice, bob):
    address = get_new_address(
        alice, f"{ALICE}::test_basic_wallet::test_003_mine", "bech32"
    )
    hashes = generate_to_address(bob, address, COINBASE_MATURITY + 1)
    assert len(hashes) == 101

    sync_blocks(bob, alice)
    wait_wallet_synced(alice)
    assert_block_count(alice, COINBASE_MATURITY + 1)
    assert alice.client.get_address_info(address)["ismine"]

    mine = alice.client.get_balances()["mine"]
    assert mine["trusted"] == BASE_COINBASE_SUBSIDY
    assert mine["immature"] == BASE_COINBASE_SUBSIDY * COINBASE_MATURITY
    (utxo,) = alice.client.list_unspent()
    assert utxo["amount"] == BASE_COINBASE_SUBSIDY


def test_004_psbt_needs_an_updater(alice):
    (utxo,) = alice.client.list_unspent()
    outpoint = {"txid": utxo["txid"], "vout": utxo["vout"]}
    addr = get_new_address(
        alice,
        f"{ALICE}::test_basic_wallet::test_004_psbt_needs_an_updater",
    )
    outputs = [{addr: PAYMENT}]
    bare = alice.client.create_psbt([outpoint], outputs)
    assert_next_role(alice, bare, "updater")


def test_005_fund_psbt(alice, state):
    address = get_new_address(
        alice, f"{ALICE}::test_basic_wallet::test_005_fund_psbt", "bech32"
    )
    outputs = [{address: PAYMENT}]
    psbt = alice.client.wallet_create_funded_psbt([], outputs)["psbt"]

    assert_next_role(alice, psbt, "signer")
    assert_not_finalized(alice, psbt)

    (vin,) = alice.client.decode_psbt(psbt)["inputs"]
    assert "final_scriptwitness" not in vin
    state["psbt"] = psbt


def test_006_check_not_finalized(alice, state):
    psbt = state["psbt"]
    with pytest.raises(AssertionError, match="should be complete"):
        assert_finalized(alice, psbt)


def test_007_sign(alice, state):
    psbt = state["psbt"]
    signed = alice.client.wallet_process_psbt(psbt)["psbt"]

    with pytest.raises(AssertionError, match="should not be complete"):
        assert_not_finalized(alice, signed)

    with pytest.raises(AssertionError, match="should be 'signer', got 'extractor'"):
        assert_next_role(alice, signed, "signer")

    assert_next_role(alice, signed, "extractor")
    hextx = assert_finalized(alice, signed)
    decoded = alice.client.decode_raw_transaction(hextx, True)
    assert len(decoded["vin"]) == 1
    assert len(decoded["vout"]) == 2


def test_008_raw_transaction_mempool(alice, state):
    outputs = [{UNSPENDABLE_ADDRESS: PAYMENT}]
    unsigned = alice.client.call(
        "fundrawtransaction", alice.client.create_raw_transaction([], outputs)
    )["hex"]

    with pytest.raises(AssertionError, match="should be allowed"):
        assert_mempool_accepts(alice, unsigned)
    reason = assert_mempool_rejects(alice, unsigned)
    assert reason.startswith("mempool-script-verify-flag-failed")
    with pytest.raises(AssertionError, match="Rejection should match"):
        assert_mempool_rejects(alice, unsigned, "bad-txns-in-belowout")

    signed = alice.client.sign_raw_transaction_with_wallet(unsigned)["hex"]
    accepted = assert_mempool_accepts(alice, signed)
    assert accepted["fees"]["base"] > 0
    with pytest.raises(AssertionError, match="should not be allowed"):
        assert_mempool_rejects(alice, signed)
    assert alice.client.get_raw_mempool() == []
    state["unsigned_rawtx"] = unsigned
    state["signed_rawtx"] = signed


def test_009_broadcast(alice, state):
    unsigned, signed = (
        state["unsigned_rawtx"],
        state["signed_rawtx"],
    )

    error = assert_send_rawtx_rejects(alice, unsigned)
    assert "'code': -26" in error
    assert alice.client.get_raw_mempool() == []

    txid = assert_send_rawtx_accepts(alice, signed)
    assert alice.client.get_raw_mempool() == [txid]
    with pytest.raises(AssertionError, match="should not be broadcastable"):
        assert_send_rawtx_rejects(alice, signed)


def test_010_confirm(alice, bob):
    (txid,) = alice.client.get_raw_mempool()
    address = get_new_address(
        alice, f"{ALICE}::test_basic_wallet::test_010_confirm", "bech32"
    )
    generate_to_address(alice, address, 1)
    assert alice.client.get_raw_mempool() == []
    assert alice.client.get_transaction(txid)["confirmations"] == 1

    # the watch-only wallet saw its coin being spent too
    sync_blocks(alice, bob)
    wait_wallet_synced(bob)
    assert bob.client.get_transaction(txid)["confirmations"] == 1
