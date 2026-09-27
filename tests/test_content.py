"""Fetch, extraction, and CLI checks with a fixed HTTP response fixture."""

from http.client import InvalidURL
from unittest.mock import MagicMock
from urllib.error import HTTPError

import pytest

from pagewatch.cli import main
from pagewatch.content import ContentError, fetch_text

PAGE_URL = "https://example.test/page"
PAGE_HTML = b"""<html><main>
    <h1> Hello <em>world</em>! </h1>
    <style>hidden style</style><script>hidden script</script>
    <p> Next \n line<br>after break </p>
</main></html>"""


@pytest.fixture
def stub_http(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    response = MagicMock()
    response.__enter__.return_value = response
    response.status = 200
    response.read.return_value = PAGE_HTML
    response.headers.get_content_charset.return_value = "utf-8"

    def open_page(url: str, timeout: int) -> MagicMock:
        assert timeout == 10
        if url.endswith("/error"):
            raise HTTPError(url, 500, "Server error", None, None)
        if url.endswith(":bad/"):
            raise InvalidURL("nonnumeric port")
        return response

    monkeypatch.setattr("pagewatch.content.urlopen", open_page)
    return response


def test_200_extracts_and_normalizes_text(stub_http: MagicMock) -> None:
    assert fetch_text(PAGE_URL, "main") == "Hello world! Next line after break"


def test_block_element_has_boundaries_on_both_sides(stub_http: MagicMock) -> None:
    stub_http.read.return_value = b"<main>Intro<p>Details</p>Outro</main>"
    assert fetch_text(PAGE_URL, "main") == "Intro Details Outro"


@pytest.mark.parametrize("selector", ["script", "style"])
def test_selected_script_or_style_has_no_readable_text(
    stub_http: MagicMock, selector: str
) -> None:
    with pytest.raises(ContentError, match="no readable text"):
        fetch_text(PAGE_URL, selector)


def test_500_is_an_error(stub_http: MagicMock) -> None:
    with pytest.raises(ContentError, match="HTTP 500"):
        fetch_text("https://example.test/error", "main")


def test_missing_selector_is_an_error(stub_http: MagicMock) -> None:
    with pytest.raises(ContentError, match="CSS selector matched no element"):
        fetch_text(PAGE_URL, "#missing")


def test_cli_prints_text(
    stub_http: MagicMock, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["fetch", PAGE_URL, "--selector", "main"]) == 0
    assert capsys.readouterr().out.strip() == "Hello world! Next line after break"


def test_cli_reports_http_error(
    stub_http: MagicMock, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["fetch", "https://example.test/error", "--selector", "main"]) == 1
    assert "HTTP 500" in capsys.readouterr().err


def test_cli_reports_invalid_request_url(
    stub_http: MagicMock, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["fetch", "https://example.test:bad/", "--selector", "main"]) == 1
    assert "nonnumeric port" in capsys.readouterr().err
