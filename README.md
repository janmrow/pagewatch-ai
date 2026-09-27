# Pagewatch AI

Pagewatch AI is a small CLI project for monitoring configured web pages and emailing users about meaningful changes. Its intended flow is: fetch, extract, normalize, compare, classify relevance, notify, then commit state.

**Status:** project harness only. The CLI currently supports `--help` and `--version`; it does not fetch pages, detect changes, classify content, or send email yet. The planned v0.1 behavior is specified in [docs/v0.1.md](docs/v0.1.md).

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
