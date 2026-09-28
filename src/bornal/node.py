import os
from abc import ABC, abstractmethod

from .client import Client
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

    - set params and build the backends (``_on_set_test_params()``)
    - start backends, then run_test (``_on_run_test()``)
    - on_stop_test (optional hook: assertions before the backends go down),
      then stop (``_on_stop_test()``: every backend is stopped, even on failure).

    A session could be used so that keeps the backends up across several tests
    (see ``examples/conftest.py``) calls the same three steps itself,
    with a no-op ``run_test``, allowing multiple and small tests on a file,
    but in practice are only one.
    """

    def __init__(self, binaries_dir=None, data_dir=None, log=None):
        self._binaries_dir = binaries_dir or env_binaries_dir()
        self._data_dir = data_dir or env_data_dir()
        self._log = log or LOG
        self._declared = []
        self._backends: list[Backend] = []
        self._localhost = "127.0.0.1"

    @property
    def log(self):
        return self._log

    @property
    def declared(self):
        return self._declared

    @property
    def backends(self):
        return self._backends

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

    def on_stop_test(self):
        """Run assertions before stopping ``self.backends`` (optional hook)"""
        pass

    def _on_set_test_params(self):
        self.set_test_params()
        for index, (name, kwargs) in enumerate(self._declared):
            _datadir = os.path.join(self._data_dir, "%s%d" % (name, index))
            if name == "electrs":
                # test could use his own "bitcoin" impl backend to use with
                # electrs. A smooth strategy to manage many backends is to use
                # already declared bitcoin imple and shift its index on backends
                # and `add_backend("electrs")` need a previous `add_backend("bitcoin-core")`
                kwargs = dict(kwargs)
                i = kwargs.pop("backend", -1)
                bitcoin_impl = self.backends[i] if self.backends else None
                if bitcoin_impl is None:
                    raise ValueError("Bitcoin implementation cannot be None")
                if bitcoin_impl.daemon.binary_name != "bitcoind":
                    raise ValueError(
                        f"Bornal do not support yet electrs+{bitcoin_impl.daemon.binary_name}"
                    )
                node = make_backend(
                    "electrs", self._binaries_dir, _datadir, self._log, **kwargs
                )
                node.daemon.attach_bitcoind(bitcoin_impl.daemon)
            else:
                # any other installed plugin; an unknown name fails in the registry
                node = make_backend(
                    name, self._binaries_dir, _datadir, self._log, **kwargs
                )
            self.backends.append(node)

    def _on_run_test(self):
        """Start every backend then run `run_test`; if either raises, stop ones
        already up and re-raise"""
        try:
            # a bitcoin impl is up before the electrs on it
            for node in self.backends:
                node.start()
            self.run_test()
        except BaseException:
            self._on_stop_test()
            raise

    def _on_stop_test(self):
        """``on_stop_test`` hook, then stop every backend (lifo) even if the hook
        raises; one ``BackendError`` groups every stop failure. A no-op once the
        backends are down, so a failed start does not run the hook twice"""
        if not self.backends:
            return
        try:
            self.on_stop_test()
        finally:
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
            self._backends = []
            if errors:
                raise BackendError(f"{len(errors)} backend(s) failed to stop", errors)

    def main(self):
        """Main cyle: set params / start backends / run_test / on_stop_test / stop"""
        self._on_set_test_params()
        try:
            self._on_run_test()
        finally:
            self._on_stop_test()
