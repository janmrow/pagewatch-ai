# Pagewatch AI

Pagewatch AI is a small CLI project for monitoring configured web pages and emailing users about meaningful changes. Its intended flow is: fetch, extract, normalize, compare, classify relevance, notify, then commit state.

**Status:** configured change detection, LLM relevance classification, and plain-text email notifications. The CLI can check multiple HTTP/HTML pages with CSS selectors, compare their normalized text with local baselines, classify changes through a Chat Completions endpoint, and send relevant changes through SMTP with STARTTLS. The planned v0.1 behavior is specified in [docs/v0.1.md](docs/v0.1.md).

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

Set the Chat Completions endpoint, API key, model, and SMTP settings in the environment before running:

```sh
export PAGEWATCH_LLM_URL=https://opencode.ai/inference/openai/v1/chat/completions
export PAGEWATCH_LLM_API_KEY="your-service-account-key"
export PAGEWATCH_LLM_MODEL="your-chat-completions-model-id"
export PAGEWATCH_SMTP_HOST=smtp.example.com
export PAGEWATCH_SMTP_PORT=587
export PAGEWATCH_SMTP_USERNAME="your-smtp-username"
export PAGEWATCH_SMTP_PASSWORD="your-smtp-password"
export PAGEWATCH_MAIL_FROM=sender@example.com
export PAGEWATCH_MAIL_TO=recipient@example.com
uv run pagewatch run --config watches.toml --state-dir .pagewatch
```

The URL above is the [OpenCode Console Inference API](https://opencode.ai/v2/docs/console/inference/). `PAGEWATCH_LLM_URL` is the complete Chat Completions endpoint, not just a base URL. To use [OpenAI Chat Completions](https://developers.openai.com/api/docs/guides/prompt-engineering), set it to `https://api.openai.com/v1/chat/completions` and provide an OpenAI API key and a model that supports that endpoint. Other providers with the same request, Bearer authentication, and response format can be used by changing these three variables. The endpoint must use HTTPS, and API redirects are refused to keep the key at the configured endpoint. Keep the API key out of `watches.toml` and Git.

Each watch needs `id`, `url`, `selector`, and nonempty `interest`. IDs must be unique and contain only letters, digits, hyphens, or underscores, beginning with a letter or digit. Each baseline is saved as `<state-dir>/<id>.json`. All watches run even if one fails; the command exits with status 1 if any watch fails. TOML, LLM, and SMTP settings are validated before any watch. The first run establishes a baseline without calling the LLM or sending email. Later changes use each watch's `interest` for classification. `run` prints only each successful watch's short status (`baseline established`, `unchanged`, or `changed`) and writes INFO/ERROR progress logs to stderr for journald. It does not print page text, diffs, classifier summaries or reasons, or credentials. Relevant changes send one plain-text email to the configured recipient with the watch ID, summary, reason, source URL, and UTC detection time. The SMTP server must support STARTTLS; login and message delivery happen only after TLS is established. Keep SMTP credentials out of `watches.toml` and Git.

## Relevance classification contract

The internal watcher can pass `interest` and a word-level diff to an injected classifier. Its response must be JSON with exactly these fields:

```json
{"relevant": true, "summary": "A deadline changed", "reason": "Matches the watch interest"}
```

Before classification, the watcher saves one unresolved content snapshot and its UTC detection time alongside the last handled baseline. A classifier or email error keeps that snapshot for the next classified check, even if the page later changes or reverts. An irrelevant decision or successful email submission advances the baseline and clears the snapshot. Existing unresolved snapshots without a detection time are stamped on their first run with this version. The detection-only `watch` command refuses to advance an unresolved snapshot or a legacy `pending: true` marker. Old markers do not contain the changed content; if it is no longer on the page, manual recovery is needed. An email may be delivered more than once if SMTP accepts it but saving the baseline fails. The prompt treats monitored website content as untrusted data; the response still must pass the strict JSON contract above.

## Local development

Install [uv](https://docs.astral.sh/uv/) and run:

```sh
uv sync --group dev
uv run pagewatch --help
uv run pagewatch --version
./scripts/verify.sh
```

The verify script runs Ruff lint and format checks plus pytest. Python 3.11 or newer is required. GitHub Actions runs it for pull requests and pushes to `main` with Python 3.11 and 3.14.

For a manual Ubuntu/systemd installation, see [docs/deployment.md](docs/deployment.md).

## License

MIT; see [LICENSE](LICENSE).
