"""bornal as a pytest 2nd layer.

Registers a pytest plugin (see pyproject ``pytest11``), so any test — bornal's
own or a downstream project's — receives its fixtures by argument name without a
conftest or ``pytest_plugins``: just install bornal, like installing pytest.

The run phase that ``bornal run`` used to do is now opt-in through pytest flags
contributed by the daemon plugins. Passing a per-daemon ``--build-<name>``
(e.g. ``--build-bitcoin 30.2`` or ``--build-bitcoin latest``) builds that daemon
on demand, wipes ``data/``/``logs/`` (unless ``--preserve-data``) and exports
``INTEGRATION_TEMP_DIR`` (plus ``BINARIES_DIR`` and each daemon's own env); the
fixtures then discover the built binaries and a clean data dir from there.
Without any ``--build-<name>`` the plugin only contributes its fixtures, so
plain ``pytest`` never triggers a build.
"""

import contextlib
import os

import pytest

from . import daemon
from .logger import LOG, set_verbose
from .node import env_binaries_dir, env_data_dir, make_node
from .paths import Paths
from .prepare import ensure_daemons


def _build_dest(name):
    """dest for a daemon's ``--build-<name>`` option"""
    return "bornal_build_%s" % name.replace("-", "_")


def pytest_addoption(parser):
    """Register bornal's run options, including one ``--build-<name>`` per daemon."""
    group = parser.getgroup("bornal", "bornal integration-test run options")
    group.addoption(
        "--wallet",
        action="store_true",
        default=False,
        dest="bornal_wallet",
        help="build the daemon(s) with wallet support",
    )
    group.addoption(
        "--force-build",
        action="store_true",
        default=False,
        dest="bornal_force_build",
        help="rebuild daemon(s) even if already present",
    )
    group.addoption(
        "--nproc",
        type=int,
        default=None,
        dest="bornal_nproc",
        metavar="N",
        help="CPU cores to compile daemon(s) with — the build's -j; an explicit "
        "value wins over $BUILD_BITCOIND_NPROCS (default: that env var, else 4)",
    )
    group.addoption(
        "--preserve-data",
        action="store_true",
        default=False,
        dest="bornal_preserve_data",
        help="keep the data and logs dirs instead of wiping them",
    )
    group.addoption(
        "--proj-path",
        default=".",
        dest="bornal_proj_path",
        help="path inside the project under test (default: current dir)",
    )
    group.addoption(
        "--tmp-path",
        default=None,
        dest="bornal_tmp_path",
        help="where to keep binaries/data/logs "
        "(default: $XDG_CACHE_HOME or ~/.cache, then bornal/<projname>)",
    )
    for name in daemon.names():
        group.addoption(
            daemon.build_flag_for(name),
            default=None,
            dest=_build_dest(name),
            metavar="VERSION",
            help="build %s at VERSION (or 'latest') and run the tests" % name,
        )


def _selected_builds(config):
    """Map daemon-name for requested revision for each ``--build-<name>`` passed"""
    selected = {}
    for name in daemon.names():
        revision = config.getoption(_build_dest(name))
        if revision is not None:
            selected[name] = revision
    return selected


def pytest_configure(config):
    """Run the build phase before collection when a ``--build-<name>`` is passed"""
    selected = _selected_builds(config)
    if selected:
        prepare_run(config, selected)


def _export_env(paths):
    """Export the discovery env the fixtures/ABC read to find the binaries"""
    os.environ["BINARIES_DIR"] = paths.binaries_dir
    os.environ["INTEGRATION_TEMP_DIR"] = paths.temp_dir
    for plugin in daemon.registry().values():
        os.environ.update(plugin.env(paths))


def prepare_run(config, selected):
    """Build the selected daemons, clean state, expose the binaries via the env."""
    set_verbose(bool(config.getoption("verbose", default=0)))
    paths = Paths(
        config.getoption("bornal_proj_path"),
        temp_dir=config.getoption("bornal_tmp_path"),
    )
    wallet = config.getoption("bornal_wallet")
    build = {"wallet": wallet}
    nproc = config.getoption("bornal_nproc")
    if nproc is not None:
        build["n_proc"] = nproc
    options = {
        name: {**build, "revision": revision} for name, revision in selected.items()
    }
    ensure_daemons(
        paths,
        daemons=list(selected),
        force=config.getoption("bornal_force_build"),
        options=options,
    )

    if not config.getoption("bornal_preserve_data"):
        LOG.info("cleaning up test directories before running tests...")
        paths.reset_state()

    _export_env(paths)
    return paths


@contextlib.contextmanager
def _started_node(name, index=0, extra_args=()):
    datadir = os.path.join(env_data_dir(), "%s%d" % (name, index))
    node = make_node(name, env_binaries_dir(), datadir, extra_args=extra_args)
    try:
        node.start()
        yield node
    finally:
        node.stop()


@pytest.fixture
def node():
    """start a plugin node by name; stop it on teardown"""
    opened = []

    def _open(name, extra_args=()):
        manager = _started_node(name, index=len(opened), extra_args=extra_args)
        started = manager.__enter__()
        opened.append(manager)
        return started

    yield _open

    for manager in reversed(opened):
        manager.__exit__(None, None, None)


@pytest.fixture
def bitcoind_node(node):
    """A started bitcoind (regtest) node, ready for RPC"""
    return node("bitcoin-core")
