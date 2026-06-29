import os
import shutil

from .git import Git


class Paths:
    """Filesystem layout for an bornal test run, derived from the project root.
    The project's own integration tests live at ``<proj>/tests/integration``
    """

    def __init__(self, projpath, temp_dir=None):
        self.proj_dir = Git(os.path.abspath(projpath)).revparse(show_toplevel=True)
        self.proj_name = os.path.basename(self.proj_dir)
        cache = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
        self.temp_dir = (
            temp_dir
            or os.environ.get("BORNAL_TEMP_DIR")
            or os.path.join(cache, "bornal", self.proj_name)
        )
        self.binaries_dir = os.path.join(self.temp_dir, "binaries")
        self.data_dir = os.path.join(self.temp_dir, "data")
        self.logs_dir = os.path.join(self.temp_dir, "logs")
        self.integration_dir = os.path.join(self.proj_dir, "tests", "integration")

    def ensure(self):
        """Create the binaries dir"""
        os.makedirs(self.binaries_dir, exist_ok=True)
        return self

    def reset_state(self):
        """Provide empty data/ and logs/ dirs for a clean test run"""
        for d in (self.data_dir, self.logs_dir):
            shutil.rmtree(d, ignore_errors=True)
            os.makedirs(d, exist_ok=True)
        return self
