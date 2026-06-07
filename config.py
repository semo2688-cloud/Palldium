import os
from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
NAVER_CLIENT_ID = os.getenv("NAVER_CLIENT_ID", "")
NAVER_CLIENT_SECRET = os.getenv("NAVER_CLIENT_SECRET", "")
EBAY_APP_ID = os.getenv("EBAY_APP_ID", "")
EBAY_CERT_ID = os.getenv("EBAY_CERT_ID", "")
MODEL_NAME = "claude-3-5-haiku-20241022"
MAX_TOKENS = 512
RATE_LIMIT_DELAY_SEC = 1.5
REQUEST_TIMEOUT_SEC = 15
MAX_PAGE_TEXT_CHARS = 6000
MIN_PAGE_TEXT_CHARS = 200

COLUMNS = [
    "플랫폼", "브랜드", "모델명", "형태", "연식",
    "가격", "상태", "이미지_URL", "지역", "출처_URL", "비고"
]


def validate_api_key() -> None:
    if not ANTHROPIC_API_KEY or ANTHROPIC_API_KEY == "your_key_here":
        raise ValueError(
            "ANTHROPIC_API_KEY가 설정되지 않았습니다.\n"
            ".env 파일에 ANTHROPIC_API_KEY=sk-ant-... 형식으로 입력하세요."
        )
