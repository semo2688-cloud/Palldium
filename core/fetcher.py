import re
import requests
from bs4 import BeautifulSoup
import config

try:
    from fake_useragent import UserAgent
    _ua = UserAgent()
    _get_ua = lambda: _ua.random
except Exception:
    _get_ua = lambda: (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )

PLATFORM_PATTERNS = {
    "번개장터": re.compile(r"bunjang\.co\.kr"),
    "중고나라": re.compile(r"(joongna\.com|cafe\.naver\.com/joonggonara)"),
    "당근마켓": re.compile(r"daangn\.com"),
}


def detect_platform(url: str) -> str:
    for name, pattern in PLATFORM_PATTERNS.items():
        if pattern.search(url):
            return name
    return "기타"


def fetch_page(url: str) -> tuple[str, str]:
    """Returns (platform, cleaned_text). On failure returns (platform, "")."""
    platform = detect_platform(url)
    headers = {
        "User-Agent": _get_ua(),
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Referer": "https://www.google.com",
    }
    try:
        resp = requests.get(url, headers=headers, timeout=config.REQUEST_TIMEOUT_SEC)
        resp.raise_for_status()
        resp.encoding = resp.apparent_encoding or "utf-8"
        text = _clean_html(resp.text)
    except requests.exceptions.RequestException as e:
        return platform, f"__FETCH_ERROR__: {e}"

    return platform, text


def _clean_html(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "nav", "footer", "header", "noscript", "iframe"]):
        tag.decompose()
    text = soup.get_text(separator="\n", strip=True)
    lines = [line for line in text.splitlines() if line.strip()]
    cleaned = "\n".join(lines)
    return cleaned[: config.MAX_PAGE_TEXT_CHARS]
