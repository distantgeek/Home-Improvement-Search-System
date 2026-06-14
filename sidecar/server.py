"""Playwright sidecar — renders JS-heavy pages and returns HTML.

FastAPI server that accepts a URL, renders it with headless Chromium via
Playwright, and returns the page HTML. Designed to run on a separate machine
(Proxmox LXC) to avoid resource contention with the HISS pipeline on TrueNAS.

SSRF protection: reuses the same blocked-URL logic from pipeline.fetchers.url_enrich.
Rate limiting: single concurrent render via asyncio.Semaphore(1).
Authentication: requires X-Sidecar-Token header matching SIDECAR_API_KEY env var.
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import os
import secrets
import socket
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field, HttpUrl

logger = logging.getLogger(__name__)

_PRIVATE_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
    ipaddress.ip_network("::ffff:0:0/96"),
    ipaddress.ip_network("::/128"),
]

_BLOCKED_HOST_SUFFIXES = (
    ".local",
    ".internal",
    ".localhost",
    ".test",
    ".example",
    ".invalid",
)

_SIDECAR_API_KEY = os.environ.get("SIDECAR_API_KEY", "")
if not _SIDECAR_API_KEY:
    raise RuntimeError("SIDECAR_API_KEY environment variable must be set")
_RENDER_TIMEOUT = int(os.environ.get("SIDECAR_RENDER_TIMEOUT", "25") or "25")
_MAX_CONTENT_LENGTH = 5 * 1024 * 1024

_browser = None
_semaphore = None


class RenderRequest(BaseModel):
    url: HttpUrl
    timeout: int = Field(default=_RENDER_TIMEOUT, ge=5, le=60)


class RenderResponse(BaseModel):
    html: str
    url: str


class ErrorResponse(BaseModel):
    error: str


def _is_private_ip(hostname: str) -> bool:
    try:
        addr_info = socket.getaddrinfo(
            hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM
        )
    except socket.gaierror:
        return True
    for family, _type, _proto, _canon, sockaddr in addr_info:
        try:
            ip = ipaddress.ip_address(sockaddr[0])
            if any(ip in net for net in _PRIVATE_NETWORKS):
                return True
        except ValueError:
            continue
    return False


def _is_blocked_url(url: str) -> bool:
    from urllib.parse import urlparse

    try:
        parsed = urlparse(url)
    except ValueError:
        return True
    if parsed.scheme != "https":
        return True
    host = (parsed.hostname or "").lower()
    if not host:
        return True
    if host in ("localhost", "127.0.0.1", "::1"):
        return True
    if any(host.endswith(s) for s in _BLOCKED_HOST_SUFFIXES):
        return True
    if _is_private_ip(host):
        return True
    return False


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _browser, _semaphore
    from playwright.async_api import async_playwright

    _semaphore = asyncio.Semaphore(1)
    pw = await async_playwright().start()
    _browser = await pw.chromium.launch(
        headless=True,
        chromium_sandbox=True,
        args=[
            "--disable-gpu",
            "--disable-dev-shm-usage",
        ],
    )
    logger.info("Playwright browser launched")
    yield
    await _browser.close()
    await pw.stop()
    logger.info("Playwright browser closed")


app = FastAPI(title="HISS Playwright Sidecar", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post(
    "/render", response_model=RenderResponse, responses={502: {"model": ErrorResponse}}
)
async def render(req: RenderRequest, authorization: str = Header(None)):
    if _SIDECAR_API_KEY:
        expected = f"Bearer {_SIDECAR_API_KEY}"
        if not authorization or not secrets.compare_digest(authorization, expected):
            raise HTTPException(status_code=401, detail="Unauthorized")

    if _is_blocked_url(str(req.url)):
        raise HTTPException(status_code=400, detail="URL blocked by SSRF protection")

    if _browser is None:
        raise HTTPException(status_code=503, detail="Browser not ready")

    async with _semaphore:
        page = None
        try:
            page = await _browser.new_page()
            try:
                await page.goto(
                    str(req.url),
                    wait_until="networkidle",
                    timeout=req.timeout * 1000,
                )
            except Exception:
                try:
                    await page.goto(
                        str(req.url),
                        wait_until="domcontentloaded",
                        timeout=max(req.timeout * 500, 5000),
                    )
                except Exception:
                    raise HTTPException(status_code=502, detail="Failed to load page")

            final_url = page.url
            if _is_blocked_url(final_url):
                raise HTTPException(status_code=400, detail="Redirect to blocked URL")

            html = await page.content()
            if len(html) > _MAX_CONTENT_LENGTH:
                html = html[:_MAX_CONTENT_LENGTH]

            return RenderResponse(html=html, url=final_url)
        finally:
            if page:
                await page.close()
