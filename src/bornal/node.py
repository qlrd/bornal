import os
from abc import ABC, abstractmethod

from .client import ClientError
from .daemon import get
from .logger import LOG

__all__ = [
    "IntegrationTest",
    "Backend",
    "env_binaries_dir",
    "env_data_dir",
    "make_backend",
]


def env_binaries_dir():
    """Binaries dir from the run env"""
    return os.environ.get("BINARIES_DIR") or os.path.join(
        os.environ["INTEGRATION_TEMP_DIR"], "binaries"
    )


def env_data_dir():
    """Per-node data dir from the run env"""
    return os.path.join(os.environ["INTEGRATION_TEMP_DIR"], "data")


class Backend:
    """A ``Daemon`` plus the ``Client`` to talk to it"""

    def __init__(self, daemon, client=None, log=None):
        self.daemon = daemon
        self.client = client or daemon.make_client()
        self._log = log or LOG

    def start(self):
        self.daemon.start()
        self.client.wait_until_up()
        self._log.debug(
            "backend '%s' up at %s", self.daemon.binary_name, self.client.url
        )
        return self

    def stop(self):
        try:
            self.client.call("stop")
        except ClientError:
            pass
        self.daemon.stop()
        return self


def make_backend(
    name,
    binaries_dir,
    datadir,
    log=None,
    extra_args=(),
    network="regtest",
    **kwargs,
):
    """Build a ``Backend`` for the installed plugin ``name`` (not started)."""
    plugin = get(name)
    if plugin.daemon_class is None:
        raise ValueError("plugin '%s' has no daemon to run" % name)
    daemon = plugin.daemon_class(
        binaries_dir=binaries_dir,
        datadir=datadir,
        log=log,
        extra_args=extra_args,
        network=network,
        **kwargs,
    )
    return Backend(daemon, log=log)


class IntegrationTest(ABC):
    """Reusable ABC for an bornal integration test.

    - implement ``set_test_params()`` — declare backends via ``self.add_backend(name)``;
    - implement ``run_test()`` — assert against ``self.backends`` (already started).

    ``main()`` lifecycle:

    - set params
    - start backends
    - run_test
    - stop (every backend is stopped, even on failure).
    """

    def __init__(self, binaries_dir=None, data_dir=None, log=None):
        self._binaries_dir = binaries_dir or env_binaries_dir()
        self._data_dir = data_dir or env_data_dir()
        self._log = log or LOG
        self._declared = []
        self.backends = []

    @property
    def log(self):
        return self._log

    def add_backend(self, name, extra_args=()):
        """Declare a backend to start"""
        self._declared.append((name, list(extra_args)))

    @abstractmethod
    def set_test_params(self):
        """Declare the backends for this test"""

    @abstractmethod
    def run_test(self):
        """Run assertions against ``self.backends``"""

    def setup_backends(self):
        """Start every declared backend and expose them as ``self.backends``."""
        for index, (name, extra_args) in enumerate(self._declared):
            datadir = os.path.join(self._data_dir, "%s%d" % (name, index))
            node = make_backend(
                name, self._binaries_dir, datadir, log=self._log, extra_args=extra_args
            )
            node.start()
            self.backends.append(node)

    def main(self):
        """set params / start backends / run_test / stop"""
        self.set_test_params()
        self.setup_backends()
        try:
            self.run_test()
        finally:
            for node in self.backends:
                node.stop()
