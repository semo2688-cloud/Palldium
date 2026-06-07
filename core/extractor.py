import json
import re
import anthropic
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
import config

_SYSTEM_PROMPT = """당신은 한국 중고 에어컨 거래 데이터를 정제하는 전문 데이터 추출 AI입니다.
제공된 상품 페이지 텍스트에서 정확히 11개 항목을 추출하고, 반드시 JSON 형식으로만 응답하세요.
JSON 외의 어떠한 텍스트도 출력하지 마세요. 마크다운 코드 블록(```)도 사용하지 마세요.
개인정보(전화번호, 주소, 이름 등)는 절대 포함하지 마세요."""

_USER_PROMPT_TEMPLATE = """플랫폼: {platform}
출처 URL: {url}

--- 상품 페이지 텍스트 시작 ---
{page_text}
--- 상품 페이지 텍스트 끝 ---

다음 JSON 형식으로 응답하세요. 알 수 없는 항목은 null로 표시하세요:

{{
  "플랫폼": "{platform}",
  "브랜드": "LG 또는 삼성 또는 대우 또는 캐리어 또는 위닉스 또는 기타 또는 null",
  "모델명": "정확한 모델 번호 (예: FQ18VDABH) 또는 null",
  "형태": "벽걸이형 또는 스탠드형 또는 천장형 또는 창문형 또는 이동형 또는 시스템에어컨 또는 null",
  "연식": "4자리 연도 숫자 (예: 2019) 또는 null",
  "가격": "숫자만, 원 단위 (예: 150000). 만원 단위면 변환 (15만원 → 150000) 또는 null",
  "상태": "미사용 또는 거의새것 또는 좋음 또는 보통 또는 나쁨 또는 null",
  "이미지_URL": "첫 번째 상품 이미지 URL 또는 null",
  "지역": "시/구 단위 지역명 (예: 서울 강남구) 또는 null",
  "출처_URL": "{url}",
  "비고": "에어컨 상태, 수리이력, 포함품목 등 유용한 정보 요약 (최대 100자) 또는 null"
}}

{custom_instruction}"""


def extract_fields(
    url: str,
    platform: str,
    page_text: str,
    custom_instruction: str = "",
    api_key: str = "",
) -> dict:
    """Returns a dict with 11 fields, or {"error": "...", "출처_URL": url} on failure."""
    if page_text.startswith("__FETCH_ERROR__"):
        return {"error": page_text.replace("__FETCH_ERROR__: ", ""), "출처_URL": url}

    key = api_key or config.ANTHROPIC_API_KEY
    client = anthropic.Anthropic(api_key=key)

    is_thin = len(page_text) < config.MIN_PAGE_TEXT_CHARS
    note_suffix = " [페이지_로드_불완전]" if is_thin else ""

    prompt = _USER_PROMPT_TEMPLATE.format(
        platform=platform,
        url=url,
        page_text=page_text or "(페이지 내용을 가져오지 못했습니다)",
        custom_instruction=custom_instruction or "",
    )

    try:
        raw = _call_claude(client, prompt)
    except Exception as e:
        return {"error": str(e), "출처_URL": url}

    data = _parse_response(raw)
    if "error" in data:
        return data

    data = _validate_and_clean(data, url, platform, note_suffix)
    return data


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type(anthropic.RateLimitError),
)
def _call_claude(client: anthropic.Anthropic, prompt: str) -> str:
    response = client.messages.create(
        model=config.MODEL_NAME,
        max_tokens=config.MAX_TOKENS,
        temperature=0,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text


def _parse_response(content: str) -> dict:
    content = content.strip()

    # 1st attempt: direct parse
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass

    # 2nd attempt: extract JSON substring
    match = re.search(r"\{.*\}", content, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    return {"error": f"JSON 파싱 실패: {content[:200]}"}


def _validate_and_clean(data: dict, url: str, platform: str, note_suffix: str) -> dict:
    data["출처_URL"] = url
    data["플랫폼"] = platform

    # Normalize price: "15만원" → 150000
    price = data.get("가격")
    if isinstance(price, str):
        price = price.replace(",", "").replace(" ", "")
        if "만" in price:
            try:
                num = float(re.sub(r"[^\d.]", "", price.split("만")[0]))
                price = int(num * 10000)
            except ValueError:
                price = None
        else:
            digits = re.sub(r"\D", "", price)
            price = int(digits) if digits else None
    data["가격"] = price

    # Append page-load warning to 비고
    if note_suffix:
        existing = data.get("비고") or ""
        data["비고"] = (existing + note_suffix).strip()

    # Ensure all 11 columns exist
    for col in config.COLUMNS:
        data.setdefault(col, None)

    return data
