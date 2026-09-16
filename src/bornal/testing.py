import re
import time

from .node import Backend
from .client import ClientError
from .logger import LOG

__all__ = [
    "COINBASE_MATURITY",
    "BASE_COINBASE_SUBSIDY",
    "assert_block_count",
    "assert_chain",
    "assert_finalized",
    "assert_mempool_accepts",
    "assert_mempool_rejects",
    "assert_next_role",
    "assert_not_finalized",
    "assert_send_rawtx_accepts",
    "assert_send_rawtx_rejects",
    "assert_wallet_info",
    "assert_wallet_roundtrip",
    "connect_p2p",
    "create_wallet",
    "generate_to_address",
    "sync_blocks",
]

BASE_COINBASE_SUBSIDY = 50
COINBASE_MATURITY = 100


def connect_p2p(alice: Backend, bob: Backend, timeout: int = 30):
    """``addnode`` ``bob`` from ``alice`` (onetry) and wait for both to sync"""
    if bob.daemon.p2p_port is None:
        raise ValueError("'bob' has p2p disabled: no p2p_port")
    p2p_addr = f"{bob.daemon.host}:{bob.daemon.p2p_port}"
    res = alice.client.add_node(p2p_addr, "onetry")
    if res is not None:
        raise AssertionError(f"'addnode' response expected to be None, got {res}")
    sync_blocks(alice, bob, timeout)


def sync_blocks(alice: Backend, bob: Backend, timeout: int = 30):
    """Wait until ``alice`` and ``bob`` report the same block count"""
    die = time.monotonic() + timeout
    while time.monotonic() < die:
        if alice.client.get_block_count() == bob.client.get_block_count():
            return
        time.sleep(0.25)
    raise AssertionError(f"Nodes did not sync in {timeout}s")


def create_wallet(
    backend: Backend,
    name: str = "bornal-wallet",
    watchonly: bool = False,
    descriptors: list[dict] | None = None,
) -> dict:
    """Create a wallet on given ``Backend``, hot or watch-only"""
    if watchonly and not descriptors:
        raise ValueError("Watch-only wallet needs descriptors")

    try:
        res = backend.client.create_wallet(name, watchonly, watchonly)
    except ClientError as exc:
        raise AssertionError(
            "createwallet failed — was bitcoind built without wallet support? "
            "run with --wallet (%s)" % exc
        ) from exc
    if res["name"] != name:
        raise AssertionError(f"Expected wallet '{name}', got '{res.get('name')}'")

    if watchonly:
        imported = backend.client.import_descriptors(descriptors)
        failed = [r for r in imported if not r["success"]]
        if failed:
            raise AssertionError(f"importdescriptors failed: {failed}")
    return res


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
    balance = backend.client.get_balance()
    if not balance >= BASE_COINBASE_SUBSIDY:
        raise AssertionError(
            f"Balance should be at least {BASE_COINBASE_SUBSIDY}, got {balance}"
        )

    unspent = backend.client.list_unspent()
    if not len(unspent) >= 1:
        raise AssertionError(f"Client should have 1 or more UTXOs, got {len(unspent)}")

    if not any(utxo["address"] == address for utxo in unspent):
        raise AssertionError(f"Client should list any UTXO for '{address}', got None")

    wallets = backend.client.list_wallets()
    if name not in wallets:
        raise AssertionError(f"Client should create '{name}' wallet, got {wallets}")


def assert_finalized(backend: Backend, psbt: str) -> str:
    res = backend.client.finalize_psbt(psbt)
    if not res["complete"]:
        raise AssertionError(f"PSBT should be complete, got {res.get('complete')}")
    return res["hex"]


def assert_not_finalized(backend: Backend, psbt: str) -> str:
    res = backend.client.finalize_psbt(psbt)
    if res["complete"]:
        raise AssertionError(f"PSBT should not be complete, got {res.get('complete')}")
    return res["psbt"]


def assert_next_role(backend: Backend, psbt: str, role: str = "updater") -> dict:
    res = backend.client.analyze_psbt(psbt)
    if res["next"] != role:
        raise AssertionError(
            f"PSBT next role should be '{role}', got '{res.get('next')}'"
        )
    return res


def assert_mempool_accepts(backend: Backend, hextx: str) -> dict:
    (res,) = backend.client.test_mempool_accept([hextx])
    if not res["allowed"]:
        raise AssertionError(f"tx should be allowed, got {res.get('reject-reason')}")
    return res


def assert_mempool_rejects(
    backend: Backend,
    hextx: str,
    rejectreason: str = r"(mempool|mandatory)-script-verify-flag-failed",
) -> str:
    (res,) = backend.client.test_mempool_accept([hextx])
    if res["allowed"]:
        raise AssertionError(f"tx should not be allowed, got {res}")
    reason = res.get("reject-reason", "")
    if not re.search(rejectreason, reason):
        raise AssertionError(f"Rejection should match '{rejectreason}', got '{reason}'")
    return reason


def assert_send_rawtx_accepts(backend: Backend, hextx: str) -> str:
    try:
        return backend.client.send_raw_transaction(hextx)
    except ClientError as exc:
        raise AssertionError(f"tx should be broadcastable, got {exc}") from exc


def assert_send_rawtx_rejects(
    backend: Backend,
    hextx: str,
    rejectreason: str = r"(mempool|mandatory)-script-verify-flag-failed",
) -> str:
    try:
        txid = backend.client.send_raw_transaction(hextx)
    except ClientError as exc:
        if not re.search(rejectreason, str(exc)):
            raise AssertionError(
                f"Rejection should match '{rejectreason}', got '{exc}'"
            ) from exc
        return str(exc)
    raise AssertionError(f"tx should not be broadcastable, got txid {txid}")


def assert_wallet_info(backend, name: str = "bornal-wallet", watchonly: bool = False):
    res = backend.client.get_wallet_info()
    if res["walletname"] != name:
        raise AssertionError(f"Expected wallet '{name}', got '{res['walletname']}'")
    if res["private_keys_enabled"] == watchonly:
        kind = "watch-only" if watchonly else "hot"
        raise AssertionError(f"Expected a {kind} wallet, got {res}")
    if res["scanning"]:
        raise AssertionError(f"Wallet still scanning: {res['scanning']}")
