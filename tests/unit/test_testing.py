# These tests drive a real ``Node/Client```; only the process and
# the JSON-RPC transport are spied
import json
from unittest.mock import MagicMock

import pytest

from bornal.client import ClientError
from bornal.node import make_backend
from bornal.testing import (
    assert_finalized,
    assert_mempool_accepts,
    assert_mempool_rejects,
    assert_next_role,
    assert_not_finalized,
    assert_send_rawtx_accepts,
    assert_send_rawtx_rejects,
    assert_wallet_info,
    assert_wallet_roundtrip,
    connect_p2p,
    create_wallet,
    generate_to_address,
    sync_blocks,
)

DESCRIPTOR = (
    "wpkh(tpubD6NzVbkrYhZ4WaWSyoBvQwbpLkojyoTZPRsgXELWz3Popb3qkjcJyJUGLnL4qHHoQva"
    "o8ESaAstxYSnhyswJ76uZPStJRJCTKvosUCJZL5B/0/*)#efr7m7hr"
)
IMPORT = [{"desc": DESCRIPTOR, "active": True, "range": [0, 10], "timestamp": "now"}]
PSBT = "cHNidP8BAHECAAAAAQ=="
TX = "02000000000101"


@pytest.fixture
def p2p_pair(tmp_path, spy_popen, spy_rpc):
    alice = make_backend("bitcoin-core", "/bin", str(tmp_path / "a")).start()
    bob = make_backend("bitcoin-core", "/bin", str(tmp_path / "b"), p2p_port=18444)
    return alice, bob.start()


def _called_as(spy_rpc, method):
    for req in spy_rpc.requests:
        payload = json.loads(req.data)
        if payload["method"] == method:
            return payload["params"]
    raise LookupError(method)


def test_assert_wallet_roundtrip(run_backend, spy_popen, spy_rpc):
    node = run_backend("bitcoin-core")
    assert_wallet_roundtrip(node)

    assert "createwallet" in spy_rpc.calls
    assert "generatetoaddress" in spy_rpc.calls
    assert "getbalance" in spy_rpc.calls
    assert "listwallets" in spy_rpc.calls


def test_assert_wallet_roundtrip_error(monkeypatch, run_backend, spy_popen, spy_rpc):
    node = run_backend("bitcoin-core")

    monkeypatch.setattr(
        node.client,
        "create_wallet",
        MagicMock(side_effect=ClientError("not implemented")),
    )
    with pytest.raises(AssertionError, match="not implemented"):
        assert_wallet_roundtrip(node)


def test_assert_wallet_roundtrip_lowbalance(
    monkeypatch, run_backend, spy_popen, spy_rpc
):
    node = run_backend("bitcoin-core")
    monkeypatch.setattr(node.client, "get_balance", MagicMock(return_value=0))
    with pytest.raises(AssertionError, match="Balance should be at least"):
        assert_wallet_roundtrip(node)


def test_assert_wallet_roundtrip_noutxo(monkeypatch, run_backend, spy_popen, spy_rpc):
    node = run_backend("bitcoin-core")
    monkeypatch.setattr(node.client, "list_unspent", MagicMock(return_value=[]))
    with pytest.raises(AssertionError, match="1 or more UTXOs"):
        assert_wallet_roundtrip(node)


def test_assert_wallet_roundtrip_any_utxo(monkeypatch, run_backend, spy_popen, spy_rpc):
    node = run_backend("bitcoin-core")
    elsewhere = [{"address": "bcrt1qelsewhere", "amount": 50}]
    monkeypatch.setattr(node.client, "list_unspent", MagicMock(return_value=elsewhere))
    with pytest.raises(AssertionError, match="list any UTXO"):
        assert_wallet_roundtrip(node)


def test_assert_wallet_roundtrip_wallet_missing(
    monkeypatch, run_backend, spy_popen, spy_rpc
):
    node = run_backend("bitcoin-core")
    monkeypatch.setattr(node.client, "list_wallets", MagicMock(return_value=[]))
    with pytest.raises(AssertionError, match="should create 'bornal-wallet'"):
        assert_wallet_roundtrip(node)


