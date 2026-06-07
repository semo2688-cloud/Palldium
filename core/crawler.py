"""
Platform crawlers — 3-tier architecture.

Tier 1 (API-based, reliable — 70% target):
  eBay Browse API, 네이버 카페 검색 API

Tier 2 (HTML scraping, accessible — 20% target):
  중고나라, 헬로마켓, Carousell Singapore

Tier 3 (Playwright / bot-protected — 10% target):
  번개장터, 당근마켓
"""

import base64
import json as _json
import random
import re
import time

import requests
from bs4 import BeautifulSoup

from core.logger import log_failure

# ── Persistent session (connection pool + consistent headers) ─────────────────

_session = requests.Session()
_session.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    "Referer": "https://www.google.com",
})
_TIMEOUT = 15


def _jitter(base: float = 1.0) -> None:
    """Randomized delay to reduce detection fingerprint."""
    time.sleep(base + random.uniform(0.3, 1.2))


# ── Tier 1: eBay Browse API ───────────────────────────────────────────────────

_ebay_token_cache: dict = {"token": "", "expires_at": 0.0}


def _get_ebay_token(app_id: str, cert_id: str) -> str:
    now = time.time()
    if _ebay_token_cache["token"] and _ebay_token_cache["expires_at"] > now + 120:
        return _ebay_token_cache["token"]

    credentials = base64.b64encode(f"{app_id}:{cert_id}".encode()).decode()
    try:
        resp = requests.post(
            "https://api.ebay.com/identity/v1/oauth2/token",
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Authorization": f"Basic {credentials}",
            },
            data={
                "grant_type": "client_credentials",
                "scope": "https://api.ebay.com/oauth/api_scope",
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        log_failure(
            "https://api.ebay.com/identity/v1/oauth2/token",
            "eBay",
            "oauth-token",
            error=str(e),
        )
        return ""

    token = data.get("access_token", "")
    expires_in = int(data.get("expires_in", 7200))
    _ebay_token_cache["token"] = token
    _ebay_token_cache["expires_at"] = now + expires_in
    return token


_EBAY_CONDITION_MAP = {
    "Used": "좋음",
    "Like New": "거의새것",
    "Seller refurbished": "보통",
    "For parts or not working": "나쁨",
    "Very Good": "거의새것",
    "Good": "좋음",
    "Acceptable": "보통",
}


def search_ebay(
    keyword: str,
    limit: int,
    app_id: str = "",
    cert_id: str = "",
) -> list[dict]:
    """
    eBay Browse API — 중고(Used) 에어컨 검색.
    developer.ebay.com 에서 App ID / Cert ID 무료 발급.
    """
    import config as _cfg
    aid = app_id or _cfg.EBAY_APP_ID
    cid = cert_id or _cfg.EBAY_CERT_ID
    if not aid or not cid:
        return []

    token = _get_ebay_token(aid, cid)
    if not token:
        return []

    results: list[dict] = []
    offset = 0

    while len(results) < limit:
        n = min(200, limit - len(results))
        try:
            resp = requests.get(
                "https://api.ebay.com/buy/browse/v1/item_summary/search",
                params={
                    "q": f"{keyword} air conditioner",
                    "filter": "conditionIds:{3000|4000|5000}",  # Used conditions
                    "limit": n,
                    "offset": offset,
                    "sort": "newlyListed",
                },
                headers={
                    "Authorization": f"Bearer {token}",
                    "X-EBAY-C-MARKETPLACE-ID": "EBAY_US",
                    "Content-Type": "application/json",
                },
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            log_failure(
                f"https://api.ebay.com/buy/browse/v1/item_summary/search?q={keyword}",
                "eBay",
                keyword,
                status_code=getattr(getattr(e, "response", None), "status_code", None),
                error=str(e),
            )
            break

        items = data.get("itemSummaries", [])
        if not items:
            break

        for item in items:
            url = item.get("itemWebUrl", "")
            if not url:
                continue

            price_info = item.get("price") or {}
            price_usd = price_info.get("value")
            currency = price_info.get("currency", "USD")
            condition = item.get("condition", "")

            results.append({
                "출처_URL": url,
                "_platform": "eBay",
                "_text": item.get("title", ""),
                "이미지_URL": (item.get("image") or {}).get("imageUrl"),
                "지역": (item.get("itemLocation") or {}).get("country"),
                "상태": _EBAY_CONDITION_MAP.get(condition, "보통"),
                "비고": f"eBay {currency} {price_usd}" if price_usd else None,
            })

        offset += len(items)
        if len(items) < n:
            break
        _jitter(0.5)

    return results[:limit]


# ── Tier 1: 네이버 카페 검색 API ──────────────────────────────────────────────

def search_naver_cafe(
    keyword: str,
    limit: int,
    client_id: str = "",
    client_secret: str = "",
) -> list[dict]:
    """
    네이버 카페 검색 API — 중고나라 카페.
    developers.naver.com 에서 무료 발급 (25,000건/일).
    """
    import config as _cfg
    cid = client_id or _cfg.NAVER_CLIENT_ID
    secret = client_secret or _cfg.NAVER_CLIENT_SECRET

    if not cid or not secret:
        return []

    results: list[dict] = []
    seen: set[str] = set()
    start = 1

    while len(results) < limit:
        n = min(100, limit - len(results))
        try:
            resp = requests.get(
                "https://openapi.naver.com/v1/search/cafearticle.json",
                params={
                    "query": f"{keyword} 중고",
                    "display": n,
                    "start": start,
                    "sort": "date",
                    "cafeid": "joonggonara",
                },
                headers={
                    "X-Naver-Client-Id": cid,
                    "X-Naver-Client-Secret": secret,
                },
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            log_failure(
                "https://openapi.naver.com/v1/search/cafearticle.json",
                "네이버 카페 중고나라",
                keyword,
                error=str(e),
            )
            break

        items = data.get("items", [])
        if not items:
            break

        for item in items:
            link = item.get("link", "")
            if not link or link in seen:
                continue
            seen.add(link)
            title = re.sub(r"<[^>]+>", "", item.get("title", ""))
            desc = re.sub(r"<[^>]+>", "", item.get("description", ""))
            results.append({
                "출처_URL": link,
                "_platform": "네이버 카페 중고나라",
                "_text": f"{title}\n{desc}".strip(),
            })

        start += n
        if len(items) < n:
            break
        _jitter(0.3)

    return results[:limit]


# ── Tier 2: Carousell Singapore ───────────────────────────────────────────────

def search_carousell(keyword: str, limit: int) -> list[dict]:
    """
    Carousell Singapore 검색.
    __NEXT_DATA__ JSON에서 리스팅 추출.
    """
    results: list[dict] = []
    seen: set[str] = set()
    page = 0

    while len(results) < limit:
        try:
            resp = _session.get(
                "https://www.carousell.sg/search/",
                params={
                    "query": f"{keyword} air conditioner",
                    "t": "1",
                    "sort_by": "time_created,descending",
                    "page": page,
                },
                timeout=_TIMEOUT,
            )
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "lxml")
            script = soup.find("script", id="__NEXT_DATA__")
            if not script or not script.string:
                break
            data = _json.loads(script.string)
        except Exception as e:
            log_failure(
                f"https://www.carousell.sg/search/?query={keyword}",
                "Carousell",
                keyword,
                error=str(e),
            )
            break

        # Try multiple known JSON paths for listings
        listings = (
            _deep_get(data, "props", "pageProps", "initialData", "results")
            or _deep_get(data, "props", "pageProps", "listings")
            or []
        )

        if not listings:
            break

        new_count = 0
        for item in listings:
            listing_id = item.get("id") or item.get("listing_id")
            if not listing_id:
                continue
            url = f"https://www.carousell.sg/p/{listing_id}"
            if url in seen:
                continue
            seen.add(url)
            new_count += 1

            title = (
                item.get("title")
                or (item.get("listing") or {}).get("title", "")
            )
            price = _to_int(
                (item.get("price") or {}).get("amount")
                or (item.get("listing") or {}).get("price")
            )
            results.append({
                "출처_URL": url,
                "_platform": "Carousell",
                "_text": title,
                "가격": price,
            })
            if len(results) >= limit:
                break

        page += 1
        if new_count == 0:
            break
        _jitter(1.0)

    return results[:limit]


# ── Tier 2: 중고나라 ──────────────────────────────────────────────────────────

def search_joongna(keyword: str, limit: int) -> list[dict]:
    results: list[dict] = []
    seen: set[str] = set()
    page = 1

    while len(results) < limit:
        try:
            resp = _session.get(
                f"https://web.joongna.com/search/{keyword}",
                params={"page": page},
                timeout=_TIMEOUT,
            )
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "lxml")
            links = [
                a["href"]
                for a in soup.find_all("a", href=re.compile(r"^/product/\d+"))
            ]
        except Exception as e:
            log_failure(
                f"https://web.joongna.com/search/{keyword}",
                "중고나라",
                keyword,
                error=str(e),
            )
            break

        if not links:
            break

        new_count = 0
        for href in links:
            url = f"https://web.joongna.com{href}"
            if url not in seen:
                seen.add(url)
                results.append({"출처_URL": url, "_platform": "중고나라", "_text": None})
                new_count += 1
                if len(results) >= limit:
                    break

        page += 1
        if new_count < 5:
            break
        _jitter(0.8)

    return results[:limit]


# ── Tier 2: 헬로마켓 ──────────────────────────────────────────────────────────

def search_hellomarket(keyword: str, limit: int) -> list[dict]:
    results: list[dict] = []
    seen: set[str] = set()
    page = 1

    while len(results) < limit:
        try:
            resp = _session.get(
                "https://www.hellomarket.com/search",
                params={"q": keyword, "page": page},
                timeout=_TIMEOUT,
            )
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "lxml")
            links = [
                a["href"]
                for a in soup.find_all("a", href=re.compile(r"/item/\d+"))
            ]
        except Exception as e:
            log_failure(
                f"https://www.hellomarket.com/search?q={keyword}",
                "헬로마켓",
                keyword,
                error=str(e),
            )
            break

        if not links:
            break

        new_count = 0
        for href in links:
            clean = re.sub(r"\?.*$", "", href)
            url = f"https://www.hellomarket.com{clean}" if clean.startswith("/") else clean
            if url not in seen:
                seen.add(url)
                results.append({"출처_URL": url, "_platform": "헬로마켓", "_text": None})
                new_count += 1
                if len(results) >= limit:
                    break

        page += 1
        if new_count < 5:
            break
        _jitter(0.8)

    return results[:limit]


