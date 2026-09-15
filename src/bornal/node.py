import os
from abc import ABC, abstractmethod

from .client import Client, ClientError
from .daemon import get, Daemon
from .logger import LOG

__all__ = [
    "IntegrationTest",
    "BackendError",
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


class BackendError(ExceptionGroup):
    def derive(self, excs):
        return BackendError(self.message, excs)


class Backend:
    """A ``Daemon`` plus the ``Client`` to talk to it"""

    def __init__(self, daemon, client=None, log=None):
        self.daemon: Daemon = daemon
        self.client: Client = client or daemon.make_client()
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
    name, binaries_dir, datadir, log=None, extra_args=(), network="regtest", **kwargs
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
        self.backends: list[Backend] = []

    @property
    def log(self):
        return self._log

    def add_backend(self, name, extra_args=(), **daemon_kwargs):
        """Declare a backend to start, ``extra_args`` is the raw argv and ``daemon_args``
        for the plugins (e.g., p2p_port for bitcoind, bitcoind for electrs, etc.)
        added with some default one (see ``bornal.daemon``, ``bornal.plugins.bitcoind``
        and ``bornal.plugins.electrs``"""
        self._declared.append((name, {"extra_args": list(extra_args), **daemon_kwargs}))

    @abstractmethod
    def set_test_params(self):
        """Declare the backends for this test"""

    @abstractmethod
    def run_test(self):
        """Run assertions against ``self.backends``"""

    def setup_backends(self):
        """Start every declared backend and expose them as ``self.backends``."""
        for index, (name, kwargs) in enumerate(self._declared):
            datadir = os.path.join(self._data_dir, "%s%d" % (name, index))
            node = make_backend(
                name, self._binaries_dir, datadir, log=self._log, **kwargs
            )
            node.start()
            self.backends.append(node)

    def stop_backends(self):
        """Stop every backend (lifo), then raise one ``BackendError`` grouping
        every failure"""
        errors: list[Exception] = []
        lifo = reversed(self.backends)
        for node in lifo:
            try:
                node.stop()
            except Exception as exc:
                exc.add_note(
                    f"while stopping {node.daemon.binary_name} at {node.client.url}: "
                    f"see {node.daemon.datadir}"
                )
                errors.append(exc)
        self.backends = []
        if errors:
            raise BackendError(f"{len(errors)} backend(s) failed to stop", errors)

    def main(self):
        """set params / start backends / run_test / stop"""
        self.set_test_params()
        self.setup_backends()
        try:
            self.run_test()
        finally:
            self.stop_backends()
