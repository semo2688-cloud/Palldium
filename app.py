import time
import streamlit as st
import config
from core import crawler, fetcher, extractor, deduplicator, exporter
from core.crawler import LIMITED_PLATFORMS, PLATFORM_TIERS
from core.logger import load_recent_failures

st.set_page_config(
    page_title="중고 에어컨 데이터 수집 도구",
    page_icon="❄️",
    layout="wide",
)

st.title("중고 에어컨 데이터 수집 도구")
st.caption("3단계 수집 파이프라인: 1차(API) → 2차(HTML) → 3차(Playwright/수동)")

# ── Sidebar: API Keys ─────────────────────────────────────────────────────────
with st.sidebar:
    st.header("설정")

    # Anthropic
    api_key_input = st.text_input(
        "Anthropic API 키",
        type="password",
        placeholder="sk-ant-...",
        help=".env 파일에 ANTHROPIC_API_KEY가 있으면 비워도 됩니다",
    )
    effective_key = api_key_input.strip() or config.ANTHROPIC_API_KEY

    st.divider()

    # Naver — Tier 1
    st.markdown("**네이버 카페 API** *(Tier 1 — 무료)*")
    st.caption("developers.naver.com → 애플리케이션 등록 → 검색 API 선택")
    naver_client_id = st.text_input(
        "Naver Client ID", type="password",
        value=config.NAVER_CLIENT_ID, placeholder="네이버 Client ID",
    )
    naver_client_secret = st.text_input(
        "Naver Client Secret", type="password",
        value=config.NAVER_CLIENT_SECRET, placeholder="네이버 Client Secret",
    )

    st.divider()

    # eBay — Tier 1
    st.markdown("**eBay Browse API** *(Tier 1 — 무료)*")
    st.caption("developer.ebay.com → My Keys → App ID / Cert ID 복사")
    ebay_app_id = st.text_input(
        "eBay App ID", type="password",
        value=config.EBAY_APP_ID, placeholder="eBay App ID (Client ID)",
    )
    ebay_cert_id = st.text_input(
        "eBay Cert ID", type="password",
        value=config.EBAY_CERT_ID, placeholder="eBay Cert ID (Client Secret)",
    )

    st.divider()
    st.markdown(
        "**플랫폼 티어 가이드**\n"
        "- 🟢 Tier 1 — API 기반, 안정적\n"
        "- 🟡 Tier 2 — HTML 스크래핑\n"
        "- 🔴 Tier 3 — Playwright, 봇방지"
    )
    st.caption("권장: Tier 1·2 → 70–80%, Tier 3 → 10–20%")

# ── Zone 2: Input Form ────────────────────────────────────────────────────────
TIER_BADGE = {1: "🟢", 2: "🟡", 3: "🔴"}
platform_options = list(crawler.PLATFORM_CRAWLERS.keys())
platform_labels = {
    p: f"{TIER_BADGE[PLATFORM_TIERS[p]]} {p}" for p in platform_options
}

with st.form("crawl_form"):
    col_kw, col_count = st.columns([3, 1])
    with col_kw:
        keyword = st.text_input(
            "검색 키워드",
            value="에어컨",
            placeholder="예: LG 에어컨, 벽걸이 에어컨, 삼성 스탠드 에어컨",
        )
    with col_count:
        per_limit = st.number_input(
            "플랫폼당 수집 수",
            min_value=10, max_value=300, value=50, step=10,
            help="각 플랫폼에서 최대 몇 개의 상품을 수집할지 설정합니다",
        )

    platforms = st.multiselect(
        "크롤링할 플랫폼",
        options=platform_options,
        default=["eBay", "네이버 카페 중고나라", "중고나라", "헬로마켓"],
        format_func=lambda p: platform_labels[p],
        help="🟢 Tier 1(API) → 🟡 Tier 2(HTML) → 🔴 Tier 3(Playwright) 순으로 안정적입니다",
    )

    # Tier 3 warning
    limited_selected = [p for p in (platforms or []) if p in LIMITED_PLATFORMS]
    if limited_selected:
        st.warning(
            f"**{', '.join(limited_selected)}** 은(는) 봇 방지로 인해 결과가 제한될 수 있습니다. "
            "Tier 1·2 플랫폼을 우선 사용하세요."
        )

    # Missing API key hints
    hints = []
    if "eBay" in (platforms or []) and not (ebay_app_id.strip() and ebay_cert_id.strip()):
        hints.append("**eBay**: 사이드바에 App ID / Cert ID 입력 필요 (developer.ebay.com 무료)")
    if "네이버 카페 중고나라" in (platforms or []) and not (naver_client_id.strip() and naver_client_secret.strip()):
        hints.append("**네이버 카페 중고나라**: 사이드바에 Client ID / Secret 입력 필요 (developers.naver.com 무료)")
    if hints:
        st.info("\n\n".join(hints))

    custom_instruction = st.text_area(
        "추가 추출 지시사항 (선택 — Claude에게 전달됩니다)",
        height=60,
        placeholder="예: 냉방 BTU 수치가 있으면 비고에 포함해주세요",
    )

    submitted = st.form_submit_button("크롤링 시작", type="primary", use_container_width=True)

