import os
import json
from pathlib import Path

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
N8N_WEBHOOK = os.getenv("N8N_WEBHOOK", "")

app = FastAPI(title="Tools API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/api/claude")
async def proxy_claude(request: Request):
    if not ANTHROPIC_API_KEY:
        raise HTTPException(status_code=503, detail="ANTHROPIC_API_KEY not configured")

    body = await request.json()
    stream = body.get("stream", False)

    payload = {
        "model": body.get("model", "claude-sonnet-4-5"),
        "max_tokens": body.get("max_tokens", 1500),
        "messages": body["messages"],
    }
    if body.get("system"):
        payload["system"] = body["system"]
    if stream:
        payload["stream"] = True

    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }

    if not stream:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                json=payload,
                headers=headers,
            )
            return JSONResponse(content=resp.json(), status_code=resp.status_code)

    async def event_stream():
        async with httpx.AsyncClient(timeout=120) as client:
            async with client.stream(
                "POST",
                "https://api.anthropic.com/v1/messages",
                json=payload,
                headers=headers,
            ) as resp:
                async for chunk in resp.aiter_bytes():
                    yield chunk

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/api/telegram")
async def send_telegram(request: Request):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        raise HTTPException(status_code=503, detail="Telegram not configured")

    body = await request.json()
    text = body.get("text", "")

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"},
        )

    if resp.status_code == 200:
        return {"ok": True}

    if N8N_WEBHOOK:
        async with httpx.AsyncClient(timeout=15) as client:
            await client.post(N8N_WEBHOOK, json={"message": text})
        return {"ok": True, "via": "n8n"}

    raise HTTPException(status_code=502, detail="Failed to send Telegram message")


static_path = Path(__file__).parent / "static"
app.mount("/", StaticFiles(directory=static_path, html=True), name="static")
