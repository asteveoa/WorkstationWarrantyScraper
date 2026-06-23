# Use the official Playwright image — Playwright 1.44.0 ships on Ubuntu Jammy (22.04),
# which has all browser deps available in its repos. No font-package failures.
FROM mcr.microsoft.com/playwright/python:v1.44.0-jammy

WORKDIR /app

# Chromium is pre-installed in this image; we still need our Python deps.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Playwright is already installed above via requirements.txt, but the browser
# binary is baked into the base image — no install-deps step needed at all.

COPY . .

ENV PYTHONUNBUFFERED=1
ENV MAX_CONCURRENCY=3

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
