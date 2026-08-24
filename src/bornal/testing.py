from .node import Backend
from .client import ClientError
from .logger import LOG

__all__ = [
    "COINBASE_MATURITY",
    "BASE_COINBASE_SUBSIDY",
    "assert_block_count",
    "assert_chain",
    "assert_wallet_roundtrip",
    "create_wallet",
    "generate_to_address",
]

BASE_COINBASE_SUBSIDY = 50
COINBASE_MATURITY = 100


def create_wallet(backend: Backend, name: str = "bornal-wallet"):
    """Create a wallet on given ``Backend``"""
    try:
        backend.client.create_wallet(name)
    except ClientError as exc:
        raise AssertionError(
            "createwallet failed — was bitcoind built without wallet support? "
            "run with --wallet (%s)" % exc
        ) from exc


def assert_chain(backend: Backend, chain: str = "regtest"):
    """Assert that the ``Backend`` is on correct chain"""
    info = backend.client.get_blockchain_info()["chain"]
    assert info == chain
    LOG.debug(info)


def assert_block_count(backend: Backend, count: int = 0):
    """Assert block count for given ``Backend``"""
    _count = backend.client.get_block_count()
    assert _count == count
    LOG.debug(_count)


def generate_to_address(backend: Backend, block_amount: int = 0):
    """Mine ``block_amount`` blocks to a fresh wallet address; return the
    address that received the coinbase"""
    try:
        address = backend.client.get_new_address()
    except ClientError as exc:
        raise AssertionError("getnewaddress failed: %s" % exc) from exc

    try:
        backend.client.generate_to_address(block_amount, address)
    except ClientError as exc:
        raise AssertionError(
            "generatetoaddress failed: {} wasn't able to generate to {}".format(
                backend, address
            )
        ) from exc

    return address


def assert_wallet_roundtrip(
    backend: Backend,
    name: str = "bornal-wallet",
    chain: str = "regtest",
    block_count: int = 0,
):
    """Create a wallet, mine past maturity, assert the matured balance + UTXOs"""
    assert_chain(backend, chain)
    assert_block_count(backend, block_count)

    create_wallet(backend, name)
    address = generate_to_address(backend, COINBASE_MATURITY + 1)

    assert_block_count(backend, block_count + COINBASE_MATURITY + 1)
    assert backend.client.get_balance() >= BASE_COINBASE_SUBSIDY

    unspent = backend.client.list_unspent()
    assert len(unspent) >= 1
    assert any(utxo["address"] == address for utxo in unspent)
