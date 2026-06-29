"""Example bornal integration test: a bitcoin-core wallet roundtrip.

- ``BitcoindWalletTest`` — the reusable ``IntegrationTest`` ABC;
- ``test_bitcoind_wallet_via_fixture`` — the ``bitcoind_node`` fixture.

Run it through the bornal pytest plugin, which builds bitcoind on demand and
exports ``INTEGRATION_TEMP_DIR``.

This test creates a wallet, so bitcoind must be built **with wallet support**
(``--wallet``):

    pytest --build-bitcoin latest --wallet examples/test_bitcoind_wallet.py
"""

from bornal.node import IntegrationTest
from bornal.testing import assert_wallet_roundtrip


class BitcoindWalletTest(IntegrationTest):
    """Mine to a fresh wallet and assert the matured balance + UTXOs."""

    def set_test_params(self):
        self.add_node("bitcoin-core")

    def run_test(self):
        assert_wallet_roundtrip(self.nodes[0], 0)
        self.log.info("wallet roundtrip OK")


def test_bitcoind_wallet():
    """ABC style: dirs default from INTEGRATION_TEMP_DIR."""
    BitcoindWalletTest().main()