# ── Tier 3: 번개장터 (Playwright) ──────────────────────────────────────────────

def search_bunjang(keyword: str, limit: int) -> list[dict]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return []

    results: list[dict] = []
    seen: set[str] = set()

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(
                user_agent=_session.headers["User-Agent"],
                viewport={"width": 1280, "height": 900},
            )
            page = ctx.new_page()
            api_items: list[dict] = []

            def on_response(resp):
                ct = resp.headers.get("content-type", "")
                if "json" in ct and any(k in resp.url for k in ("find", "search", "product")):
                    try:
                        body = resp.json()
                        items = body.get("list") or body.get("products") or body.get("items") or []
                        if items and isinstance(items[0], dict) and items[0].get("pid"):
                            api_items.extend(items)
                    except Exception:
                        pass

            page.on("response", on_response)
            page.goto(
                f"https://bunjang.co.kr/search/product?q={keyword}&order=date",
                wait_until="networkidle",
                timeout=30000,
            )
            page.wait_for_timeout(4000)

            if api_items:
                for it in api_items[:limit]:
                    pid = str(it.get("pid") or "")
                    if not pid:
                        continue
                    url = f"https://bunjang.co.kr/products/{pid}"
                    if url not in seen:
                        seen.add(url)
                        results.append({
                            "출처_URL": url,
                            "_platform": "번개장터",
                            "_text": f"{it.get('name', '')} {it.get('description', '')}".strip() or None,
                            "가격": _to_int(it.get("price")),
                            "이미지_URL": it.get("product_image"),
                            "지역": it.get("location"),
                        })
            else:
                content = page.content()
                pids = list(dict.fromkeys(re.findall(r"/products/(\d+)", content)))
                for pid in pids[:limit]:
                    url = f"https://bunjang.co.kr/products/{pid}"
                    if url not in seen:
                        seen.add(url)
                        results.append({"출처_URL": url, "_platform": "번개장터", "_text": None})
                if not pids:
                    log_failure(
                        f"https://bunjang.co.kr/search/product?q={keyword}",
                        "번개장터",
                        keyword,
                        error="0 results — bot-blocked (Cloudflare)",
                    )

            browser.close()
    except Exception as e:
        log_failure(
            f"https://bunjang.co.kr/search/product?q={keyword}",
            "번개장터",
            keyword,
            error=str(e),
        )

    return results[:limit]


