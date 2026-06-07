import time
import streamlit as st
import config
from core import crawler, fetcher, extractor, deduplicator, exporter
from core.crawler import LIMITED_PLATFORMS

st.set_page_config(
    page_title="중고 에어컨 데이터 수집 도구",
    page_icon="❄️",
    layout="wide",
)

# ── Zone 1: Header ────────────────────────────────────────────────────────────
st.title("중고 에어컨 데이터 수집 도구")
st.caption("번개장터 · 중고나라 · 당근마켓 · 네이버 중고거래를 자동 크롤링하여 11개 항목을 추출합니다")

# ── Sidebar: Settings ─────────────────────────────────────────────────────────
with st.sidebar:
    st.header("설정")
    api_key_input = st.text_input(
        "Anthropic API 키",
        type="password",
        placeholder="sk-ant-...",
        help=".env 파일에 ANTHROPIC_API_KEY가 있으면 비워도 됩니다",
    )
    effective_key = api_key_input.strip() or config.ANTHROPIC_API_KEY

    st.divider()
    st.markdown("**네이버 카페 API 키** (선택)")
    st.caption(
        "[네이버 개발자센터](https://developers.naver.com)에서 무료 발급 "
        "→ 애플리케이션 등록 → 검색 API 선택 → Client ID/Secret 복사"
    )
    naver_client_id = st.text_input(
        "Naver Client ID",
        type="password",
        value=config.NAVER_CLIENT_ID,
        placeholder="네이버 Client ID",
    )
    naver_client_secret = st.text_input(
        "Naver Client Secret",
        type="password",
        value=config.NAVER_CLIENT_SECRET,
        placeholder="네이버 Client Secret",
    )

    st.divider()
    st.markdown("**사용 방법**")
    st.markdown(
        "1. API 키 입력 (없으면 .env 사용)\n"
        "2. 검색 키워드와 플랫폼 선택\n"
        "3. 크롤링 시작 버튼 클릭\n"
        "4. 결과 확인 후 다운로드"
    )
    st.divider()
    st.caption("지원 플랫폼: 번개장터, 중고나라, 헬로마켓, 네이버 카페 중고나라, 당근마켓")

# ── Zone 2: Input Form ────────────────────────────────────────────────────────
with st.form("crawl_form"):
    col_kw, col_count = st.columns([3, 1])
    with col_kw:
        keyword = st.text_input(
            "검색 키워드",
            value="에어컨",
            placeholder="예: 에어컨, LG 에어컨, 벽걸이 에어컨, 삼성 스탠드 에어컨",
        )
    with col_count:
        per_limit = st.number_input(
            "플랫폼당 수집 수",
            min_value=10,
            max_value=300,
            value=50,
            step=10,
            help="각 플랫폼에서 최대 몇 개의 상품을 수집할지 설정합니다",
        )

    platforms = st.multiselect(
        "크롤링할 플랫폼",
        options=list(crawler.PLATFORM_CRAWLERS.keys()),
        default=["중고나라", "헬로마켓"],
        help="수집할 플랫폼을 선택하세요. 여러 개 선택 가능합니다.",
    )

    # 봇 방지 플랫폼 / API 키 미설정 경고
    limited_selected = [p for p in (platforms or []) if p in LIMITED_PLATFORMS]
    if limited_selected:
        st.warning(
            f"**{', '.join(limited_selected)}** 은(는) 봇 방지 시스템으로 인해 수집 결과가 없거나 제한될 수 있습니다. "
            "**중고나라**, **헬로마켓** 은 안정적으로 동작합니다."
        )
    if "네이버 카페 중고나라" in (platforms or []) and not (naver_client_id.strip() and naver_client_secret.strip()):
        st.info(
            "**네이버 카페 중고나라**를 사용하려면 사이드바에 Naver Client ID / Secret을 입력하세요. "
            "[네이버 개발자센터](https://developers.naver.com)에서 무료 발급 가능합니다."
        )

    custom_instruction = st.text_area(
        "추가 추출 지시사항 (선택 — Claude에게 전달됩니다)",
        height=70,
        placeholder="예: 냉방 BTU 수치가 있으면 비고에 포함해주세요",
    )

    submitted = st.form_submit_button("크롤링 시작", type="primary", use_container_width=True)

# ── Zone 3 & 4: Processing + Results ─────────────────────────────────────────
if submitted:
    if not effective_key or effective_key == "your_key_here":
        st.error("ANTHROPIC_API_KEY가 설정되지 않았습니다. 사이드바에 API 키를 입력하거나 .env 파일을 확인하세요.")
        st.stop()

    if not platforms:
        st.warning("플랫폼을 하나 이상 선택해주세요.")
        st.stop()

    if not keyword.strip():
        st.warning("검색 키워드를 입력해주세요.")
        st.stop()

    # ── Phase 1: Crawl search results ────────────────────────────────────────
    st.info(f"'{keyword}' 키워드로 {len(platforms)}개 플랫폼에서 크롤링합니다. (플랫폼당 최대 {per_limit}개)")

    phase1_bar = st.progress(0)
    phase1_status = st.empty()
    all_items: list[dict] = []

    for pi, platform in enumerate(platforms):
        phase1_status.text(f"[1/2] {platform} 검색 중...")
        phase1_bar.progress((pi + 0.5) / len(platforms))

        crawl_fn = crawler.PLATFORM_CRAWLERS.get(platform)
        if crawl_fn is None:
            continue
        try:
            if platform == "네이버 카페 중고나라":
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

    phase1_bar.progress(1.0)
    phase1_status.text(f"[1/2] 완료 — 총 {len(all_items)}개 상품 발견")

    if not all_items:
        st.error("크롤링 결과가 없습니다. 키워드나 플랫폼을 바꿔보세요.")
        st.stop()

    # ── Phase 2: Fetch + Claude extract ──────────────────────────────────────
    phase2_bar = st.progress(0)
    phase2_status = st.empty()
    records: list[dict] = []
    failed: list[dict] = []

    for i, item in enumerate(all_items):
        url = item["출처_URL"]
        platform = item.get("_platform") or fetcher.detect_platform(url)
        page_text = item.get("_text")  # pre-fetched text from API (e.g., Bunjang)

        phase2_status.text(f"[2/2] 추출 중: {i + 1}/{len(all_items)} — {platform} — {url[:55]}...")
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
                # Merge pre-filled fields from crawler (only for null fields)
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
    st.session_state["keyword"] = keyword.strip()

# ── Render results from session state ────────────────────────────────────────
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
        st.warning("추출에 성공한 데이터가 없습니다. 실패 목록을 확인하세요.")

    if failed:
        with st.expander(f"실패한 항목 {len(failed)}개 보기"):
            for f in failed:
                st.write(f"- **{f.get('출처_URL', '알 수 없음')}**")
                st.caption(f"  오류: {f.get('error', '알 수 없는 오류')}")
