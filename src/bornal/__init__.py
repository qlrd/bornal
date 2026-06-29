from argparse import ArgumentParser

from .logger import set_verbose
from .paths import Paths
from .scaffold import DEFAULT_TEMPLATE, TEMPLATES, scaffold

DESC = "kit for bitcoin related integration test tools"

parser = ArgumentParser(prog="bornal", description=DESC)
parser.add_argument(
    "--proj-path",
    default=".",
    help="path inside the project under test (default: current dir)",
)
parser.add_argument(
    "--tmp-path",
    default=None,
    help="where to keep binaries/data/logs "
    "(default: $XDG_CACHE_HOME or ~/.cache, then bornal/<projname>)",
)
parser.add_argument(
    "-v",
    "--verbose",
    action="store_true",
    help="show the underlying commands being run",
)

_sub = parser.add_subparsers(dest="command", required=True)

_create = _sub.add_parser(
    "create", help="scaffold an example integration test into the project"
)
_create.add_argument(
    "feature",
    nargs="?",
    default=None,
    metavar="FEATURE",
    help="feature name -> tests/integration/test_<feature>.py (default: the daemon name)",
)
_create.add_argument(
    "--template",
    default=DEFAULT_TEMPLATE,
    metavar="NAME",
    help="which starter body to scaffold — one of: %s (default: %s)"
    % (", ".join(sorted(TEMPLATES)), DEFAULT_TEMPLATE),
)
_create.add_argument(
    "--force",
    action="store_true",
    help="overwrite an existing scaffolded test file",
)

_create.add_argument(
    "--copyright-holders",
    default="selfcustody",
    metavar="COPYRIGHT_HOLDERS",
    help="copyright holders to put on LICENSE at generated codes",
)


def main():
    args = parser.parse_args()
    set_verbose(args.verbose)
    paths = Paths(args.proj_path, temp_dir=args.tmp_path)
    if args.command == "create":
        scaffold(
            paths,
            feature=args.feature,
            template=args.template,
            copyright_holders=args.copyright_holders,
            force=args.force,
        )


if __name__ == "__main__":
    main()
