"""Load watches from a small TOML configuration file."""

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*\Z")


class ConfigError(Exception):
    """The watch configuration could not be loaded or validated."""


@dataclass(frozen=True)
class Watch:
    id: str
    url: str
    selector: str
    interest: str


def load_watches(path: Path) -> list[Watch]:
    """Load a nonempty list of watches with unique, file-safe IDs."""
    try:
        with path.open("rb") as file:
            config = tomllib.load(file)
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(f"could not load config {path}: {exc}") from exc

    unknown = set(config) - {"watches"}
    if unknown:
        raise ConfigError(f"unknown config fields: {', '.join(sorted(unknown))}")
    raw_watches = config.get("watches")
    if not isinstance(raw_watches, list) or not raw_watches:
        raise ConfigError("config must contain at least one [[watches]] entry")

    watches = []
    seen_ids = set()
    for number, raw in enumerate(raw_watches, start=1):
        if not isinstance(raw, dict):
            raise ConfigError(f"watch {number} must be a TOML table")
        unknown = set(raw) - {"id", "url", "selector", "interest"}
        if unknown:
            raise ConfigError(
                f"watch {number} has unknown fields: {', '.join(sorted(unknown))}"
            )
        for field in ("id", "url", "selector", "interest"):
            if not isinstance(raw.get(field), str) or not raw[field].strip():
                raise ConfigError(f"watch {number} needs a nonempty {field}")

        watch = Watch(
            id=raw["id"],
            url=raw["url"],
            selector=raw["selector"],
            interest=raw["interest"],
        )
        if not _SAFE_ID.fullmatch(watch.id):
            raise ConfigError(f"watch {number} has an invalid id: {watch.id}")
        if watch.id in seen_ids:
            raise ConfigError(f"duplicate watch id: {watch.id}")
        seen_ids.add(watch.id)
        watches.append(watch)
    return watches
