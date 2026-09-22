"""Fixtures shared by the examples"""

import pytest

from bornal.daemon import free_port
from bornal.node import IntegrationTest


class BaseTest(IntegrationTest):
    """Two ``bitcoin-core`` regtest nodes listening on p2p and the tests will
    call ``backends[0]`` (could be an 'alice') and ``backends[1]`` (maybe a 'bob')
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.state: dict = {}
        self.localhost = "127.0.0.1"
        self.nodes = [
            {"daemon": "bitcoin-core", "p2p_port": free_port()},
            {"daemon": "bitcoin-core", "p2p_port": free_port()},
        ]

    def set_test_params(self):
        for node in self.nodes:
            self.log.info(
                f"Preparing '{node.get('daemon')}' ({self.localhost}:{node.get('p2p_port')})"
            )
            self.add_backend(node.get("daemon"), p2p_port=node.get("p2p_port"))

    def run_test(self):
        self.log.info("Tests running")

    def on_stop_test(self):
        self.log.info("Tests stopped")


@pytest.fixture(scope="module")
def test_factory(request):
    return BaseTest


@pytest.fixture
def alice(integration_test):
    return integration_test.backends[0]


@pytest.fixture
def bob(integration_test):
    return integration_test.backends[1]


@pytest.fixture
def state(integration_test):
    return integration_test.state
