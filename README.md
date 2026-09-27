# Pagewatch AI

Pagewatch AI is a small CLI project for monitoring configured web pages and emailing users about meaningful changes. Its intended flow is: fetch, extract, normalize, compare, classify relevance, notify, then commit state.

**Status:** fetch and extraction only. The CLI can fetch one HTTP/HTML page, select its first matching element with a CSS selector, and print normalized text. It does not yet detect changes, classify content, persist state, or send email. The planned v0.1 behavior is specified in [docs/v0.1.md](docs/v0.1.md).

## Fetch text

```sh
uv run pagewatch fetch https://example.com --selector 'h1'
```

Scripts and styles are excluded from the selected content, and whitespace is collapsed. The command exits with status 1 if fetching or extraction fails; invalid CLI arguments exit with status 2.

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
