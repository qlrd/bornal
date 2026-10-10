import os
import tempfile

from ..client import ElectrumClient
from ..daemon import Compiler, CompilerError, Daemon, abort, free_port, run
from ..deps import check_installed
from ..git import Git
from ..logger import LOG

__all__ = ["ElectrsClient", "ElectrsCompiler", "ElectrsDaemon"]

_NAME = "electrs"
_REPO = "https://github.com/romanz/electrs"
_BUILD_META = "electrs.build.json"
_CONF_NAME = "electrs.toml"


def _build_env():
    env = os.environ.copy()
    env["CXXFLAGS"] = ("%s -include cstdint" % env.get("CXXFLAGS", "")).strip()
    return env


class ElectrsCompiler(Compiler):
    """Builds electrs with cargo. ``--nproc`` is ignored."""

    @property
    def binary_name(self):
        return _NAME

    @property
    def build_meta(self):
        return _BUILD_META

    @property
    def name(self):
        return _NAME

    @property
    def repo(self):
        return _REPO

    def ensure(self, paths, *args, force=False, revision=None, **kwargs) -> str:
        dest = self.dest(paths)
        wanted = {"revision": revision or "latest"}
        wants_specific = revision is not None

        if os.path.exists(dest) and not force:
            if not wants_specific or self.read_build_meta(paths) == wanted:
                LOG.info("%s matching build, skip it", self.name)
                return dest
            LOG.info("%s rebuilding", self.name)
        elif not (force or wants_specific):
            found = self.on_path()
            if found:
                LOG.info("electrs on PATH: %s", found)
                self.install(paths, found)
                self.write_build_meta(paths, {"revision": "path"})
                return dest

        check_installed("git", "cargo", "clang")
        revision = self.resolve_revision(revision)

        try:
            with tempfile.TemporaryDirectory() as workdir:
                src = os.path.join(workdir, "electrs")

                LOG.info(f"cloning {self.name} {self.git_ref(revision)}")
                Git.clone(_REPO, src, branch=self.git_ref(revision), depth=1)

                LOG.info(f"building {self.name}")
                run(
                    ["cargo", "build", "--locked", "--release"],
                    cwd=src,
                    env=_build_env(),
                )

                self.install(paths, os.path.join(src, "target", "release", "electrs"))
        except CompilerError as exc:
            abort(exc)
        self.write_build_meta(paths, wanted)
        LOG.info(f"{self.name} built at {paths.binaries_dir}")
        LOG.info(
            f"reuse it elsewhere with:\n\texport PATH={paths.binaries_dir}:$PATH\n\n"
        )
        return dest


class ElectrsClient(ElectrumClient):
    """Electrum client for electrs"""

    @property
    def name(self):
        return _NAME

    def server_version(self, protocol="1.4"):
        return self.call("server.version", "electrs", protocol)


class ElectrsDaemon(Daemon):
    """Runs ``electrs`` on top of a running bitcoind (other implementations are
    not supported yet; florestad ships its own Electrum server, see
    ``bornal.plugins.floresta``), configured through a generated
    ``electrs.toml``."""

    @property
    def name(self):
        return _NAME

    @property
    def client_class(self):
        return ElectrsClient

    def __init__(self, *args, bitcoind=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._bitcoind = bitcoind
        # electrs' Prometheus metrics cannot be disabled: reserve a port so
        # parallel runs never collide on the default monitoring address.
        self._monitoring_port = free_port()

    @property
    def bitcoind(self):
        return self._bitcoind

    @property
    def binary_name(self) -> str:
        return "electrs"

    @property
    def monitoring_port(self) -> int:
        return self._monitoring_port

    @property
    def conf_file(self) -> str:
        return os.path.join(self.datadir, _CONF_NAME)

    def attach_bitcoind(self, bitcoind):
        """Point this electrs at a started ``BitcoindDaemon``"""
        self._bitcoind = bitcoind
        return self

    def _conf(self) -> str:
        backend = self._bitcoind
        if backend is None:
            raise RuntimeError(
                "electrs needs a bitcoind: pass bitcoind= or attach_bitcoind()"
            )
        lines = [
            'daemon_dir = "%s"' % backend.datadir,
            'auth = "%s:%s"' % (backend.rpc_user, backend.rpc_password),
            'daemon_rpc_addr = "%s:%d"' % (backend.host, backend.port),
            'db_dir = "%s"' % os.path.join(self.datadir, "db"),
            'network = "%s"' % self.network,
            'electrum_rpc_addr = "%s:%d"' % (self.host, self.port),
            'monitoring_addr = "%s:%d"' % (self.host, self._monitoring_port),
            'log_filters = "INFO"',
            # a fresh regtest chain reports IBD until its first block is mined
            # and electrs does not answer the electrum rpc while it waits
            "skip_block_download_wait = true",
        ]

        # Electrs >= 0.12 fetches blocks over bitcoind's rest api.
        # Older builds sync over p2p when offered
        if backend.p2p_port is not None:
            lines.append('daemon_p2p_addr = "%s:%d"' % (backend.host, backend.p2p_port))
        return "\n".join(lines) + "\n"

    def args(self) -> list:
        return ["--conf", self.conf_file]

    def start(self):
        os.makedirs(self.datadir, exist_ok=True)
        with open(self.conf_file, "w") as handle:
            handle.write(self._conf())
        return super().start()


setattr(ElectrsCompiler, "daemon_class", ElectrsDaemon)
