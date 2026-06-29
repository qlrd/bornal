import logging

LOG = logging.getLogger("bornal")

if not LOG.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("[bornal] %(levelname)s: %(message)s"))
    LOG.addHandler(_handler)
    LOG.setLevel(logging.INFO)


def set_verbose(verbose):
    """Show DEBUG-level chatter when verbose"""
    LOG.setLevel(logging.DEBUG if verbose else logging.INFO)


def fail(msg, *args):
    """Log an error and exit non-zero"""
    LOG.error(msg, *args)
    raise SystemExit(1)
