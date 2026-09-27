"""Command-line entry point for Pagewatch."""

import argparse
from collections.abc import Sequence
from importlib.metadata import version


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="pagewatch",
        description="Monitor meaningful changes on web pages (not implemented yet).",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {version('pagewatch-ai')}",
    )
    parser.parse_args(argv)
    parser.error("monitoring is not implemented yet")
