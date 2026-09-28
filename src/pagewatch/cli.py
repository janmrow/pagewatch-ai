"""Command-line entry point for Pagewatch."""

import argparse
import logging
import sys
from collections.abc import Sequence
from functools import partial
from importlib.metadata import version
from pathlib import Path

from pagewatch.classification import ClassificationError
from pagewatch.config import ConfigError, load_watches
from pagewatch.content import ContentError, fetch_text
from pagewatch.llm import classifier_from_env
from pagewatch.mail import NotificationError, notifier_from_env
from pagewatch.watch import WatchError, check_watch

_LOG = logging.getLogger("pagewatch.runtime")


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
            classifier = classifier_from_env()
            mailer = notifier_from_env()
        except (ConfigError, ClassificationError, NotificationError) as exc:
            print(f"pagewatch: {exc}", file=sys.stderr)
            return 1

        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
        old_level, old_propagate = _LOG.level, _LOG.propagate
        _LOG.addHandler(handler)
        _LOG.setLevel(logging.INFO)
        _LOG.propagate = False
        try:
            failed = False
            for watch in watches:
                try:
                    result = check_watch(
                        watch.url,
                        watch.selector,
                        args.state_dir / f"{watch.id}.json",
                        interest=watch.interest,
                        classifier=classifier,
                        notifier=partial(mailer.send, watch.id, watch.url),
                        watch_id=watch.id,
                    )
                except ContentError:
                    _LOG.error("watch=%s fetch failed", watch.id)
                except WatchError:
                    _LOG.error("watch=%s state operation failed", watch.id)
                except ClassificationError:
                    pass  # The classifier stage logged the failure.
                except NotificationError:
                    _LOG.error("watch=%s notification failed", watch.id)
                else:
                    print(f"{watch.id}: {result.status}")
                    continue
                failed = True
            return int(failed)
        finally:
            _LOG.removeHandler(handler)
            _LOG.setLevel(old_level)
            _LOG.propagate = old_propagate

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
