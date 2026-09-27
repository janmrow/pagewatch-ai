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

Each watch needs `id`, `url`, `selector`, and nonempty `interest`. IDs must be unique and contain only letters, digits, hyphens, or underscores, beginning with a letter or digit. Each baseline is saved as `<state-dir>/<id>.json`. All watches run even if one fails; the command exits with status 1 if any watch fails. TOML parsing and field validation run before any watch.

## Relevance classification contract

The internal watcher can pass `interest` and a word-level diff to an injected classifier. Its response must be JSON with exactly these fields:

```json
{"relevant": true, "summary": "A deadline changed", "reason": "Matches the watch interest"}
```

Before classification, the watcher saves one unresolved content snapshot alongside the last handled baseline. A classifier error or relevant change without a successful notification keeps that snapshot for the next classified check, even if the page later changes or reverts. An irrelevant decision or successful notification advances the baseline and clears the snapshot. Detection-only `watch` and `run` refuse to advance a watch with an unresolved snapshot or a legacy `pending: true` marker. Old markers do not contain the changed content; if it is no longer on the page, manual recovery is needed. A notification may be delivered more than once if delivery succeeds but saving the baseline fails. This contract is tested with fakes. The CLI still does not invoke a classifier or notifier, and no LLM API or email service is connected.

## Local development

Install [uv](https://docs.astral.sh/uv/) and run:

```sh
uv sync --group dev
uv run pagewatch --help
uv run pagewatch --version
./scripts/verify.sh
```

The verify script runs Ruff lint and format checks plus pytest. Python 3.11 or newer is required. GitHub Actions runs it for pull requests and pushes to `main` with Python 3.11 and 3.14.

## License

MIT; see [LICENSE](LICENSE).
