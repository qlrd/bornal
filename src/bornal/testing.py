from .cli import CliError

__all__ = ["COINBASE_MATURITY", "COINBASE_SUBSIDY", "assert_wallet_roundtrip"]

COINBASE_SUBSIDY = 50
COINBASE_MATURITY = 100


def assert_wallet_roundtrip(node, block_amount=0):
    """Create a wallet, mine past maturity, assert the matured balance + UTXOs"""
    cli = node.cli
    assert cli.get_blockchain_info()["chain"] == "regtest"
    print(cli.get_block_count())
    assert cli.get_block_count() == block_amount

    try:
        cli.create_wallet("bornal-wallet")
    except CliError as exc:
        raise AssertionError(
            "createwallet failed — was bitcoind built without wallet support? "
            "run with --wallet (%s)" % exc
        ) from exc
    address = cli.get_new_address()

    blocks = COINBASE_MATURITY + 1
    cli.generate_to_address(blocks, address)
    assert cli.get_block_count() == blocks

    assert cli.get_balance() == COINBASE_SUBSIDY

    unspent = cli.list_unspent()
    assert len(unspent) >= 1
    assert any(utxo["address"] == address for utxo in unspent)