# ── Tier 3: 당근마켓 (Playwright) ─────────────────────────────────────────────

def search_daangn(keyword: str, limit: int) -> list[dict]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return []

    results: list[dict] = []
    seen: set[str] = set()

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(
                user_agent=_session.headers["User-Agent"],
                viewport={"width": 1280, "height": 900},
            )
            page = ctx.new_page()
            page.goto(
                f"https://www.daangn.com/search/{keyword}",
                wait_until="networkidle",
                timeout=30000,
            )
            page.wait_for_timeout(5000)
            for _ in range(3):
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(2000)

            content = page.content()
            article_ids = list(dict.fromkeys(re.findall(r"/articles/(\d+)", content)))

            for aid in article_ids[:limit]:
                url = f"https://www.daangn.com/articles/{aid}"
                if url not in seen:
                    seen.add(url)
                    results.append({"출처_URL": url, "_platform": "당근마켓", "_text": None})

            if not article_ids:
                log_failure(
                    f"https://www.daangn.com/search/{keyword}",
                    "당근마켓",
                    keyword,
                    error="0 results — bot-blocked or location-restricted",
                )

            browser.close()
    except Exception as e:
        log_failure(
            f"https://www.daangn.com/search/{keyword}",
            "당근마켓",
            keyword,
            error=str(e),
        )

    return results[:limit]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _to_int(val):
    if val is None:
        return None
    try:
        return int(str(val).replace(",", "").replace("원", "").strip())
    except (ValueError, TypeError):
        return None


def _deep_get(d: dict, *keys):
    for k in keys:
        if not isinstance(d, dict):
            return None
        d = d.get(k)
    return d


# ── Registry ──────────────────────────────────────────────────────────────────

PLATFORM_CRAWLERS: dict[str, callable] = {
    "eBay": search_ebay,
    "네이버 카페 중고나라": search_naver_cafe,
    "중고나라": search_joongna,
    "헬로마켓": search_hellomarket,
    "Carousell": search_carousell,
    "번개장터": search_bunjang,
    "당근마켓": search_daangn,
}

# 1=API 기반 안정, 2=HTML 스크래핑, 3=Playwright/봇방지
PLATFORM_TIERS: dict[str, int] = {
    "eBay": 1,
    "네이버 카페 중고나라": 1,
    "중고나라": 2,
    "헬로마켓": 2,
    "Carousell": 2,
    "번개장터": 3,
    "당근마켓": 3,
}

LIMITED_PLATFORMS = {"번개장터", "당근마켓"}
