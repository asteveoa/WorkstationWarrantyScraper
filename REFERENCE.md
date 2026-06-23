# Bulk Warranty Lookup — Reference

## URLs

| Service | URL | Port |
|---------|-----|------|
| API backend | https://hp.hidemybackground.com | 8000 |
| Frontend | https://warranty.hidemybackground.com | 8080 |

---

## API Endpoints

```
GET /warranty-check/{serial}          # HP
GET /warranty-check/lenovo/{serial}   # Lenovo
GET /warranty-check/dell/{serial}     # Dell
GET /health
GET /                                 # HP scraper frontend (pepe)
```

All return: `{ serialNumber, startDate, endDate (start+5yr), error }`

---

## Server

- **Host:** `10.50.50.114` — user `steve`
- **Path:** `/home/steve/hpscraper/`

```
hpscraper/
├── docker-compose.yml
├── Dockerfile
├── main.py
├── scraper_fast.py       # HP — Chromium
├── scraper_dell.py       # Dell — httpx OAuth2
├── scraper_lenovo.py     # Lenovo — Firefox
├── requirements.txt
├── frontend/             # HP scraper UI (pepe)
└── warranty-frontend/    # Bulk Warranty site (nginx volume)
    ├── index.html
    └── nginx.conf
```

---

## Docker

```bash
# Status
sudo docker ps

# Logs
sudo docker logs hp-warranty-api --tail 50 -f

# Quick inject (no rebuild)
sudo docker cp <file> hp-warranty-api:/app/<file>
sudo docker restart hp-warranty-api

# Frontend (volume-mounted — no restart needed)
# Just SFTP the new index.html to warranty-frontend/index.html

# Full rebuild (requirements change)
cd /home/steve/hpscraper
sudo docker compose build --no-cache && sudo docker compose up -d

# Start new frontend only
sudo docker compose up -d warranty-frontend
```

---

## Vendor Details

### HP
- Chromium Playwright scraper (`scraper_fast.py`)
- Sequential requests, 3s gap (rate limit)

### Dell
- OAuth2 `client_credentials` → Bearer token (cached 3600s)
- Token: `https://apigtwb2c.us.dell.com/auth/oauth/v2/token`
- Warranty: `https://apigtwb2c.us.dell.com/PROD/sbil/eapi/v5/asset-entitlements?servicetags={serial}`
- API returns a **list** → always use `data[0]`
- `shipDate` = Purchase_Date; `shipDate + 5yr` = EOL_Date
- Credentials in `scraper_dell.py` (server-side only)

### Lenovo
- **Firefox** required — Chromium gets `ERR_HTTP2_PROTOCOL_ERROR` from Lenovo CDN
- Navigate to `https://pcsupport.lenovo.com/us/en/warranty-lookup` with `wait_until="networkidle"` (Vue SPA must fully mount)
- Input selector: `#app-standalone-warrantylookup input`
- Intercepts `getIbaseInfo` POST response for warranty dates
- `startDate + 5yr` = EOL_Date

---

## Frontend (warranty.hidemybackground.com)

- **Local file:** `D:\Projectsdocker\BulkWarrantyLookup\index.html`
- PapaParse CSV parsing; strips trailing-comma junk columns (`_1`, `_2` …)
- Both **Serial** and **Make** columns are required
- HP: sequential with 3s gaps; Lenovo/Dell: parallel
- Output appends `Purchase_Date` and `EOL_Date` columns

### Deploy frontend
```python
sftp.put('index.html', '/home/steve/hpscraper/warranty-frontend/index.html')
# Live immediately — no restart
```

---

## Cloudflare Tunnel (ingress)

```yaml
ingress:
  - hostname: warranty.hidemybackground.com
    service: http://localhost:8080
  - hostname: hp.hidemybackground.com
    service: http://localhost:8000
  - service: http_status:404
```
