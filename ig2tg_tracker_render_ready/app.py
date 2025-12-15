from __future__ import annotations

import os
import time
import secrets
import csv
import io
from typing import Optional, Dict, Any

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import RedirectResponse, JSONResponse, PlainTextResponse

from db import init_schema, insert_click, link_click_to_tg_user, get_clicks_rows_for_csv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
BOT_USERNAME = os.getenv("BOT_USERNAME", "").strip().lstrip("@")
CHANNEL_URL = os.getenv("CHANNEL_URL", "").strip()
BASE_URL = os.getenv("BASE_URL", "").strip()
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "").strip()
TRACK_DB = os.getenv("TRACK_DB", "./tracker.sqlite3").strip()

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is required")
if not BOT_USERNAME:
    raise RuntimeError("BOT_USERNAME is required")
if not CHANNEL_URL:
    raise RuntimeError("CHANNEL_URL is required")
if not BASE_URL:
    raise RuntimeError("BASE_URL is required")
if not ADMIN_TOKEN:
    raise RuntimeError("ADMIN_TOKEN is required")

app = FastAPI(title="IG → Telegram click tracker")


@app.on_event("startup")
def _startup() -> None:
    init_schema(TRACK_DB)


def _client_ip(request: Request) -> str:
    # Render proxies usually set X-Forwarded-For
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else ""


def _check_admin(token: str) -> None:
    if token != ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")


async def tg_api(method: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.post(url, json=payload)
        data = r.json()
        return data


async def tg_send_message(chat_id: int, text: str, reply_markup: Optional[Dict[str, Any]] = None) -> None:
    payload: Dict[str, Any] = {"chat_id": chat_id, "text": text}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    await tg_api("sendMessage", payload)


@app.get("/health")
async def health() -> JSONResponse:
    return JSONResponse({"ok": True})


@app.get("/privacy")
async def privacy() -> PlainTextResponse:
    text = (
        "Privacy notice\n"
        "This service logs clicks on the Instagram bio link (timestamp, IP, user-agent, referrer).\n"
        "If you press Start in Telegram after clicking, we also store your Telegram user id and username\n"
        "to link you to that click.\n"
        "We do not receive your Instagram account identity from Instagram.\n"
    )
    return PlainTextResponse(text)


@app.get("/ig")
async def ig(request: Request) -> RedirectResponse:
    """
    Instagram bio link target.

    1) creates a click token and logs it
    2) redirects into Telegram bot deep-link:
       https://t.me/<bot>?start=ig_<token>
    """
    token = secrets.token_urlsafe(18)
    now = int(time.time())

    insert_click(
        TRACK_DB,
        token=token,
        ts=now,
        ip=_client_ip(request),
        user_agent=request.headers.get("user-agent", ""),
        referrer=request.headers.get("referer", ""),
    )

    deep_link = f"https://t.me/{BOT_USERNAME}?start=ig_{token}"
    return RedirectResponse(deep_link, status_code=302)


@app.post("/tg/webhook")
async def tg_webhook(update: Dict[str, Any]) -> JSONResponse:
    """
    Telegram webhook endpoint. We care about /start ig_<token>.

    Note: you only learn "who clicked" if the user actually presses Start.
    """
    message = update.get("message") or update.get("edited_message")
    if not message:
        return JSONResponse({"ok": True})

    text = (message.get("text") or "").strip()
    if not text.startswith("/start"):
        return JSONResponse({"ok": True})

    # Parse /start payload
    payload = ""
    parts = text.split(maxsplit=1)
    if len(parts) == 2:
        payload = parts[1].strip()

    user = message.get("from") or {}
    tg_user_id = user.get("id")
    tg_username = user.get("username") or ""
    tg_first_name = user.get("first_name") or ""
    tg_last_name = user.get("last_name") or ""

    click_token: Optional[str] = None
    if payload.startswith("ig_"):
        click_token = payload[len("ig_") :]

    if click_token and tg_user_id:
        link_click_to_tg_user(
            TRACK_DB,
            token=click_token,
            tg_user_id=int(tg_user_id),
            username=tg_username,
            first_name=tg_first_name,
            last_name=tg_last_name,
        )

    # Reply with button to channel
    chat_id = message.get("chat", {}).get("id")
    if chat_id:
        await tg_send_message(
            chat_id=chat_id,
            text="Готово! Нажми кнопку ниже, чтобы открыть канал 👇",
            reply_markup={"inline_keyboard": [[{"text": "Открыть канал", "url": CHANNEL_URL}]]},
        )

    return JSONResponse({"ok": True})


@app.get("/admin/csv")
async def admin_csv(token: str, limit: int = 5000) -> PlainTextResponse:
    _check_admin(token)
    rows = get_clicks_rows_for_csv(TRACK_DB, limit=limit)

    buf = io.StringIO()
    w = csv.DictWriter(
        buf,
        fieldnames=[
            "token",
            "ts",
            "ip",
            "user_agent",
            "referrer",
            "tg_user_id",
            "tg_username",
            "tg_first_name",
            "tg_last_name",
            "linked_ts",
        ],
    )
    w.writeheader()
    for r in rows:
        w.writerow(r)
    return PlainTextResponse(buf.getvalue(), media_type="text/csv")


@app.get("/admin/set_webhook")
async def admin_set_webhook(token: str) -> JSONResponse:
    """
    Calls Telegram setWebhook and points it to:
      {BASE_URL}/tg/webhook
    """
    _check_admin(token)
    webhook_url = f"{BASE_URL.rstrip('/')}/tg/webhook"
    data = await tg_api(
        "setWebhook",
        {
            "url": webhook_url,
            "allowed_updates": ["message", "edited_message"],
        },
    )
    return JSONResponse(data)
