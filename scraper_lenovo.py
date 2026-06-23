"""
Lenovo warranty scraper using Playwright (Firefox).
Fills the warranty-lookup form, intercepts the getIbaseInfo API response,
and returns { startDate, endDate (start+5yr) }.
"""

import asyncio
from datetime import date
from dateutil.relativedelta import relativedelta
from playwright.async_api import Browser

LENOVO_WARRANTY_URL = "https://pcsupport.lenovo.com/us/en/warranty-lookup"
TIMEOUT_MS = 45000

_STEALTH_SCRIPT = """
    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
    Object.defineProperty(navigator, 'plugins',   {get: () => [1,2,3,4,5]});
    Object.defineProperty(navigator, 'languages', {get: () => ['en-US','en']});
"""


async def lookup_warranty_lenovo(browser: Browser, serial: str) -> dict:
    result = {"serialNumber": serial.upper(), "startDate": None, "endDate": None, "error": None}

    context = await browser.new_context(
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) "
            "Gecko/20100101 Firefox/121.0"
        ),
        locale="en-US",
        viewport={"width": 1920, "height": 1080},
        extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
    )
    await context.add_init_script(_STEALTH_SCRIPT)
    page = await context.new_page()

    warranty_data: dict | None = None
    data_event = asyncio.Event()

    async def on_response(resp):
        nonlocal warranty_data
        try:
            ct = resp.headers.get("content-type", "")
            if "json" not in ct:
                return
            body = await resp.json()
            dates = _extract_warranty_dates(body)
            if dates.get("startDate"):
                warranty_data = dates
                data_event.set()
        except Exception:
            pass

    page.on("response", on_response)

    try:
        # networkidle ensures the Vue SPA has fully mounted before we look for inputs
        await page.goto(LENOVO_WARRANTY_URL, wait_until="networkidle", timeout=TIMEOUT_MS)

        # Dismiss cookie/overlay
        for sel in ["#onetrust-accept-btn-handler", "button[id*='accept' i]", ".modal-close"]:
            try:
                await page.click(sel, timeout=2000)
                await page.wait_for_timeout(300)
            except Exception:
                pass

        # Wait for the Vue warranty form input to appear inside the SPA container
        input_sel = None
        try:
            await page.wait_for_selector(
                "#app-standalone-warrantylookup input",
                timeout=12000, state="visible"
            )
            input_sel = "#app-standalone-warrantylookup input"
        except Exception:
            pass

        if not input_sel:
            for sel in ["input[id*='serial' i]", "input[name*='serial' i]",
                        "input[placeholder*='serial' i]"]:
                try:
                    await page.wait_for_selector(sel, timeout=4000, state="visible")
                    input_sel = sel
                    break
                except Exception:
                    pass

        if not input_sel:
            result["error"] = "Could not locate serial input on Lenovo warranty page"
            return result

        # Fill the serial number
        await page.click(input_sel, click_count=3)
        await page.keyboard.press("Delete")
        await page.type(input_sel, serial, delay=60)
        await page.wait_for_timeout(400)

        # Submit
        submitted = False
        for btn_sel in ["button[type='submit']", "button[id*='search' i]",
                        "button[id*='find' i]", "#app-standalone-warrantylookup button"]:
            try:
                el = page.locator(btn_sel).first
                if await el.is_visible(timeout=2000):
                    await el.click()
                    submitted = True
                    break
            except Exception:
                pass

        if not submitted:
            await page.keyboard.press("Enter")

        try:
            await asyncio.wait_for(data_event.wait(), timeout=25.0)
        except asyncio.TimeoutError:
            pass

        if warranty_data:
            _apply_dates(result, warranty_data)
        else:
            result["error"] = "No warranty data found — serial may be invalid"

    except Exception as exc:
        result["error"] = str(exc)
    finally:
        await context.close()

    return result


def _apply_dates(result: dict, dates: dict) -> None:
    start_str = dates.get("startDate")
    if start_str:
        result["startDate"] = start_str[:10]
        try:
            start = date.fromisoformat(start_str[:10])
            result["endDate"] = (start + relativedelta(years=5)).isoformat()
        except ValueError:
            end_str = dates.get("endDate")
            result["endDate"] = end_str[:10] if end_str else None


def _extract_warranty_dates(obj, depth: int = 0) -> dict:
    if depth > 10 or not isinstance(obj, (dict, list)):
        return {}

    if isinstance(obj, list):
        for item in obj:
            found = _extract_warranty_dates(item, depth + 1)
            if found:
                return found
        return {}

    start = (
        obj.get("currentWarrantyStartDate") or obj.get("warrantyStartDate") or
        obj.get("startDate") or obj.get("warrantyStart") or
        obj.get("StartDate") or obj.get("warrantyEffectiveDate") or
        obj.get("effectiveDate")
    )
    end = (
        obj.get("currentWarrantyEndDate") or obj.get("warrantyEndDate") or
        obj.get("endDate") or obj.get("warrantyEnd") or
        obj.get("EndDate") or obj.get("expirationDate") or
        obj.get("warrantyExpirationDate")
    )
    if start or end:
        return {"startDate": start, "endDate": end}

    for v in obj.values():
        found = _extract_warranty_dates(v, depth + 1)
        if found:
            return found

    return {}
