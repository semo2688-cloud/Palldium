"""
Platform crawlers.
Each crawler returns list[dict] where each dict has at minimum:
  - "출처_URL": product page URL
  - "_platform": platform name
  - "_text": pre-fetched page text (optional, skips re-fetching)
  - any pre-filled COLUMNS fields from the search API/page
"""

import re
import time
import requests
from bs4 import BeautifulSoup

_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
_HEADERS = {
    "User-Agent": _UA,
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8",
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    "Referer": "https://www.google.com",
}
_TIMEOUT = 15


# ── 중고나라 (joongna.com) — 가장 안정적 ────────────────────────────────────

def search_joongna(keyword: str, limit: int) -> list[dict]:
    """중고나라 검색 결과에서 상품 URL 수집. 페이지네이션 지원."""
    results: list[dict] = []
    seen: set[str] = set()
    page = 1

    while len(results) < limit:
        try:
            resp = requests.get(
                f"https://web.joongna.com/search/{keyword}",
                params={"page": page},
                headers=_HEADERS,
                timeout=_TIMEOUT,
            )
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "lxml")
            links = [
                a["href"]
                for a in soup.find_all("a", href=re.compile(r"^/product/\d+"))
            ]
        except Exception:
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
        if new_count < 5:   # 마지막 페이지 근처
            break
        time.sleep(0.8)

    return results[:limit]


# ── 헬로마켓 (hellomarket.com) ────────────────────────────────────────────────

def search_hellomarket(keyword: str, limit: int) -> list[dict]:
    """헬로마켓 검색 결과에서 상품 URL 수집."""
    results: list[dict] = []
    seen: set[str] = set()
    page = 1

    while len(results) < limit:
        try:
            resp = requests.get(
                "https://www.hellomarket.com/search",
                params={"q": keyword, "page": page},
                headers=_HEADERS,
                timeout=_TIMEOUT,
            )
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "lxml")
            links = [
                a["href"]
                for a in soup.find_all("a", href=re.compile(r"/item/\d+"))
            ]
        except Exception:
            break

        if not links:
            break

        new_count = 0
        for href in links:
            # "/item/12345?..." → clean
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
        time.sleep(0.8)

    return results[:limit]


# ── 번개장터 — Playwright 헤드리스 브라우저 ──────────────────────────────────

def search_bunjang(keyword: str, limit: int) -> list[dict]:
    """번개장터 검색. Playwright(헤드리스 크롬)로 JS 렌더링 후 링크 추출."""
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
                user_agent=_UA,
                viewport={"width": 1280, "height": 900},
            )
            page = ctx.new_page()

            # 네트워크 API 가로채기 시도
            api_items: list[dict] = []

            def on_response(resp):
                ct = resp.headers.get("content-type", "")
                if "json" in ct and ("find" in resp.url or "search" in resp.url or "product" in resp.url.lower()):
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
                # API 인터셉트 성공
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
                # HTML에서 링크 추출 시도
                content = page.content()
                pids = list(dict.fromkeys(re.findall(r"/products/(\d+)", content)))
                for pid in pids[:limit]:
                    url = f"https://bunjang.co.kr/products/{pid}"
                    if url not in seen:
                        seen.add(url)
                        results.append({"출처_URL": url, "_platform": "번개장터", "_text": None})

            browser.close()
    except Exception:
        pass

    return results[:limit]


# ── 당근마켓 — Playwright 헤드리스 브라우저 ──────────────────────────────────

def search_daangn(keyword: str, limit: int) -> list[dict]:
    """당근마켓 검색. Playwright로 JS 렌더링 후 article 링크 추출."""
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
                user_agent=_UA,
                viewport={"width": 1280, "height": 900},
            )
            page = ctx.new_page()
            page.goto(
                f"https://www.daangn.com/search/{keyword}",
                wait_until="networkidle",
                timeout=30000,
            )
            page.wait_for_timeout(5000)

            # 스크롤해서 더 로드
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

            browser.close()
    except Exception:
        pass

    return results[:limit]


# ── 네이버 카페 검색 API (공식, 무료) ──────────────────────────────────────

def search_naver_cafe(
    keyword: str,
    limit: int,
    client_id: str = "",
    client_secret: str = "",
) -> list[dict]:
    """
    네이버 카페 검색 API로 에어컨 중고 글 수집.
    중고나라(joonggonara) 카페에서 키워드 검색.
    developers.naver.com에서 무료 API 키 발급 필요.
    """
    import config as _cfg
    cid = client_id or _cfg.NAVER_CLIENT_ID
    secret = client_secret or _cfg.NAVER_CLIENT_SECRET

    if not cid or not secret:
        return []

    results: list[dict] = []
    seen: set[str] = set()
    start = 1
    display = 100  # 회당 최대

    while len(results) < limit:
        n = min(display, limit - len(results))
        try:
            resp = requests.get(
                "https://openapi.naver.com/v1/search/cafearticle.json",
                params={
                    "query": f"{keyword} 중고",
                    "display": n,
                    "start": start,
                    "sort": "date",
                    "cafeid": "joonggonara",   # 중고나라 카페로 한정
                },
                headers={
                    "X-Naver-Client-Id": cid,
                    "X-Naver-Client-Secret": secret,
                },
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            break

        items = data.get("items", [])
        if not items:
            break

        for item in items:
            link = item.get("link", "")
            if not link or link in seen:
                continue
            seen.add(link)

            # HTML 태그 제거
            title = re.sub(r"<[^>]+>", "", item.get("title", ""))
            desc = re.sub(r"<[^>]+>", "", item.get("description", ""))
            text = f"{title}\n{desc}".strip()

            results.append({
                "출처_URL": link,
                "_platform": "네이버 카페 중고나라",
                "_text": text,   # title+desc → Claude가 추출 (페이지 재접속 불필요)
            })

        start += display
        if len(items) < display:
            break
        time.sleep(0.3)

    return results[:limit]


# ── 헬퍼 ──────────────────────────────────────────────────────────────────────

def _to_int(val) -> int | None:
    if val is None:
        return None
    try:
        return int(str(val).replace(",", "").replace("원", "").strip())
    except (ValueError, TypeError):
        return None


PLATFORM_CRAWLERS: dict[str, callable] = {
    "중고나라": search_joongna,
    "헬로마켓": search_hellomarket,
    "번개장터": search_bunjang,
    "당근마켓": search_daangn,
    "네이버 카페 중고나라": search_naver_cafe,
}

# 봇 방지로 인해 결과가 제한되거나 없을 수 있는 플랫폼
LIMITED_PLATFORMS = {"번개장터", "당근마켓"}
