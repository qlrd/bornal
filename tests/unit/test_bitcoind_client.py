import json

import pytest

from bornal.client import ClientError
from bornal.node import make_backend
from bornal.plugins.bitcoind import UNSPENDABLE_ADDRESS
from bornal.testing import BASE_COINBASE_SUBSIDY, COINBASE_MATURITY


def payload(spy_rpc):
    return json.loads(spy_rpc.req.data)


def test_get_connection_count(spy_popen, spy_rpc, tmp_path):
    client = make_backend("bitcoin-core", "/bin", str(tmp_path)).start().client
    assert client.get_connection_count() == 0
    assert payload(spy_rpc)["method"] == "getconnectioncount"
    assert payload(spy_rpc)["params"] == []

    client.add_node("127.0.0.1:18444", "onetry")
    assert client.get_connection_count() == 1


def test_wallet_wrappers_need_a_wallet(spy_popen, spy_rpc, tmp_path):
    client = make_backend("bitcoin-core", "/bin", str(tmp_path)).start().client
    with pytest.raises(ClientError, match="No wallet is loaded"):
        client.get_balances()
    with pytest.raises(ClientError, match="No wallet is loaded"):
        client.get_address_info(UNSPENDABLE_ADDRESS)
    assert spy_rpc.calls[-2:] == ["getbalances", "getaddressinfo"]


def test_get_address_info(spy_popen, spy_rpc, tmp_path):
    client = make_backend("bitcoin-core", "/bin", str(tmp_path)).start().client
    client.create_wallet("miner")
    mine = client.get_new_address(
        f"test_bitcoind_client::test_get_address_info::{tmp_path}"
    )

    info = client.get_address_info(mine)
    assert payload(spy_rpc) == {
        "jsonrpc": "1.0",
        "id": "bornal",
        "method": "getaddressinfo",
        "params": [mine],
    }
    assert info["address"] == mine
    assert info["ismine"] is True
    assert client.get_address_info(UNSPENDABLE_ADDRESS)["ismine"] is False


def test_get_balances(spy_popen, spy_rpc, tmp_path):
    client = make_backend("bitcoin-core", "/bin", str(tmp_path)).start().client
    client.create_wallet("miner")
    mine = client.get_new_address(
        f"test_bitcoind_client::test_get_balances::{tmp_path}", "legacy"
    )

    client.generate_to_address(COINBASE_MATURITY + 1, mine)
    balances = client.get_balances()
    assert payload(spy_rpc)["method"] == "getbalances"
    assert balances["mine"]["trusted"] == BASE_COINBASE_SUBSIDY
    assert balances["mine"]["immature"] == BASE_COINBASE_SUBSIDY * COINBASE_MATURITY
    assert balances["mine"]["untrusted_pending"] == 0
    assert balances["lastprocessedblock"]["height"] == COINBASE_MATURITY + 1

    client.generate_to_address(1, UNSPENDABLE_ADDRESS)
    foreign = client.get_balances()["mine"]
    assert foreign["trusted"] == 0 and foreign["immature"] == 0
