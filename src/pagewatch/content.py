"""Fetch a web page and extract readable text from one CSS selection."""

from http.client import InvalidURL
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import urlopen

from bs4 import BeautifulSoup
from soupsieve.util import SelectorSyntaxError


class ContentError(Exception):
    """The page could not be fetched or its selected text extracted."""


def fetch_text(url: str, selector: str) -> str:
    """Return normalized text from the first element matching ``selector``."""
    try:
        parsed_url = urlsplit(url)
    except ValueError as exc:
        raise ContentError(f"invalid URL: {exc}") from exc
    if parsed_url.scheme not in {"http", "https"} or not parsed_url.hostname:
        raise ContentError("URL must use HTTP or HTTPS and include a host")

    try:
        with urlopen(url, timeout=10) as response:
            body = response.read()
            encoding = response.headers.get_content_charset()
    except HTTPError as exc:
        raise ContentError(f"HTTP {exc.code} while fetching {url}") from exc
    except (URLError, TimeoutError, InvalidURL, UnicodeEncodeError) as exc:
        raise ContentError(f"could not fetch {url}: {exc}") from exc

    soup = BeautifulSoup(body, "html.parser", from_encoding=encoding)
    try:
        selected = soup.select_one(selector)
    except SelectorSyntaxError as exc:
        raise ContentError(f"invalid CSS selector: {selector}") from exc
    if selected is None:
        raise ContentError(f"CSS selector matched no element: {selector}")
    if selected.name in {"script", "style"}:
        raise ContentError(f"CSS selector matched no readable text: {selector}")

    for tag in selected.find_all(["script", "style"]):
        tag.replace_with(" ")
    for tag in selected.find_all("br"):
        tag.replace_with(" ")
    for tag in selected.find_all(
        [
            "article",
            "blockquote",
            "div",
            "h1",
            "h2",
            "h3",
            "h4",
            "h5",
            "h6",
            "li",
            "p",
            "section",
            "td",
            "th",
            "tr",
        ]
    ):
        tag.insert_before(" ")
        tag.append(" ")

    text = " ".join(selected.get_text().split())
    if not text:
        raise ContentError(f"CSS selector matched no readable text: {selector}")
    return text
