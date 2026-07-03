import os
from subprocess import Popen, PIPE

from .logger import LOG, fail


def _exec(argv):
    """Run a ``git`` argv, returning trimmed stdout; exit non-zero with stderr."""
    LOG.debug("$ %s", " ".join(argv))
    process = Popen(argv, stdout=PIPE, stderr=PIPE, text=True)
    stdout, stderr = process.communicate()
    if process.returncode != 0:
        fail(stderr.strip() or "git command failed: %s" % " ".join(argv))
    LOG.debug("%s", stdout.strip())
    return stdout.strip()


class Git:
    """Thin wrapper around the ``git`` CLI."""

    def __init__(self, projpath: str):
        self._projpath = projpath

    @staticmethod
    def init(path, quiet=True):
        """Initialize a new repo at ``path``; return a ``Git`` bound to it."""
        argv = ["git", "init"]
        if quiet:
            argv.append("-q")
        argv.append(path)
        _exec(argv)
        return Git(path)

    @staticmethod
    def clone(repo, dest, branch=None, depth=None):
        """Clone ``repo`` into ``dest``"""
        argv = ["git", "clone"]
        if depth:
            argv += ["--depth", str(depth)]
        if branch:
            argv += ["--branch", branch]
        argv += [repo, dest]
        _exec(argv)
        return dest

    @staticmethod
    def ls_remote_tags(repo, pattern="*"):
        """Tag names in a remote ``repo`` matching ``pattern``"""
        out = _exec(["git", "ls-remote", "--tags", "--refs", repo, pattern])
        tags = []
        for line in out.splitlines():
            ref = line.split("\t")[-1]
            if ref.startswith("refs/tags/"):
                tags.append(ref[len("refs/tags/") :])
        return tags

    def _run(self, cmd, *args, **kwargs):
        flags = []
        for k, v in kwargs.items():
            if not v:
                continue
            flags.append("%s%s" % ("-" if len(k) < 2 else "--", k.replace("_", "-")))
            if not isinstance(v, bool):
                flags.append(str(v))
        git = os.path.join(self._projpath, ".git")
        prefix = ["git", "--git-dir", git, "--work-tree", self._projpath]
        return _exec([*prefix, cmd, *args, *flags])

    def add(self, *paths):
        """Stage ``paths`` for the next commit."""
        return self._run("add", *paths)

    def commit(self, message, quiet=True):
        """Create a commit carrying ``message`` (identity comes from the env)."""
        return self._run("commit", message=message, quiet=quiet)

    def log(self, oneline=True, L=""):
        commits: list[dict] = []
        for line in self._run("log", oneline=oneline, L=L).splitlines():
            if not line:
                continue
            if L and (line.startswith("diff ") or line[:1] in " +-@"):
                commits[-1]["diff"].append(line)
                continue
            commit, _, message = line.partition(" ")
            entry: dict = {"commit": commit, "message": message}
            if L:
                entry["diff"] = []
            commits.append(entry)
        return commits

    def tip(self):
        """Return the most recent commit (the tip) as a single dict, or None."""
        commits = self.log(oneline=True)
        return commits[0] if commits else None

    def revparse(self, show_toplevel=True):
        """Resolve the project's top-level dir via ``rev-parse``."""
        return self._run("rev-parse", show_toplevel=show_toplevel)

    def branch(self, show_current=False):
        """Query branches; with ``show_current`` return the checked-out branch."""
        return self._run("branch", show_current=show_current)
