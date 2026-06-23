"""
Dell TechDirect warranty lookup via OAuth2 client credentials.
Endpoint: GET /PROD/sbil/eapi/v5/asset-entitlements?servicetags={tag}
startDate = shipDate, endDate = shipDate + 5 years (matches HP logic).
"""

import os
import time
import httpx
from datetime import date
from dateutil.relativedelta import relativedelta

DELL_TOKEN_URL    = "https://apigtwb2c.us.dell.com/auth/oauth/v2/token"
DELL_WARRANTY_URL = "https://apigtwb2c.us.dell.com/PROD/sbil/eapi/v5/asset-entitlements"

DELL_CLIENT_ID     = os.environ["DELL_CLIENT_ID"]
DELL_CLIENT_SECRET = os.environ["DELL_CLIENT_SECRET"]

_token: str | None = None
_token_expiry: float = 0.0


async def _get_token() -> str:
    global _token, _token_expiry
    if _token and time.time() < _token_expiry - 60:
        return _token
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            DELL_TOKEN_URL,
            data={
                "grant_type":    "client_credentials",
                "client_id":     DELL_CLIENT_ID,
                "client_secret": DELL_CLIENT_SECRET,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        _token = data["access_token"]
        _token_expiry = time.time() + int(data.get("expires_in", 3600))
    return _token


async def lookup_warranty_dell(serial: str) -> dict:
    result = {"serialNumber": serial.upper(), "startDate": None, "endDate": None, "error": None}
    try:
        token = await _get_token()
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                DELL_WARRANTY_URL,
                params={"servicetags": serial},
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()

        # API returns a list when queried with servicetags param
        entry = data[0] if isinstance(data, list) else data

        if entry.get("invalid"):
            result["error"] = "Invalid service tag"
            return result

        ship = entry.get("shipDate")
        if ship:
            start = date.fromisoformat(str(ship)[:10])
            result["startDate"] = start.isoformat()
            result["endDate"]   = (start + relativedelta(years=5)).isoformat()
        else:
            result["error"] = "No ship date found for this service tag"

    except httpx.HTTPStatusError as e:
        result["error"] = f"Dell API HTTP {e.response.status_code}"
    except Exception as e:
        result["error"] = str(e)

    return result
