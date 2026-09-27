# Pagewatch AI

Pagewatch AI is a small CLI project for monitoring configured web pages and emailing users about meaningful changes. Its intended flow is: fetch, extract, normalize, compare, classify relevance, notify, then commit state.

**Status:** single-watch change detection. The CLI can fetch one HTTP/HTML page, extract normalized text with a CSS selector, and compare it with a local baseline. It does not yet classify changes or send email. The planned v0.1 behavior is specified in [docs/v0.1.md](docs/v0.1.md).

## Fetch text

```sh
uv run pagewatch fetch https://example.com --selector 'h1'
```

Scripts and styles are excluded from the selected content, and whitespace is collapsed. The command exits with status 1 if fetching or extraction fails; invalid CLI arguments exit with status 2.

## Detect changes

```sh
uv run pagewatch watch https://example.com --selector 'h1' --state-file .pagewatch/homepage.json
```

Use one state file per URL and selector. The first run saves a baseline and prints `baseline established`. Identical content prints `unchanged`. Changed content prints a word-level unified diff and updates the baseline, so the next identical run is unchanged. Failed fetches or extraction do not replace a valid baseline. The state file is local JSON; `.pagewatch/` is ignored by Git.

## Local development

Install [uv](https://docs.astral.sh/uv/) and run:

```sh
uv sync --group dev
uv run pagewatch --help
uv run pagewatch --version
./scripts/verify.sh
```

The verify script runs Ruff lint and format checks plus pytest. Python 3.11 or newer is required.

## License

MIT; see [LICENSE](LICENSE).
