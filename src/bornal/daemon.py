import os
import socket
import subprocess
from abc import ABC, abstractmethod
from importlib.metadata import entry_points

from .logger import LOG, fail

__all__ = [
    "Compiler",
    "Daemon",
    "ENTRY_POINT_GROUP",
    "build_flag_for",
    "free_port",
    "get",
    "names",
    "registry",
]

ENTRY_POINT_GROUP = "bornal.daemons"


# Plugins subclass this and register via the ``bornal.daemons`` entry-point.
# ``bornal`` stays agnostic: it never imports a compiler directly, it only
# discovers whatever plugins are installed.
class Compiler(ABC):
    """Compiles a bitcoin daemon binary from source (no external cli)."""

    name = ""
    """Plugin related compiler name"""

    daemon_class = None
    """``Daemon``` class to be bind"""

    build_flag = None
    """
    pytest option this plugin contributes (e.g. ``--build-bitcoin``);
    when left ``None`` it is derived as ``--build-<name>`` (see ``build_flag_for``).
    """

    @abstractmethod
    # Extra ``options`` are compiler-specific; ignore the ones you don't know
    # (accept ``**_``)
    def ensure(self, paths, *, force=False, **options) -> str:
        """Make the compiled binary available under ``paths.binaries_dir``."""

    # This is the project's discovery in some``tests/integration`` (and
    # the framework it uses) read these to locate the binaries.
    def env(self, paths):
        """Env vars this compiler contributes to the test run (name -> value)."""
        return {}


def free_port():
    """Unused local TCP port"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class Daemon(ABC):
    """A running daemon, launched from a compiled or pre-built binary."""

    cli_class = None
    rpc_user = None
    rpc_password = None

    def __init__(
        self,
        binaries_dir,
        datadir,
        host="127.0.0.1",
        port=None,
        log=None,
        extra_args=(),
        network="regtest",
    ):
        self._binaries_dir = binaries_dir
        self._datadir = datadir
        self._host = host
        self._port = port or free_port()
        self._extra_args = list(extra_args)
        self._network = network
        self._log = log or LOG
        self._process = None

    @property
    @abstractmethod
    def binary_name(self) -> str:
        """Executable name under the binaries dir (e.g. ``"bitcoind"``)."""

    @abstractmethod
    def args(self) -> list:
        """Process arguments"""

    @property
    def binary(self) -> str:
        return os.path.join(self._binaries_dir, self.binary_name)

    @property
    def datadir(self) -> str:
        return self._datadir

    @property
    def network(self) -> str:
        return self._network

    @property
    def host(self) -> str:
        return self._host

    @property
    def port(self) -> int:
        return self._port

    @property
    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def make_cli(self):
        """A ``Cli`` wired to this daemon's RPC endpoint."""
        if self.cli_class is None:
            raise NotImplementedError("%s has no cli_class" % type(self).__name__)
        return self.cli_class(
            host=self._host,
            port=self._port,
            user=self.rpc_user,
            password=self.rpc_password,
            log=self._log,
        )

    def start(self):
        if self.is_running:
            raise RuntimeError("%s already running" % self.binary_name)
        os.makedirs(self._datadir, exist_ok=True)
        argv = [self.binary, *self.args(), *self._extra_args]
        self._log.debug("$ %s", " ".join(argv))
        self._process = subprocess.Popen(argv)
        return self

    def stop(self, timeout=30):
        if self._process is None:
            return
        if self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait()
        self._process = None


def registry():
    """Discover installed daemon plugins"""
    found = {}
    for ep in entry_points(group=ENTRY_POINT_GROUP):
        daemon = ep.load()()
        found[daemon.name or ep.name] = daemon
    return found


def names():
    return sorted(registry())


def get(name):
    daemons = registry()
    if name not in daemons:
        known = ", ".join(sorted(daemons)) or "(none installed)"
        fail("unknown daemon '%s' — known: %s", name, known)
    return daemons[name]


def build_flag_for(name):
    """The pytest build option a daemon plugin contributes"""
    plugin = registry().get(name)
    flag = getattr(plugin, "build_flag", None) if plugin else None
    return flag or "--build-%s" % name
