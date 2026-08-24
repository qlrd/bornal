"""Example bornal integration test with electrs indexing a bitcoin-core backend.

- ``test_electrs_via_fixture`` — the ready-made ``bitcoin_electrs_backend``
  fixture that starts electrs on top of a mined regtest bitcoind;
- ``test_electrs_indexes_mined_blocks`` — compose the stack yourself with the
  ``backend`` factory fixture. Could be bitcoind (the only for now) or another.

Run it through the bornal pytest plugin, which builds bitcoind and electrs on
demand. No ``--wallet`` needed: blocks are mined to a fixed unspendable
address:

    pytest --build-bitcoin latest --build-electrs latest examples/test_electrs_index.py

This example runs without class definitions and this is used to show some kind
of versatility with bornal, that you could create tests with oriented object
style or fixtures style.
"""

import time

from bornal.client import ClientError
from bornal.daemon import free_port
from bornal.plugins.bitcoind import UNSPENDABLE_ADDRESS


def wait_for_height(client, height, timeout=30):
    """Poll the electrum server until its index reaches ``height``."""
    timeout = time.time() + timeout
    while time.time() < timeout:
        try:
            tip = client.get_tip()
            if tip["height"] >= height:
                return tip
        except ClientError:
            pass
        time.sleep(0.5)
    raise AssertionError("electrs index never reached height %d" % height)


def test_electrs(bitcoin_electrs_backend):
    client = bitcoin_electrs_backend.client
    version = client.server_version()
    assert version[0].startswith("electrs/")
    assert version[1] == "1.4"
    tip = wait_for_height(client, 1)
    assert client.block_header(tip["height"])


def test_electrs_indexes(backend):
    btc = backend("bitcoin-core", p2p_port=free_port())
    start = btc.client.get_block_count()
    btc.client.generate_to_address(5, UNSPENDABLE_ADDRESS)
    electrs = backend("electrs", bitcoind=btc.daemon)
    tip = wait_for_height(electrs.client, start + 5)
    assert tip["height"] == start + 5
    assert electrs.client.block_header(0)  # the genesis header is indexed too
