"""bornal as a pytest 2nd layer.
Override in a module or a conftest that returns an ``IntegrationTest subclass,
or any callable taking your data_dir``.
"""

import os
import pathlib
import pytest

from . import daemon
from .logger import LOG, set_verbose
from .node import (
    env_data_dir,
)
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


@pytest.fixture(scope="module")
def test_factory(request):
    """Need to be overrided on your own module."""
    pytest.fail(f"{request.module.__name__} defines no test_factory fixture.")


@pytest.fixture(scope="module")
def integration_test(request, test_factory):
    """
    This is a wrapper for custom IntegrationTest derived classes to be used on
    fixture style. You define a derived class on you <project>/conftest.py
    with proper setup and define you own overrides of ``test_factory``:

    ```python
    # on your conftest.py
    from bornal.node import IntegrationTest

    class SomeTest(IntegrationTest):

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
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

        def run_test(self):
            self.log.info("Tests running")

        def on_stop_test(self):
            self.log.info("Tests stopped")


    @pytest.fixture(scope="module")
    def test_factory(request):
        return SomeTest

    # on your tests files
    def test_001_my_test(integration_test):
        # Integration test is now available until all tests occurs
        alice, bob = integration_test.backends
        ...
    ```

    """
    test = test_factory(
        data_dir=os.path.join(
            env_data_dir(), pathlib.Path(request.module.__file__).stem
        )
    )
    test._on_set_test_params()
    test._on_run_test()
    yield test
    test._on_stop_test()
