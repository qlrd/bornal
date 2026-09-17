"""Fixtures shared by the examples"""

import os

import pytest

from bornal.daemon import free_port
from bornal.node import env_data_dir, IntegrationTest, BackendError
from bornal.testing import COINBASE_MATURITY, create_wallet, generate_to_address


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

    # This a little kludge to mix the usage of classes and fixtures, so we
    # can create sessions of test, instead in each of one power on and power off
    # tests while keeping the possibilities of fixtures in pytest: ``_on_run_test``
    # starts the backends and the pytest functions are the test, so there is
    # nothing left for ``run_test`` to do.
    def run_test(self):
        pass


def _stop_all(tests):
    errors: list[Exception] = []
    for ps in tests.values():
        if ps["test"] is not None:
            try:
                ps["test"]._on_stop_test()
            except BackendError as exc:
                errors.append(exc)
            ps["test"] = None
    if errors:
        raise BackendError(f"{len(errors)} session(s) failed to stop", errors)


@pytest.fixture(scope="session")
def _running_tests():
    tests = {}
    yield tests
    _stop_all(tests)


@pytest.fixture
def base_test(_running_tests):
    def _start(tag: str, stop: bool = True):
        ps = _running_tests.setdefault(tag, {"test": None, "stop": stop})
        ps["stop"] = stop

        if ps["test"] is None:
            test: IntegrationTest = BaseTest(data_dir=os.path.join(env_data_dir(), tag))
            test._on_set_test_params()
            test._on_run_test()
            ps["test"] = test
        return ps["test"]

    yield _start

    _stop_all({tag: ps for tag, ps in _running_tests.items() if ps["stop"]})

