"""
Thin wrapper around lookup_warranty() that returns only
warrantyStartDate (as startDate) and startDate + 5 years (as endDate).

No external HTTP calls — reuses the in-process Playwright browser.
"""

from datetime import date
from dateutil.relativedelta import relativedelta

from scraper import lookup_warranty


async def lookup_warranty_fast(browser, serial: str) -> dict:
    full = await lookup_warranty(browser, serial.strip(), "us")

    start: date | None = None
    start_str = full.get("warrantyStartDate")
    if start_str:
        try:
            start = date.fromisoformat(start_str)
        except ValueError:
            pass

    return {
        "serialNumber": serial.upper(),
        "startDate": start_str or None,
        "endDate": (start + relativedelta(years=5)).isoformat() if start else None,
        "error": full.get("error") if not start else None,
    }
