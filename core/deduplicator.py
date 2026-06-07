import re
from urllib.parse import urlparse, urlunparse

BRAND_ALIASES = {
    "엘지": "LG",
    "엘지전자": "LG",
    "LG전자": "LG",
    "삼성전자": "삼성",
    "삼성 전자": "삼성",
    "대우전자": "대우",
    "캐리어에어컨": "캐리어",
}


def remove_duplicates(records: list[dict]) -> tuple[list[dict], int]:
    """Returns (deduplicated_records, removed_count)."""
    initial_count = len(records)

    # Pass 1: exact URL dedup
    seen_urls: set[str] = set()
    pass1: list[dict] = []
    for rec in records:
        norm = _normalize_url(rec.get("출처_URL") or "")
        if norm and norm in seen_urls:
            continue
        if norm:
            seen_urls.add(norm)
        pass1.append(rec)

    # Pass 2: semantic dedup (same brand+model+price+form)
    seen_keys: set[tuple] = set()
    pass2: list[dict] = []
    for rec in pass1:
        key = _composite_key(rec)
        if key is None:
            pass2.append(rec)
            continue
        if key in seen_keys:
            # Replace existing entry if current record has fewer nulls
            existing_idx = next(
                (i for i, r in enumerate(pass2) if _composite_key(r) == key), None
            )
            if existing_idx is not None:
                existing_nulls = _count_nulls(pass2[existing_idx])
                current_nulls = _count_nulls(rec)
                if current_nulls < existing_nulls:
                    pass2[existing_idx] = rec
        else:
            seen_keys.add(key)
            pass2.append(rec)

    removed = initial_count - len(pass2)
    return pass2, removed


def _normalize_url(url: str) -> str:
    if not url:
        return ""
    try:
        parsed = urlparse(url.strip().lower())
        normalized = urlunparse((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", "", ""))
        return normalized
    except Exception:
        return url.strip().lower()


def _normalize_brand(brand) -> str:
    if not brand:
        return ""
    brand = str(brand).strip()
    return BRAND_ALIASES.get(brand, brand).upper()


def _normalize_model(model) -> str:
    if not model:
        return ""
    return re.sub(r"[\s\-_]", "", str(model)).upper()


def _round_price(price) -> int | None:
    if price is None:
        return None
    try:
        return round(int(price) / 1000) * 1000
    except (ValueError, TypeError):
        return None


def _composite_key(rec: dict) -> tuple | None:
    brand = _normalize_brand(rec.get("브랜드"))
    model = _normalize_model(rec.get("모델명"))
    price = _round_price(rec.get("가격"))
    form = rec.get("형태") or ""

    if not brand and not model:
        return None
    return (brand, model, price, form)


def _count_nulls(rec: dict) -> int:
    return sum(1 for v in rec.values() if v is None)