# ── Zone 2b: 수동 보완 (3차) ──────────────────────────────────────────────────
with st.expander("🔧 수동 보완 루트 (3차) — URL 직접 입력"):
    st.caption(
        "봇 방지로 수집하지 못한 상품 URL을 직접 붙여넣으세요. "
        "한 줄에 하나씩 입력하면 자동 크롤링 결과에 추가됩니다."
    )
    manual_urls_raw = st.text_area(
        "상품 URL 목록",
        height=120,
        placeholder="https://bunjang.co.kr/products/12345\nhttps://www.daangn.com/articles/67890",
    )
    manual_submit = st.button("수동 URL 추가하여 수집", use_container_width=False)

# ── Phase processing ──────────────────────────────────────────────────────────
def _parse_manual_urls(raw: str) -> list[dict]:
    items = []
    for line in raw.splitlines():
        url = line.strip()
        if url.startswith("http"):
            items.append({"출처_URL": url, "_platform": "수동입력", "_text": None})
    return items


def _run_pipeline(all_items: list[dict], kw: str) -> None:
    if not all_items:
        st.error("수집된 상품이 없습니다.")
        return

    phase2_bar = st.progress(0)
    phase2_status = st.empty()
    records: list[dict] = []
    failed: list[dict] = []

    for i, item in enumerate(all_items):
        url = item["출처_URL"]
        platform = item.get("_platform") or fetcher.detect_platform(url)
        page_text = item.get("_text")

        phase2_status.text(f"[2/2] 추출 중: {i+1}/{len(all_items)} — {platform} — {url[:50]}...")
        phase2_bar.progress((i + 1) / len(all_items))

        try:
            if page_text is None:
                _, page_text = fetcher.fetch_page(url)

            record = extractor.extract_fields(
                url=url,
                platform=platform,
                page_text=page_text,
                custom_instruction=custom_instruction,
                api_key=effective_key,
            )

            if "error" in record:
                failed.append(record)
            else:
                for key in config.COLUMNS:
                    if record.get(key) is None and key in item and not key.startswith("_"):
                        record[key] = item[key]
                records.append(record)

        except Exception as e:
            failed.append({"출처_URL": url, "error": str(e)})

        time.sleep(config.RATE_LIMIT_DELAY_SEC)

    phase2_status.text("중복 제거 중...")
    records, removed = deduplicator.remove_duplicates(records)

    phase2_bar.progress(1.0)
    phase2_status.empty()

    st.session_state["results"] = records
    st.session_state["failed"] = failed
    st.session_state["removed"] = removed
    st.session_state["keyword"] = kw


if submitted:
    if not effective_key or effective_key == "your_key_here":
        st.error("ANTHROPIC_API_KEY가 설정되지 않았습니다.")
        st.stop()
    if not platforms:
        st.warning("플랫폼을 하나 이상 선택해주세요.")
        st.stop()
    if not keyword.strip():
        st.warning("검색 키워드를 입력해주세요.")
        st.stop()

    st.info(f"'{keyword}' 키워드로 {len(platforms)}개 플랫폼에서 크롤링합니다. (플랫폼당 최대 {per_limit}개)")

    # ── Phase 1: Crawl ────────────────────────────────────────────────────────
    phase1_bar = st.progress(0)
    phase1_status = st.empty()
    all_items: list[dict] = []

    for pi, platform in enumerate(platforms):
        tier = PLATFORM_TIERS.get(platform, 2)
        phase1_status.text(
            f"[1/2] {TIER_BADGE[tier]} {platform} 검색 중..."
        )
        phase1_bar.progress((pi + 0.5) / len(platforms))

        crawl_fn = crawler.PLATFORM_CRAWLERS.get(platform)
        if crawl_fn is None:
            continue
        try:
            if platform == "eBay":
                items = crawl_fn(
                    keyword.strip(), int(per_limit),
                    app_id=ebay_app_id.strip(),
                    cert_id=ebay_cert_id.strip(),
                )
            elif platform == "네이버 카페 중고나라":
                items = crawl_fn(
                    keyword.strip(), int(per_limit),
                    client_id=naver_client_id.strip(),
                    client_secret=naver_client_secret.strip(),
                )
            else:
                items = crawl_fn(keyword.strip(), int(per_limit))
            all_items.extend(items)
        except Exception as e:
            st.warning(f"{platform} 크롤링 중 오류: {e}")

        phase1_bar.progress((pi + 1) / len(platforms))
        time.sleep(0.5)

    # append manual URLs if any
    manual_items = _parse_manual_urls(manual_urls_raw or "")
    if manual_items:
        all_items.extend(manual_items)

    phase1_bar.progress(1.0)
    phase1_status.text(f"[1/2] 완료 — 총 {len(all_items)}개 상품 발견 (수동 {len(manual_items)}개 포함)")

    _run_pipeline(all_items, keyword.strip())

