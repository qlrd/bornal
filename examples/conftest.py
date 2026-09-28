import pytest

from bornal.daemon import free_port
from bornal.node import IntegrationTest


class BaseTest(IntegrationTest):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.state: dict = {}

    def set_test_params(self):
        self.add_backend("bitcoin-core", p2p_port=free_port())
        self.add_backend("bitcoin-core", p2p_port=free_port())

        # bind electrs to last core
        self.add_backend("electrs")

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
def bob_electrs(integration_test):
    return integration_test.backends[2]


@pytest.fixture
def state(integration_test):
    return integration_test.state
