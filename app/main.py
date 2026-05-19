import os
import secrets
from pathlib import Path

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, Form, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
N8N_WEBHOOK = os.getenv("N8N_WEBHOOK", "")
SESSION_SECRET = os.getenv("SESSION_SECRET", secrets.token_hex(32))
APP_USERNAME = os.getenv("APP_USERNAME", "cesar")
APP_PASSWORD = os.getenv("APP_PASSWORD", "")

LOGIN_HTML = """<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1"/>
  <title>Acceso — Agentes IA</title>
  <link href="https://fonts.googleapis.com/css2?family=Space+Mono:wght@400;700&display=swap" rel="stylesheet"/>
  <style>
    *,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
    body{background:#080b0f;color:#e2e8f0;font-family:'Space Mono',monospace;
         display:flex;align-items:center;justify-content:center;min-height:100vh}
    body::before{content:'';position:fixed;inset:0;
      background-image:linear-gradient(rgba(45,212,191,.03) 1px,transparent 1px),
                       linear-gradient(90deg,rgba(45,212,191,.03) 1px,transparent 1px);
      background-size:40px 40px;pointer-events:none}
    .card{background:#0e1117;border:1px solid #1c2230;border-radius:16px;
          padding:2.5rem 2rem;width:100%;max-width:380px;position:relative;z-index:1}
    .logo{font-size:1.8rem;font-weight:700;letter-spacing:-.02em;color:#fff;margin-bottom:.25rem}
    .logo span{color:#2dd4bf}
    .sub{font-size:.72rem;color:#64748b;letter-spacing:.08em;margin-bottom:2rem}
    label{display:block;font-size:.65rem;color:#64748b;letter-spacing:.1em;
          text-transform:uppercase;margin-bottom:.4rem}
    input{width:100%;background:#05080c;border:1px solid #1c2230;border-radius:8px;
          color:#e2e8f0;font-family:'Space Mono',monospace;font-size:.82rem;
          padding:.65rem 1rem;outline:none;margin-bottom:1rem;transition:border-color .2s}
    input:focus{border-color:#2dd4bf}
    button{width:100%;background:#2dd4bf;color:#000;border:none;border-radius:8px;
           padding:.75rem;font-family:'Space Mono',monospace;font-size:.85rem;
           font-weight:700;cursor:pointer;letter-spacing:.03em;transition:background .2s}
    button:hover{background:#5eead4}
    .error{background:#1f0e0e;border:1px solid #ef4444;border-radius:8px;
           padding:.65rem 1rem;color:#ef4444;font-size:.78rem;margin-bottom:1rem}
    .dot{width:8px;height:8px;border-radius:50%;background:#2dd4bf;
         box-shadow:0 0 8px #2dd4bf;display:inline-block;margin-right:.5rem;
         animation:pulse 2s infinite}
    @keyframes pulse{0%,100%{opacity:1}50%{opacity:.3}}
  </style>
</head>
<body>
  <div class="card">
    <div class="logo">agentes<span>.</span></div>
    <div class="sub"><span class="dot"></span>cesarheredero.com · acceso privado</div>
    {error_html}
    <form method="post" action="/api/login">
      <label>Usuario</label>
      <input type="text" name="username" autocomplete="username" autofocus required/>
      <label>Contraseña</label>
      <input type="password" name="password" autocomplete="current-password" required/>
      <button type="submit">Entrar →</button>
    </form>
  </div>
</body>
</html>"""


class AuthMiddleware(BaseHTTPMiddleware):
    PUBLIC = {"/login", "/api/login"}

    async def dispatch(self, request: Request, call_next):
        if request.url.path in self.PUBLIC:
            return await call_next(request)
        if not request.session.get("authenticated"):
            return RedirectResponse(url="/login", status_code=302)
        return await call_next(request)


app = FastAPI(title="Agentes IA")

# Middleware order: CORS → Session → Auth → handlers
app.add_middleware(AuthMiddleware)
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET, max_age=86400 * 7, https_only=False)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, error: str = ""):
    error_html = '<div class="error">Usuario o contraseña incorrectos.</div>' if error else ""
    return HTMLResponse(LOGIN_HTML.replace("{error_html}", error_html))


@app.post("/api/login")
async def do_login(request: Request, username: str = Form(...), password: str = Form(...)):
    if not APP_PASSWORD:
        return HTMLResponse("APP_PASSWORD no configurado en .env", status_code=503)
    if username == APP_USERNAME and password == APP_PASSWORD:
        request.session["authenticated"] = True
        return RedirectResponse(url="/", status_code=302)
    return RedirectResponse(url="/login?error=1", status_code=302)


@app.get("/api/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=302)


@app.post("/api/claude")
async def proxy_claude(request: Request):
    if not ANTHROPIC_API_KEY:
        return JSONResponse({"detail": "ANTHROPIC_API_KEY no configurado"}, status_code=503)

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
            resp = await client.post("https://api.anthropic.com/v1/messages", json=payload, headers=headers)
            return JSONResponse(content=resp.json(), status_code=resp.status_code)

    async def event_stream():
        async with httpx.AsyncClient(timeout=120) as client:
            async with client.stream("POST", "https://api.anthropic.com/v1/messages", json=payload, headers=headers) as resp:
                async for chunk in resp.aiter_bytes():
                    yield chunk

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/api/telegram")
async def send_telegram(request: Request):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return JSONResponse({"detail": "Telegram no configurado"}, status_code=503)

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

    return JSONResponse({"detail": "Error enviando Telegram"}, status_code=502)


static_path = Path(__file__).parent / "static"
app.mount("/", StaticFiles(directory=static_path, html=True), name="static")
