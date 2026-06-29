import os
from abc import ABC, abstractmethod

from .cli import CliError
from .daemon import get
from .logger import LOG

__all__ = [
    "IntegrationTest",
    "Node",
    "env_binaries_dir",
    "env_data_dir",
    "make_node",
]


def env_binaries_dir():
    """Binaries dir from the run env"""
    return os.environ.get("BINARIES_DIR") or os.path.join(
        os.environ["INTEGRATION_TEMP_DIR"], "binaries"
    )


def env_data_dir():
    """Per-node data dir from the run env"""
    return os.path.join(os.environ["INTEGRATION_TEMP_DIR"], "data")


class Node:
    """A started daemon plus the ``Cli`` to talk to it"""

    def __init__(self, daemon, cli=None, log=None):
        self.daemon = daemon
        self.cli = cli or daemon.make_cli()
        self._log = log or LOG

    def start(self):
        self.daemon.start()
        self.cli.wait_until_up()
        self._log.debug("node '%s' up at %s", self.daemon.binary_name, self.cli.url)
        return self

    def stop(self):
        try:
            self.cli.call("stop")
        except CliError:
            pass
        self.daemon.stop()
        return self


def make_node(name, binaries_dir, datadir, log=None, extra_args=(), network="regtest"):
    """Build a ``Node`` for the installed plugin ``name`` (not started)"""
    plugin = get(name)
    if plugin.daemon_class is None:
        raise ValueError("plugin '%s' has no daemon to run" % name)
    daemon = plugin.daemon_class(
        binaries_dir=binaries_dir,
        datadir=datadir,
        log=log,
        extra_args=extra_args,
        network=network,
    )
    return Node(daemon, log=log)


class IntegrationTest(ABC):
    """Reusable ABC for an bornal integration test.

    - implement ``set_test_params()`` — declare nodes via ``self.add_node(name)``;
    - implement ``run_test()`` — assert against ``self.nodes`` (already started).

    ``main()`` drives the lifecycle: set params -> start nodes -> run_test ->
    stop (every node is stopped, even on failure).
    """

    def __init__(self, binaries_dir=None, data_dir=None, log=None):
        self._binaries_dir = binaries_dir or env_binaries_dir()
        self._data_dir = data_dir or env_data_dir()
        self._log = log or LOG
        self._declared = []
        self.nodes = []

    @property
    def log(self):
        return self._log

    def add_node(self, name, extra_args=()):
        """Declare a node to start"""
        self._declared.append((name, list(extra_args)))

    @abstractmethod
    def set_test_params(self):
        """Declare the nodes for this test"""

    @abstractmethod
    def run_test(self):
        """Run assertions against ``self.nodes``"""

    def setup_nodes(self):
        """Start every declared node and expose them as ``self.nodes``."""
        for index, (name, extra_args) in enumerate(self._declared):
            datadir = os.path.join(self._data_dir, "%s%d" % (name, index))
            node = make_node(
                name, self._binaries_dir, datadir, log=self._log, extra_args=extra_args
            )
            node.start()
            self.nodes.append(node)

    def main(self):
        """set params / start nodes / run_test / stop"""
        self.set_test_params()
        self.setup_nodes()
        try:
            self.run_test()
        finally:
            for node in self.nodes:
                node.stop()
