# Pagewatch AI

Pagewatch AI is a small CLI project for monitoring configured web pages and emailing users about meaningful changes. Its intended flow is: fetch, extract, normalize, compare, classify relevance, notify, then commit state.

**Status:** configured change detection. The CLI can check multiple HTTP/HTML pages with CSS selectors and compare their normalized text with local baselines. It does not yet classify changes or send email. The planned v0.1 behavior is specified in [docs/v0.1.md](docs/v0.1.md).

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

## Run configured watches

Create `watches.toml`:

```toml
[[watches]]
id = "news"
url = "https://example.com/news"
selector = "main"
interest = "Updates to the news page"

[[watches]]
id = "announcements"
url = "https://example.com/announcements"
selector = "article"
interest = "New announcements"
```

```sh
uv run pagewatch run --config watches.toml --state-dir .pagewatch
```

Each watch needs `id`, `url`, `selector`, and nonempty `interest`. IDs must be unique and contain only letters, digits, hyphens, or underscores, beginning with a letter or digit. Each baseline is saved as `<state-dir>/<id>.json`. `interest` is loaded but not used until relevance classification is implemented. All watches run even if one fails; the command exits with status 1 if any watch fails. TOML parsing and field validation run before any watch.

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
