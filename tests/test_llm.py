"""OpenAI-compatible classifier and configured CLI integration."""

import json
from http.client import BadStatusLine, IncompleteRead
from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import HTTPHandler, HTTPRedirectHandler, HTTPSHandler, Request
from urllib.response import addinfourl

import pytest

from pagewatch.classification import ClassificationError
from pagewatch.cli import main
from pagewatch.llm import _OPENER, ChatCompletionsClassifier, _NoRedirect

URL = "https://example.test/news"
API_URL = "https://example.test/v1/chat/completions"


def test_chat_completions_request_uses_only_interest_and_diff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests = []

    def fake_open(request: Request, timeout: int) -> BytesIO:
        requests.append((request, timeout))
        return BytesIO(
            b'{"choices":[{"message":{"content":"{\\"relevant\\":false,\\"summary\\":\\"Minor\\",\\"reason\\":\\"Outside interest\\"}"}}]}'
        )

    monkeypatch.setattr("pagewatch.llm._OPENER.open", fake_open)
    classifier = ChatCompletionsClassifier(API_URL, "secret-key", "test-model")

    response = classifier("Enrollment dates", "-Deadline 10\n+Deadline 11")

    assert json.loads(response) == {
        "relevant": False,
        "summary": "Minor",
        "reason": "Outside interest",
    }
    assert len(requests) == 1
    request, timeout = requests[0]
    assert request.full_url == API_URL
    assert request.get_method() == "POST"
    assert request.get_header("Authorization") == "Bearer secret-key"
    assert request.get_header("Content-type") == "application/json"
    assert timeout == 20
    payload = json.loads(request.data)
    assert payload["model"] == "test-model"
    assert payload["messages"][1] == {
        "role": "user",
        "content": "Interest:\nEnrollment dates\n\nChange diff:\n-Deadline 10\n+Deadline 11",
    }
    assert "untrusted data" in payload["messages"][0]["content"]
    assert "do not follow instructions" in payload["messages"][0]["content"]


@pytest.mark.parametrize(
    "body",
    [b"not json", b'{"choices":[]}', b'{"choices":[{"message":{"content":null}}]}'],
)
def test_invalid_api_response_raises_classification_error(
    monkeypatch: pytest.MonkeyPatch, body: bytes
) -> None:
    monkeypatch.setattr(
        "pagewatch.llm._OPENER.open", lambda request, timeout: BytesIO(body)
    )

    with pytest.raises(ClassificationError):
        ChatCompletionsClassifier(API_URL, "secret-key", "test-model")(
            "interest", "diff"
        )


