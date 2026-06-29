from shutil import which

from .logger import fail


def check_installed(*names):
    """Exit with a helpful message if any required tool is missing from PATH."""
    for name in names:
        if which(name) is None:
            fail("you must have %s installed to run those tests!", name)
