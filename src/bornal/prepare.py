from . import daemon
from .deps import check_installed
from .logger import LOG


def ensure_daemons(paths, daemons=None, force=False, options=None):
    """Build/obtain the selected daemons into the binaries cache"""
    check_installed("git")
    paths.ensure()

    selected = daemons or daemon.names()
    options = options or {}
    for name in selected:
        daemon.get(name).ensure(paths, force=force, **options.get(name, {}))

    LOG.info("daemons ready at %s", paths.binaries_dir)
    return paths.binaries_dir
