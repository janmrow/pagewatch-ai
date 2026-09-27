"""Command-line entry point for Pagewatch."""

import argparse
import sys
from collections.abc import Sequence
from importlib.metadata import version

from pagewatch.content import ContentError, fetch_text


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="pagewatch",
        description="Fetch and extract text from web pages.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {version('pagewatch-ai')}",
    )
    commands = parser.add_subparsers(dest="command")
    fetch = commands.add_parser("fetch", help="fetch text selected from one page")
    fetch.add_argument("url", help="HTTP or HTTPS page URL")
    fetch.add_argument("--selector", required=True, help="CSS selector to extract")

    args = parser.parse_args(argv)
    if args.command is None:
        parser.error("a command is required")

    try:
        text = fetch_text(args.url, args.selector)
    except ContentError as exc:
        print(f"pagewatch: {exc}", file=sys.stderr)
        return 1

    print(text)
    return 0