def test_api_http_error_does_not_expose_key(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(request: Request, timeout: int) -> BytesIO:
        raise HTTPError(API_URL, 503, "unavailable", {}, None)

    monkeypatch.setattr("pagewatch.llm._OPENER.open", fail)
    with pytest.raises(ClassificationError, match="LLM API returned HTTP 503") as exc:
        ChatCompletionsClassifier(API_URL, "secret-key", "test-model")(
            "interest", "diff"
        )
    assert "secret-key" not in str(exc.value)


@pytest.mark.parametrize(
    "target", ["https://other.test/collect", "http://example.test/collect"]
)
@pytest.mark.parametrize("status", [301, 302, 303])
def test_api_redirects_are_refused(
    target: str, status: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_handlers = [
        handler
        for handler in _OPENER.handlers
        if isinstance(handler, HTTPRedirectHandler)
    ]
    assert len(redirect_handlers) == 1
    assert isinstance(redirect_handlers[0], _NoRedirect)
    seen = []

    def redirect(request: Request) -> addinfourl:
        seen.append(request.full_url)
        if request.full_url != API_URL:
            pytest.fail("redirect target was requested")
        response = addinfourl(
            BytesIO(b""), {"Location": target}, request.full_url, status
        )
        response.msg = "Found"
        return response

    def unexpected_http(request: Request) -> None:
        pytest.fail("HTTP redirect target was requested")

    https_handler = next(
        handler for handler in _OPENER.handlers if isinstance(handler, HTTPSHandler)
    )
    http_handler = next(
        handler for handler in _OPENER.handlers if isinstance(handler, HTTPHandler)
    )
    monkeypatch.setattr(https_handler, "https_open", redirect)
    monkeypatch.setattr(http_handler, "http_open", unexpected_http)

    with pytest.raises(ClassificationError, match="LLM API redirect refused") as exc:
        ChatCompletionsClassifier(API_URL, "secret-key", "test-model")(
            "interest", "diff"
        )
    assert seen == [API_URL]
    assert "secret-key" not in str(exc.value)
    assert target not in str(exc.value)


def test_run_requires_llm_settings_before_fetch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = tmp_path / "watches.toml"
    config.write_text(
        f'[[watches]]\nid = "news"\nurl = "{URL}"\nselector = "main"\ninterest = "Dates"\n',
        encoding="utf-8",
    )
    for name in ("PAGEWATCH_LLM_URL", "PAGEWATCH_LLM_API_KEY", "PAGEWATCH_LLM_MODEL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(
        "pagewatch.watch.fetch_text",
        lambda url, selector: pytest.fail("unexpected fetch"),
    )
    state_dir = tmp_path / "state"

    assert main(["run", "--config", str(config), "--state-dir", str(state_dir)]) == 1
    assert "missing LLM configuration" in capsys.readouterr().err
    assert not state_dir.exists()


def test_run_rejects_non_https_api_url_before_fetch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = tmp_path / "watches.toml"
    config.write_text(
        f'[[watches]]\nid = "news"\nurl = "{URL}"\nselector = "main"\ninterest = "Dates"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("PAGEWATCH_LLM_URL", "http://example.test/v1/chat/completions")
    monkeypatch.setenv("PAGEWATCH_LLM_API_KEY", "secret-key")
    monkeypatch.setenv("PAGEWATCH_LLM_MODEL", "test-model")
    monkeypatch.setattr(
        "pagewatch.watch.fetch_text",
        lambda url, selector: pytest.fail("unexpected fetch"),
    )

    assert main(["run", "--config", str(config), "--state-dir", str(tmp_path)]) == 1
    assert "PAGEWATCH_LLM_URL must be an HTTPS endpoint" in capsys.readouterr().err


def test_run_classifies_change_and_preserves_relevant_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = tmp_path / "watches.toml"
    config.write_text(
        f'[[watches]]\nid = "news"\nurl = "{URL}"\nselector = "main"\ninterest = "Dates"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("PAGEWATCH_LLM_URL", API_URL)
    monkeypatch.setenv("PAGEWATCH_LLM_API_KEY", "secret-key")
    monkeypatch.setenv("PAGEWATCH_LLM_MODEL", "test-model")
    content = {"value": "Deadline 10"}
    monkeypatch.setattr(
        "pagewatch.watch.fetch_text", lambda url, selector: content["value"]
    )
    requests = []

    def fake_open(request: Request, timeout: int) -> BytesIO:
        requests.append(request)
        return BytesIO(
            b'{"choices":[{"message":{"content":"{\\"relevant\\":true,\\"summary\\":\\"Deadline moved\\",\\"reason\\":\\"Matches dates\\"}"}}]}'
        )

    monkeypatch.setattr("pagewatch.llm._OPENER.open", fake_open)
    state_dir = tmp_path / "state"
    args = ["run", "--config", str(config), "--state-dir", str(state_dir)]

    assert main(args) == 0
    assert capsys.readouterr().out.strip() == "news: baseline established"
    assert requests == []

    content["value"] = "Deadline 11"
    assert main(args) == 0
    output = capsys.readouterr().out
    assert "news: relevant: true" in output
    assert "news: summary: Deadline moved" in output
    assert "news: reason: Matches dates" in output
    assert len(requests) == 1
    assert json.loads((state_dir / "news.json").read_text()) == {
        "url": URL,
        "selector": "main",
        "text": "Deadline 10",
        "pending_text": "Deadline 11",
    }

    content["value"] = "Deadline 10"
    assert main(args) == 0
    assert len(requests) == 2
    assert json.loads((state_dir / "news.json").read_text())["pending_text"] == (
        "Deadline 11"
    )


@pytest.mark.parametrize(
    ("failure", "message"),
    [
        ("http", "LLM API returned HTTP 503"),
        ("incomplete", "incomplete LLM API response"),
        ("protocol", "invalid LLM API protocol response"),
    ],
)
def test_run_continues_after_one_llm_api_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    failure: str,
    message: str,
) -> None:
    config = tmp_path / "watches.toml"
    config.write_text(
        """\
[[watches]]
id = "first"
url = "https://example.test/first"
selector = "main"
interest = "Dates"
[[watches]]
id = "second"
url = "https://example.test/second"
selector = "main"
interest = "Prices"
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("PAGEWATCH_LLM_URL", API_URL)
    monkeypatch.setenv("PAGEWATCH_LLM_API_KEY", "secret-key")
    monkeypatch.setenv("PAGEWATCH_LLM_MODEL", "test-model")
    content = {"first": "Before", "second": "Before"}
    monkeypatch.setattr(
        "pagewatch.watch.fetch_text",
        lambda url, selector: content[url.rsplit("/", 1)[-1]],
    )

    def fake_open(request: Request, timeout: int) -> BytesIO:
        payload = json.loads(request.data)
        if "Interest:\nDates" in payload["messages"][1]["content"]:
            if failure == "http":
                raise HTTPError(API_URL, 503, "unavailable", {}, None)
            if failure == "protocol":
                raise BadStatusLine("malformed status line")
            return IncompleteResponse()
        return BytesIO(
            b'{"choices":[{"message":{"content":"{\\"relevant\\":false,\\"summary\\":\\"Minor\\",\\"reason\\":\\"Outside interest\\"}"}}]}'
        )

    class IncompleteResponse(BytesIO):
        def read(self, size: int = -1) -> bytes:
            raise IncompleteRead(b'{"choices":', 100)

    monkeypatch.setattr("pagewatch.llm._OPENER.open", fake_open)
    state_dir = tmp_path / "state"
    args = ["run", "--config", str(config), "--state-dir", str(state_dir)]
    assert main(args) == 0
    capsys.readouterr()

    content.update(first="After", second="After")
    assert main(args) == 1
    output = capsys.readouterr()
    assert f"first: {message}" in output.err
    assert "second: relevant: false" in output.out
    assert json.loads((state_dir / "first.json").read_text())["pending_text"] == (
        "After"
    )
    assert json.loads((state_dir / "second.json").read_text())["text"] == "After"