def test_generatetoaddress_fail(monkeypatch, run_backend, spy_popen, spy_rpc):
    node = run_backend("bitcoin-core")
    hack = MagicMock(side_effect=ClientError("hacked"))
    monkeypatch.setattr(node.client, "generate_to_address", hack)
    with pytest.raises(AssertionError, match="generatetoaddress failed"):
        generate_to_address(node, 1)
    monkeypatch.setattr(node.client, "get_new_address", hack)
    with pytest.raises(AssertionError, match="getnewaddress failed"):
        generate_to_address(node, 1)


def test_create_wallet(run_backend, spy_popen, spy_rpc):
    node = run_backend("bitcoin-core")
    assert create_wallet(node, "hot") == {"name": "hot"}
    assert _called_as(spy_rpc, "createwallet") == ["hot", False, False]


def test_create_wallet_mismatch(monkeypatch, run_backend, spy_popen, spy_rpc):
    node = run_backend("bitcoin-core")
    other = MagicMock(return_value={"name": "other"})
    monkeypatch.setattr(node.client, "create_wallet", other)
    with pytest.raises(AssertionError, match="Expected wallet 'hot'"):
        create_wallet(node, "hot")


def test_create_wallet_watchonly_fail(run_backend, spy_popen, spy_rpc):
    node = run_backend("bitcoin-core")
    with pytest.raises(ValueError, match="needs descriptors"):
        create_wallet(node, "cold", True)
    assert "createwallet" not in spy_rpc.calls


def test_create_wallet_watchonly(run_backend, spy_popen, spy_rpc):
    node = run_backend("bitcoin-core")
    create_wallet(node, "cold", True, IMPORT)
    assert _called_as(spy_rpc, "createwallet") == ["cold", True, True]
    assert _called_as(spy_rpc, "importdescriptors") == [IMPORT]


def test_create_wallet_watchonly_import_fail(run_backend, spy_popen, spy_rpc):
    node = run_backend("bitcoin-core")
    unchecked = [{**IMPORT[0], "desc": DESCRIPTOR.split("#")[0]}]
    with pytest.raises(AssertionError, match="importdescriptors failed"):
        create_wallet(node, "cold", True, unchecked)


def test_assert_wallet_info_hot(run_backend, spy_popen, spy_rpc):
    node = run_backend("bitcoin-core")
    create_wallet(node, "hottestmock", False)
    assert_wallet_info(node, "hottestmock")


def test_assert_wallet_info_watchonly(run_backend, spy_popen, spy_rpc):
    node = run_backend("bitcoin-core")
    create_wallet(node, "coldtestmock", True, IMPORT)
    assert_wallet_info(node, "coldtestmock", True)
    assert "importdescriptors" in spy_rpc.calls


def test_assert_wallet_info_fail_name(run_backend, spy_popen, spy_rpc):
    node = run_backend("bitcoin-core")
    create_wallet(node, "hot")
    with pytest.raises(AssertionError, match="Expected wallet 'cold'"):
        assert_wallet_info(node, "cold")


def test_assert_wallet_info_fail_kind(run_backend, spy_popen, spy_rpc):
    node = run_backend("bitcoin-core")
    create_wallet(node, "hot")
    with pytest.raises(AssertionError, match="Expected a watch-only wallet"):
        assert_wallet_info(node, "hot", True)


def test_assert_wallet_info_scan(monkeypatch, run_backend, spy_popen, spy_rpc):
    node = run_backend("bitcoin-core")
    scanning = {
        "walletname": "hot",
        "private_keys_enabled": True,
        "scanning": {"duration": 1, "progress": 0.5},
    }
    monkeypatch.setattr(
        node.client, "get_wallet_info", MagicMock(return_value=scanning)
    )
    with pytest.raises(AssertionError, match="still scanning"):
        assert_wallet_info(node, "hot")


def test_assert_wallet_info_single_wallet(run_backend, spy_popen, spy_rpc):
    node = run_backend("bitcoin-core")
    create_wallet(node, "one")
    create_wallet(node, "two")
    with pytest.raises(ClientError, match="Multiple wallets are loaded"):
        assert_wallet_info(node, "two")


