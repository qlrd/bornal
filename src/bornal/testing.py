from .client import ClientError
from .logger import LOG

__all__ = ["COINBASE_MATURITY", "COINBASE_SUBSIDY", "assert_wallet_roundtrip"]

COINBASE_SUBSIDY = 50
COINBASE_MATURITY = 100


def assert_wallet_roundtrip(node, block_amount=0):
    """Create a wallet, mine past maturity, assert the matured balance + UTXOs"""
    client = node.client
    assert client.get_blockchain_info()["chain"] == "regtest"
    LOG.debug(client.get_block_count())
    assert client.get_block_count() == block_amount

    try:
        client.create_wallet("bornal-wallet")
    except ClientError as exc:
        raise AssertionError(
            "createwallet failed — was bitcoind built without wallet support? "
            "run with --wallet (%s)" % exc
        ) from exc
    address = client.get_new_address()

    blocks = COINBASE_MATURITY + 1
    client.generate_to_address(blocks, address)
    assert client.get_block_count() == blocks

    assert client.get_balance() == COINBASE_SUBSIDY

    unspent = client.list_unspent()
    assert len(unspent) >= 1
    assert any(utxo["address"] == address for utxo in unspent)
