"""Command-line entry point for Pagewatch."""

import argparse
import sys
from collections.abc import Sequence
from importlib.metadata import version
from pathlib import Path

from pagewatch.config import ConfigError, load_watches
from pagewatch.content import ContentError, fetch_text
from pagewatch.watch import WatchError, check_watch


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="pagewatch",
        description="Fetch web pages and detect content changes.",
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
    watch = commands.add_parser("watch", help="detect changes for one page")
    watch.add_argument("url", help="HTTP or HTTPS page URL")
    watch.add_argument("--selector", required=True, help="CSS selector to extract")
    watch.add_argument(
        "--state-file", required=True, type=Path, help="local baseline file"
    )
    run = commands.add_parser("run", help="check every watch in a TOML config")
    run.add_argument("--config", required=True, type=Path, help="TOML config file")
    run.add_argument("--state-dir", required=True, type=Path, help="baseline directory")

    args = parser.parse_args(argv)
    if args.command is None:
        parser.error("a command is required")

    if args.command == "run":
        try:
            watches = load_watches(args.config)
        except ConfigError as exc:
            print(f"pagewatch: {exc}", file=sys.stderr)
            return 1

        failed = False
        for watch in watches:
            try:
                result = check_watch(
                    watch.url, watch.selector, args.state_dir / f"{watch.id}.json"
                )
            except (ContentError, WatchError) as exc:
                print(f"pagewatch: {watch.id}: {exc}", file=sys.stderr)
                failed = True
                continue
            print(f"{watch.id}: {result.status}")
            if result.diff:
                print(result.diff)
        return int(failed)

    try:
        if args.command == "fetch":
            print(fetch_text(args.url, args.selector))
        else:
            result = check_watch(args.url, args.selector, args.state_file)
            print(result.diff or result.status)
    except (ContentError, WatchError) as exc:
        print(f"pagewatch: {exc}", file=sys.stderr)
        return 1

    return 0
