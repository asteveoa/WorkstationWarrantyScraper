"""
HP warranty scraper using Playwright.
Navigates support.hp.com, intercepts internal API responses,
and returns structured warranty data.
"""

import asyncio
from playwright.async_api import async_playwright, Browser

HP_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)
WARRANTY_CHECK_URL = "https://support.hp.com/us-en/checkwarranty/"
TIMEOUT_MS = 30000

# Ordered list of selectors to try for the serial input field
_INPUT_SELECTORS = [
    "#inputtextpfinder",
    "input[id*='pfinder']",
    "input[id*='serial']",
    "input[name*='serial']",
    "input[placeholder*='serial' i]",
    "input[type='text']:visible",
]

# Ordered list of selectors to try for the submit button
_SUBMIT_SELECTORS = [
    "#FindMyProduct",
    "button[id*='find' i]",
    "button[type='submit']",
    "input[type='submit']",
]


def _parse_result(serial: str, product_data: dict | None, warranty_data: dict | None) -> dict:
    result = {
        "serialNumber": serial.upper(),
        "productName": None,
        "productNumber": None,
        "description": None,
        "warrantyStatus": None,
        "warrantyStartDate": None,
        "warrantyEndDate": None,
        "warrantyType": None,
        "serviceType": None,
        "entitlements": [],
        "error": None,
    }

    if product_data:
        verify = (product_data.get("data") or {}).get("verifyResponse") or {}
        d = verify.get("data") or {}
        result["productName"]   = d.get("productName")
        result["productNumber"] = d.get("productNumber")
        result["description"]   = d.get("description")

    if warranty_data:
        devices = (warranty_data.get("data") or {}).get("devices") or []
        if devices:
            w = (devices[0].get("warranty") or {}).get("data") or {}
            result["warrantyStatus"]    = w.get("status")
            result["warrantyStartDate"] = (w.get("warrantyStartDate") or "")[:10] or None
            result["warrantyEndDate"]   = (w.get("warrantyEndDate") or "")[:10] or None
            result["warrantyType"]      = w.get("warrantyTypeDescription")
            result["serviceType"]       = w.get("serviceType")
            result["entitlements"] = [
                {
                    "warrantyType":  e.get("warrantyTypeDescription"),
                    "serviceType":   e.get("serviceType"),
                    "status":        e.get("status"),
                    "startDate":     (e.get("warrantyStartDate") or "")[:10] or None,
                    "endDate":       (e.get("warrantyEndDate") or "")[:10] or None,
                }
                for e in w.get("entitlements") or []
            ]

    if result["productName"] is None and result["warrantyStatus"] is None:
        result["error"] = "No data returned — serial number may be invalid or not found."

    return result


_STEALTH_SCRIPT = """
    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
    Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
    Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
    window.chrome = {runtime: {}};
"""


async def lookup_warranty(browser: Browser, serial: str, country: str = "us") -> dict:
    context = await browser.new_context(
        user_agent=HP_USER_AGENT,
        locale="en-US",
        viewport={"width": 1920, "height": 1080},
        extra_http_headers={
            "Accept-Language": "en-US,en;q=0.9",
        },
    )
    await context.add_init_script(_STEALTH_SCRIPT)
    page = await context.new_page()

    product_data: dict | None = None
    warranty_data: dict | None = None
    data_event = asyncio.Event()

    async def on_response(resp):
        nonlocal product_data, warranty_data
        url = resp.url
        try:
            if "searchresult" in url and "context=pdp" in url and resp.status == 200:
                product_data = await resp.json()
            elif "warranty/specs" in url and resp.status == 200:
                warranty_data = await resp.json()
                data_event.set()
        except Exception:
            pass

    page.on("response", on_response)

    try:
        # ── Strategy 1: navigate with serial in URL query param ───────────────
        # HP's page sometimes reads ?sn= and fires the API automatically,
        # bypassing the need to fill the form.
        direct_url = f"{WARRANTY_CHECK_URL}?sn={serial}"
        await page.goto(direct_url, wait_until="load", timeout=TIMEOUT_MS)
        await page.wait_for_timeout(4000)

        if data_event.is_set():
            return _parse_result(serial, product_data, warranty_data)

        # ── Dismiss overlays ──────────────────────────────────────────────────
        for overlay in ["#onetrust-accept-btn-handler", "[aria-label='Close']", ".modal-close"]:
            try:
                await page.click(overlay, timeout=2000)
                await page.wait_for_timeout(500)
            except Exception:
                pass

        # ── Strategy 2: find and fill the serial input field ─────────────────
        input_selector = None
        for sel in _INPUT_SELECTORS:
            try:
                await page.wait_for_selector(sel, timeout=5000, state="visible")
                input_selector = sel
                break
            except Exception:
                continue

        if input_selector:
            await page.fill(input_selector, serial)
            await page.wait_for_timeout(400)

            for btn in _SUBMIT_SELECTORS:
                try:
                    await page.click(btn, timeout=3000)
                    break
                except Exception:
                    continue
        else:
            # ── Strategy 3: press Enter on the page hoping the field is focused
            await page.keyboard.press("Tab")
            await page.keyboard.type(serial)
            await page.keyboard.press("Enter")

        # Wait for warranty API response (up to 20s)
        try:
            await asyncio.wait_for(data_event.wait(), timeout=20.0)
        except asyncio.TimeoutError:
            pass

        return _parse_result(serial, product_data, warranty_data)

    except Exception as exc:
        return {
            "serialNumber": serial.upper(),
            "productName": None, "productNumber": None, "description": None,
            "warrantyStatus": None, "warrantyStartDate": None, "warrantyEndDate": None,
            "warrantyType": None, "serviceType": None, "entitlements": [],
            "error": str(exc),
        }
    finally:
        await context.close()
