"""
Warranty FastAPI service — HP, Dell, Lenovo.

Endpoints:
  GET  /warranty/{serial}              - HP full lookup (all fields, Playwright)
  POST /warranty/bulk                  - HP batch full lookup
  GET  /warranty-check/{serial}        - HP date-only: { startDate, endDate (start+5yr) }
  POST /warranty-check/bulk            - HP batch date-only
  GET  /warranty-check/dell/{serial}   - Dell date-only via TechDirect API
  GET  /warranty-check/lenovo/{serial} - Lenovo date-only via Playwright scraper
  GET  /health                         - liveness check
  GET  /                               - frontend UI
"""

import asyncio
import os
from contextlib import asynccontextmanager
from typing import List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from playwright.async_api import async_playwright, Browser

from scraper import lookup_warranty
from scraper_fast import lookup_warranty_fast
from scraper_dell import lookup_warranty_dell
from scraper_lenovo import lookup_warranty_lenovo

# ── Browser singletons ────────────────────────────────────────────────────────
_browser: Browser | None = None          # Chromium — HP
_firefox:  Browser | None = None          # Firefox  — Lenovo (Chromium HTTP/2 blocked)
_playwright_ctx = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _browser, _firefox, _playwright_ctx
    _playwright_ctx = async_playwright()
    pw = await _playwright_ctx.__aenter__()
    _browser = await pw.chromium.launch(
        headless=True,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-infobars",
            "--window-size=1920,1080",
        ],
    )
    print("Chromium browser started.")
    _firefox = await pw.firefox.launch(headless=True)
    print("Firefox browser started.")
    yield
    await _browser.close()
    await _firefox.close()
    await _playwright_ctx.__aexit__(None, None, None)
    print("Browsers stopped.")


app = FastAPI(
    title="HP Warranty API",
    description="HP warranty lookups via Playwright. Hosted at hp.hidemybackground.com.",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

MAX_CONCURRENCY = int(os.getenv("MAX_CONCURRENCY", "3"))
_semaphore: asyncio.Semaphore | None = None


def get_semaphore() -> asyncio.Semaphore:
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(MAX_CONCURRENCY)
    return _semaphore


# ── Models ────────────────────────────────────────────────────────────────────
class BulkRequest(BaseModel):
    serial_numbers: List[str]
    country: Optional[str] = "us"
    max_concurrent: Optional[int] = None


class DateBulkRequest(BaseModel):
    serial_numbers: List[str]
    max_concurrent: Optional[int] = None


# ── Health ────────────────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    return {"status": "ok", "browser": _browser is not None and not _browser.is_connected() is False}


# ── Full Playwright lookup ────────────────────────────────────────────────────
@app.get("/warranty/{serial_number}")
async def warranty_single(serial_number: str, country: str = "us"):
    if not serial_number or len(serial_number) < 5:
        raise HTTPException(status_code=400, detail="Invalid serial number")
    async with get_semaphore():
        result = await lookup_warranty(_browser, serial_number.strip(), country)
    if result.get("error") and result.get("productName") is None:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@app.post("/warranty/bulk")
async def warranty_bulk(req: BulkRequest):
    if not req.serial_numbers:
        raise HTTPException(status_code=400, detail="serial_numbers must not be empty")
    if len(req.serial_numbers) > 200:
        raise HTTPException(status_code=400, detail="Maximum 200 serial numbers per request")

    limit = req.max_concurrent or MAX_CONCURRENCY
    sem = asyncio.Semaphore(limit)

    async def bounded(sn: str):
        async with sem:
            return await lookup_warranty(_browser, sn.strip(), req.country)

    results = await asyncio.gather(*[bounded(sn) for sn in req.serial_numbers])
    return {"count": len(results), "results": list(results)}


# ── Date-only lookup: /warranty-check/ ───────────────────────────────────────
# Returns { serialNumber, startDate, endDate (start+5yr) } only.
# Used by the PowerShell discovery script and the CSV frontend.
# Publicly accessible at https://hp.hidemybackground.com/warranty-check/{serial}

@app.get("/warranty-check/{serial_number}")
async def warranty_check_single(serial_number: str):
    if not serial_number or len(serial_number) < 5:
        raise HTTPException(status_code=400, detail="Invalid serial number")
    async with get_semaphore():
        result = await lookup_warranty_fast(_browser, serial_number.strip())
    if result.get("error") and result.get("startDate") is None:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@app.post("/warranty-check/bulk")
async def warranty_check_bulk(req: DateBulkRequest):
    if not req.serial_numbers:
        raise HTTPException(status_code=400, detail="serial_numbers must not be empty")
    if len(req.serial_numbers) > 200:
        raise HTTPException(status_code=400, detail="Maximum 200 serial numbers per request")

    limit = req.max_concurrent or MAX_CONCURRENCY
    sem = asyncio.Semaphore(limit)

    async def bounded(sn: str):
        async with sem:
            return await lookup_warranty_fast(_browser, sn.strip())

    results = await asyncio.gather(*[bounded(sn) for sn in req.serial_numbers])
    return {"count": len(results), "results": list(results)}


# ── Dell date-only lookup ─────────────────────────────────────────────────────
@app.get("/warranty-check/dell/{serial_number}")
async def warranty_check_dell(serial_number: str):
    if not serial_number or len(serial_number) < 5:
        raise HTTPException(status_code=400, detail="Invalid service tag")
    result = await lookup_warranty_dell(serial_number.strip())
    if result.get("error") and result.get("startDate") is None:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


# ── Lenovo date-only lookup ───────────────────────────────────────────────────
@app.get("/warranty-check/lenovo/{serial_number}")
async def warranty_check_lenovo(serial_number: str):
    if not serial_number or len(serial_number) < 5:
        raise HTTPException(status_code=400, detail="Invalid serial number")
    async with get_semaphore():
        result = await lookup_warranty_lenovo(_firefox, serial_number.strip())
    if result.get("error") and result.get("startDate") is None:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


# ── Frontend ──────────────────────────────────────────────────────────────────
app.mount("/static", StaticFiles(directory="frontend"), name="static")


@app.get("/")
async def serve_ui():
    return FileResponse("frontend/index.html")
