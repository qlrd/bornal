import os
import json
import socket
import subprocess
import shutil
from abc import ABC, abstractmethod
from importlib.metadata import entry_points

from .git import Git
from .logger import LOG, fail

__all__ = [
    "Compiler",
    "CompilerError",
    "Daemon",
    "ENTRY_POINT_GROUP",
    "abort",
    "build_flag_for",
    "free_port",
    "get",
    "names",
    "registry",
    "run",
]

ENTRY_POINT_GROUP = "bornal.daemons"


class CompilerError(ExceptionGroup):
    def derive(self, excs):
        return CompilerError(self.message, excs)


def run(argv, cwd=None, env=None):
    LOG.debug("$ %s", " ".join(argv))
    process = subprocess.run(argv, cwd=cwd, env=env)
    if process.returncode != 0:
        message = f"command '{' '.join(argv)}' exited with code {process.returncode}"
        raise CompilerError("Failed to compile", [Exception(message)])


def abort(exc):
    for cause in exc.exceptions:
        LOG.error(cause)
    fail(exc.message)


# Plugins subclass this and register via the ``bornal.daemons`` entry-point.
# ``bornal`` stays agnostic: it never imports a compiler directly, it only
# discovers whatever plugins are installed.
class Compiler(ABC):
    """Compiles a bitcoin daemon binary from source."""

    name = ""
    """Plugin related compiler name"""

    daemon_class = None
    """``Daemon``` class to be bind"""

    build_flag = None
    """
    pytest option this plugin contributes (e.g. ``--build-bitcoin``);
    when left ``None`` it is derived as ``--build-<name>`` (see ``build_flag_for``).
    """

    repo = None
    """Some given abstract project to be compiled."""

    binary_name = None
    """Some given binary that the project compiles to."""

    build_meta = None
    """Metadata for built cache"""

    @abstractmethod
    # Extra ``options`` are compiler-specific; ignore the ones you don't know
    # (accept ``**_``)
    def ensure(self, paths, *, force=False, **options) -> str:
        """Make the compiled binary available under ``paths.binaries_dir``."""

    @staticmethod
    def git_ref(rev):
        return f"v{rev}" if rev[:1].isdigit() else rev

    def _depends_on(self, attr):
        val = getattr(self, attr)
        if val is None:
            raise AttributeError(f"'{attr}' not set on {type(self).__name__}")
        return val

    def check_compiler(self, *build_deps):
        """Check if build deps are correct before build."""
        if any(shutil.which(dep) for dep in build_deps):
            return
        causes = [Exception(f"'{dep}' not found on PATH'") for dep in build_deps]
        msg = f"{self.name} needs at least on of: " + ", ".join(build_deps)
        raise CompilerError(msg, causes)

    def env(self, paths):
        """Env vars this compiler contributes to the test run (name -> value)."""
        if self.binary_name is None:
            raise ValueError(f"Binary name is not on {type(self).__name__}")
        binary_key = self.binary_name.upper()
        binary_val = self.dest(paths)
        prefix = self.name.upper().replace("-", "_")

        # derive envs by name like
        # <BINARY_NAME> will be under ``paths.binaries_dir``
        # <NAME>_PATH will be ``paths.binaries_dir``
        return {
            binary_key: binary_val,
            f"{prefix}_PATH": paths.binaries_dir,
        }

    def dest(self, paths) -> str:
        return os.path.join(paths.binaries_dir, self._depends_on("binary_name"))

    def on_path(self):
        if self.binary_name is None:
            raise ValueError(f"Binary name is not on '{type(self).__name__}'")
        return shutil.which(self._depends_on("binary_name"))

    def install(self, paths, built):
        """Copy compiled into cached daemons"""
        os.makedirs(paths.binaries_dir, exist_ok=True)
        output = self.dest(paths)
        shutil.copy(built, output)
        os.chmod(output, 0o755)

    def get_latest_revision(self):
        versions = []
        for tag in Git.ls_remote_tags(self.repo, "v[0-9]*"):
            parts = tag.lstrip("v").split(".")
            if parts and all(p.isdigit() for p in parts):
                versions.append(tuple(int(p) for p in parts))
        if not versions:
            fail("unable to determine 'latest' for %s", self.name)
        return ".".join(str(p) for p in max(versions))

    def resolve_revision(self, rev):
        if rev in (None, "", "latest"):
            return self.get_latest_revision()
        return rev

    def build_meta_path(self, paths):
        return os.path.join(paths.binaries_dir, self._depends_on("build_meta"))

    def read_build_meta(self, paths):
        """How the cached bitcoind was built, or ``None`` if unknown/missing."""
        try:
            with open(self.build_meta_path(paths)) as f:
                return json.load(f)

        except (OSError, ValueError):
            return None

    def write_build_meta(self, paths, meta):
        """Record how the cached bitcoind was built"""
        with open(self.build_meta_path(paths), "w") as f:
            json.dump(meta, f)


def free_port():
    """Unused local TCP port"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class Daemon(ABC):
    """A running daemon, launched from a compiled or pre-built binary."""

    client_class = None
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

    def make_client(self):
        """A ``Client`` wired to this daemon's RPC endpoint."""
        if self.client_class is None:
            raise NotImplementedError("%s has no client_class" % type(self).__name__)
        return self.client_class(
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