def test_connect_p2p(p2p_pair, spy_rpc):
    alice, bob = p2p_pair
    connect_p2p(alice, bob, timeout=1)
    assert _called_as(spy_rpc, "addnode") == [f"{bob.daemon.host}:18444", "onetry"]
    assert "getblockcount" in spy_rpc.calls


def test_connect_p2p_needs_p2p_port(p2p_pair, spy_rpc):
    alice, bob = p2p_pair
    with pytest.raises(ValueError, match="p2p disabled"):
        connect_p2p(bob, alice)
    assert "addnode" not in spy_rpc.calls


def test_connect_p2p_unexpected_response(monkeypatch, p2p_pair):
    alice, bob = p2p_pair
    monkeypatch.setattr(alice.client, "add_node", MagicMock(return_value="nope"))
    with pytest.raises(AssertionError, match="expected to be None"):
        connect_p2p(alice, bob)


def test_sync_blocks_timeout(monkeypatch, p2p_pair):
    alice, bob = p2p_pair
    monkeypatch.setattr(bob.client, "get_block_count", MagicMock(return_value=1))
    with pytest.raises(AssertionError, match="did not sync"):
        sync_blocks(alice, bob, timeout=1)


def test_assert_finalized(run_backend, spy_popen, spy_rpc):
    node = run_backend("bitcoin-core")
    spy_rpc.finalizable.append(PSBT)
    assert len(assert_finalized(node, PSBT)) == 64
    assert _called_as(spy_rpc, "finalizepsbt") == [PSBT, True]
    with pytest.raises(AssertionError, match="should not be complete"):
        assert_not_finalized(node, PSBT)


def test_assert_not_finalized(run_backend, spy_popen, spy_rpc):
    node = run_backend("bitcoin-core")
    assert assert_not_finalized(node, PSBT) == PSBT
    with pytest.raises(AssertionError, match="should be complete"):
        assert_finalized(node, PSBT)


def test_assert_next_role(run_backend, spy_popen, spy_rpc):
    node = run_backend("bitcoin-core")
    assert assert_next_role(node, PSBT)["next"] == "updater"
    spy_rpc.roles[PSBT] = "signer"
    assert assert_next_role(node, PSBT, "signer")["next"] == "signer"
    with pytest.raises(AssertionError, match="should be 'updater', got 'signer'"):
        assert_next_role(node, PSBT)


def test_assert_mempool_accepts(run_backend, spy_popen, spy_rpc):
    node = run_backend("bitcoin-core")
    spy_rpc.acceptable.append(TX)
    assert assert_mempool_accepts(node, TX)["allowed"]
    assert _called_as(spy_rpc, "testmempoolaccept") == [[TX], 0.1]
    with pytest.raises(AssertionError, match="should not be allowed"):
        assert_mempool_rejects(node, TX)


def test_assert_mempool_rejects(run_backend, spy_popen, spy_rpc):
    node = run_backend("bitcoin-core")
    reason = assert_mempool_rejects(node, TX)
    assert reason.startswith("mempool-script-verify-flag-failed (")
    with pytest.raises(AssertionError, match="should be allowed"):
        assert_mempool_accepts(node, TX)
    with pytest.raises(AssertionError, match="Rejection should match"):
        assert_mempool_rejects(node, TX, "bad-txns-in-belowout")


def test_assert_send_rawtx_accepts(run_backend, spy_popen, spy_rpc):
    node = run_backend("bitcoin-core")
    spy_rpc.acceptable.append(TX)
    assert len(assert_send_rawtx_accepts(node, TX)) == 64
    assert _called_as(spy_rpc, "sendrawtransaction") == [TX, 0.1]
    with pytest.raises(AssertionError, match="should not be broadcastable"):
        assert_send_rawtx_rejects(node, TX)


def test_assert_send_rawtx_rejects(run_backend, spy_popen, spy_rpc):
    node = run_backend("bitcoin-core")
    error = assert_send_rawtx_rejects(node, TX)
    assert "'code': -26" in error and "mempool-script-verify-flag-failed" in error
    with pytest.raises(AssertionError, match="should be broadcastable"):
        assert_send_rawtx_accepts(node, TX)
    with pytest.raises(AssertionError, match="Rejection should match"):
        assert_send_rawtx_rejects(node, TX, "bad-txns-in-belowout")