elif manual_submit and manual_urls_raw.strip():
    if not effective_key or effective_key == "your_key_here":
        st.error("ANTHROPIC_API_KEY가 설정되지 않았습니다.")
        st.stop()
    manual_items = _parse_manual_urls(manual_urls_raw)
    if not manual_items:
        st.warning("유효한 URL을 입력해주세요 (http로 시작).")
    else:
        st.info(f"수동 입력 URL {len(manual_items)}개를 처리합니다.")
        # Keep existing results and append
        existing = st.session_state.get("results", [])
        _run_pipeline(manual_items, st.session_state.get("keyword", "수동"))
        if existing:
            merged = existing + st.session_state.get("results", [])
            merged, removed = deduplicator.remove_duplicates(merged)
            st.session_state["results"] = merged
            st.session_state["removed"] = st.session_state.get("removed", 0) + removed

# ── Render results ────────────────────────────────────────────────────────────
if "results" in st.session_state:
    records = st.session_state["results"]
    failed = st.session_state["failed"]
    removed = st.session_state["removed"]
    saved_keyword = st.session_state.get("keyword", "")

    st.divider()
    col_a, col_b, col_c, col_d = st.columns(4)
    col_a.metric("수집 완료", f"{len(records)}개")
    col_b.metric("중복 제거", f"{removed}개")
    col_c.metric("실패", f"{len(failed)}개")
    col_d.metric("검색어", saved_keyword)

    if records:
        import pandas as pd
        df = pd.DataFrame(records, columns=config.COLUMNS)
        st.dataframe(
            df,
            use_container_width=True,
            height=420,
            column_config={
                "이미지_URL": st.column_config.LinkColumn("이미지"),
                "출처_URL": st.column_config.LinkColumn("출처"),
                "가격": st.column_config.NumberColumn("가격", format="%d원"),
            },
        )

        st.divider()
        dl_col1, dl_col2 = st.columns(2)
        with dl_col1:
            st.download_button(
                label="Excel 다운로드 (.xlsx)",
                data=exporter.to_excel_bytes(records),
                file_name=f"중고에어컨_{saved_keyword}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )
        with dl_col2:
            st.download_button(
                label="CSV 다운로드 (.csv)",
                data=exporter.to_csv_bytes(records),
                file_name=f"중고에어컨_{saved_keyword}.csv",
                mime="text/csv",
                use_container_width=True,
            )
    else:
        st.warning("추출에 성공한 데이터가 없습니다.")

    if failed:
        with st.expander(f"실패한 항목 {len(failed)}개 보기"):
            for f in failed:
                st.write(f"- **{f.get('출처_URL', '알 수 없음')}**")
                st.caption(f"  오류: {f.get('error', '알 수 없는 오류')}")

# ── 실패 로그 뷰어 ─────────────────────────────────────────────────────────────
st.divider()
with st.expander("📋 실패 로그 보기 (logs/failures.jsonl)"):
    failures = load_recent_failures(limit=50)
    if not failures:
        st.caption("기록된 실패 없음")
    else:
        import pandas as pd
        df_fail = pd.DataFrame(failures)
        # Count by platform
        platform_counts = df_fail.groupby("platform").size().reset_index(name="실패 횟수")
        st.markdown("**플랫폼별 실패 횟수**")
        st.dataframe(platform_counts, use_container_width=True, hide_index=True)
        st.markdown("**최근 실패 목록**")
        st.dataframe(
            df_fail[["ts", "platform", "query", "status_code", "error"]].tail(20),
            use_container_width=True,
            hide_index=True,
        )
