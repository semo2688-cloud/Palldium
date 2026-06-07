"""
FastAPI entry point for Vercel deployment.
Each endpoint must complete within 60s (Vercel Pro) / 30s (Hobby).
Playwright-based crawlers (번개장터, 당근마켓) are unavailable on Vercel.
"""
import os
import sys

# Ensure project root is in path so core/ imports work on Vercel
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel
from typing import Optional

_HTML_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")

from core import crawler, fetcher, extractor, exporter
from core.crawler import PLATFORM_CRAWLERS, PLATFORM_TIERS, LIMITED_PLATFORMS
import config

app = FastAPI(title="중고 에어컨 데이터 수집 API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── HTML 서빙 ─────────────────────────────────────────────────────────────────

@app.get("/")
def root():
    with open(_HTML_FILE, encoding="utf-8") as f:
        return HTMLResponse(content=f.read())


# ── Request Models ────────────────────────────────────────────────────────────

class CrawlRequest(BaseModel):
    keyword: str
    platform: str
    limit: int = 30
    naver_client_id: str = ""
    naver_client_secret: str = ""
    ebay_app_id: str = ""
    ebay_cert_id: str = ""


class ExtractRequest(BaseModel):
    url: str
    platform: str
    page_text: Optional[str] = None
    anthropic_api_key: str = ""
    custom_instruction: str = ""


class ExportRequest(BaseModel):
    records: list[dict]


# ── API Endpoints ─────────────────────────────────────────────────────────────

@app.get("/api/platforms")
def get_platforms():
    return {
        "platforms": [
            {
                "name": p,
                "tier": PLATFORM_TIERS[p],
                "limited": p in LIMITED_PLATFORMS,
            }
            for p in PLATFORM_CRAWLERS.keys()
        ]
    }


@app.post("/api/crawl")
def crawl_platform(req: CrawlRequest):
    crawl_fn = PLATFORM_CRAWLERS.get(req.platform)
    if not crawl_fn:
        raise HTTPException(status_code=400, detail=f"Unknown platform: {req.platform}")

    try:
        if req.platform == "eBay":
            items = crawl_fn(
                req.keyword, req.limit,
                app_id=req.ebay_app_id or config.EBAY_APP_ID,
                cert_id=req.ebay_cert_id or config.EBAY_CERT_ID,
            )
        elif req.platform == "네이버 카페 중고나라":
            items = crawl_fn(
                req.keyword, req.limit,
                client_id=req.naver_client_id or config.NAVER_CLIENT_ID,
                client_secret=req.naver_client_secret or config.NAVER_CLIENT_SECRET,
            )
        else:
            items = crawl_fn(req.keyword, req.limit)
    except Exception as e:
        return {"items": [], "error": str(e), "count": 0}

    return {"items": items, "count": len(items)}


@app.post("/api/extract")
def extract_item(req: ExtractRequest):
    api_key = req.anthropic_api_key or config.ANTHROPIC_API_KEY
    if not api_key:
        raise HTTPException(status_code=400, detail="ANTHROPIC_API_KEY가 없습니다.")

    page_text = req.page_text
    if not page_text:
        _, page_text = fetcher.fetch_page(req.url)

    record = extractor.extract_fields(
        url=req.url,
        platform=req.platform,
        page_text=page_text,
        custom_instruction=req.custom_instruction,
        api_key=api_key,
    )
    return record


@app.post("/api/export/excel")
def export_excel(req: ExportRequest):
    if not req.records:
        raise HTTPException(status_code=400, detail="데이터가 없습니다.")
    try:
        xlsx_bytes = exporter.to_excel_bytes(req.records)
        return Response(
            content=xlsx_bytes,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": "attachment; filename=aircon_data.xlsx"},
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/export/csv")
def export_csv(req: ExportRequest):
    if not req.records:
        raise HTTPException(status_code=400, detail="데이터가 없습니다.")
    try:
        csv_bytes = exporter.to_csv_bytes(req.records)
        return Response(
            content=csv_bytes,
            media_type="text/csv; charset=utf-8-sig",
            headers={"Content-Disposition": "attachment; filename=aircon_data.csv"},
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/health")
def health():
    return {"status": "ok", "model": config.MODEL_NAME}
