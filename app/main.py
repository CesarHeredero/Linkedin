import asyncio
import json as _json
import os
import secrets
import time
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv
from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response, StreamingResponse
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
ADZUNA_APP_ID = os.getenv("ADZUNA_APP_ID", "")
ADZUNA_APP_KEY = os.getenv("ADZUNA_APP_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID", "1jty9n0zSmMCcCFlkzVpNdn1feoS_wPEo5FsnJym-eqg")
GOOGLE_CREDENTIALS_JSON = os.getenv("GOOGLE_CREDENTIALS_JSON", "")

TERMINOS_BUSQUEDA = ["Lead UX", "Product Owner", "Product Manager", "UX Lead"]
# Pares (término, categoría Remotive) — Product y Design son las relevantes para César
TERMINOS_REMOTIVE = [
    ("product owner", "Product"),
    ("product manager", "Product"),
    ("head of product", "Product"),
    ("ux designer", "Design"),
    ("ux lead", "Design"),
    ("lead ux", "Design"),
]
scheduler = AsyncIOScheduler(timezone="Europe/Madrid")


async def _fetch_remotive(pares: list) -> list:
    """Busca ofertas en Remotive filtrando por categoría Product/Design.

    pares: lista de (termino, categoria) — ej. [("product owner", "Product")]
    """
    from urllib.parse import quote as urlquote
    vistas: set = set()
    resultado: list = []
    for termino, categoria in pares:
        try:
            url = (
                f"https://remotive.com/api/remote-jobs"
                f"?search={urlquote(termino)}&category={urlquote(categoria)}&limit=10"
            )
            async with httpx.AsyncClient(timeout=20) as client:
                resp = await client.get(url)
            if resp.status_code != 200:
                continue
            for j in resp.json().get("jobs", []):
                jid = f"remotive_{j.get('id', '')}"
                if jid in vistas:
                    continue
                vistas.add(jid)
                resultado.append({
                    "id": jid,
                    "titulo": j.get("title", ""),
                    "empresa": j.get("company_name", "Sin especificar"),
                    "ubicacion": j.get("candidate_required_location", "Remoto"),
                    "modalidad": "Remoto",
                    "salario": j.get("salary", "") or "No especificado",
                    "descripcion": (j.get("description", "") or "")[:600],
                    "url": j.get("url", ""),
                    "fecha": (j.get("publication_date", "") or "")[:10],
                    "termino": termino,
                    "fuente": "Remotive",
                })
        except Exception:
            continue
    return resultado


async def busqueda_automatica():
    vistas: set = set()
    todas: list = []

    # ── Adzuna (España, requiere credenciales) ─────────────────────────────────
    if ADZUNA_APP_ID and ADZUNA_APP_KEY:
        for termino in TERMINOS_BUSQUEDA:
            params = {
                "app_id": ADZUNA_APP_ID,
                "app_key": ADZUNA_APP_KEY,
                "results_per_page": 10,
                "what": termino,
                "sort_by": "date",
            }
            try:
                async with httpx.AsyncClient(timeout=15) as client:
                    resp = await client.get("https://api.adzuna.com/v1/api/jobs/es/search/1", params=params)
                if resp.status_code != 200:
                    continue
                for r in resp.json().get("results", []):
                    rid = r.get("id", "")
                    if rid in vistas:
                        continue
                    vistas.add(rid)
                    s_min, s_max = r.get("salary_min"), r.get("salary_max")
                    salario = f"{int(s_min):,} – {int(s_max):,} €/año".replace(",", ".") if s_min and s_max else "No especificado"
                    title_lower = r.get("title", "").lower()
                    modalidad = "Remoto" if "remoto" in title_lower or "remote" in title_lower else "Presencial/Híbrido"
                    todas.append({
                        "id": rid,
                        "titulo": r.get("title", ""),
                        "empresa": r.get("company", {}).get("display_name", "Sin especificar"),
                        "ubicacion": r.get("location", {}).get("display_name", "España"),
                        "modalidad": modalidad,
                        "salario": salario,
                        "descripcion": r.get("description", "")[:600],
                        "url": r.get("redirect_url", ""),
                        "fecha": r.get("created", "")[:10],
                        "termino": termino,
                        "fuente": "Adzuna",
                    })
            except Exception:
                continue

    # ── Remotive (global remoto, sin credenciales) — solo Product y Design ───────
    remotive = await _fetch_remotive(TERMINOS_REMOTIVE)
    for o in remotive:
        if o["id"] not in vistas:
            vistas.add(o["id"])
            todas.append(o)

    if not todas:
        return

    data_path = Path("/app/data/ofertas.json")
    data_path.parent.mkdir(parents=True, exist_ok=True)
    with open(data_path, "w") as f:
        _json.dump({"ofertas": todas, "total": len(todas), "fecha_busqueda": datetime.now().isoformat()}, f, ensure_ascii=False, indent=2)

    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return

    lines = [f"<b>💼 Ofertas encontradas ({len(todas)})</b>\n"]
    for o in todas[:8]:
        lines.append(f"• <b>{o['titulo']}</b> — {o['empresa']}")
        lines.append(f"  📍 {o['ubicacion']} · {o['modalidad']}\n")
    lines.append("Abre el Buscador para generar tu CV personalizado.")
    texto = "\n".join(lines)

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            await client.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                json={"chat_id": TELEGRAM_CHAT_ID, "text": texto, "parse_mode": "HTML", "disable_web_page_preview": True},
            )
    except Exception:
        if N8N_WEBHOOK:
            try:
                async with httpx.AsyncClient(timeout=15) as client:
                    await client.post(N8N_WEBHOOK, json={"message": texto})
            except Exception:
                pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler.add_job(busqueda_automatica, CronTrigger(hour=9, minute=0))
    scheduler.add_job(busqueda_automatica, CronTrigger(hour=18, minute=0))
    scheduler.start()
    yield
    scheduler.shutdown(wait=False)


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


# ── Rate limiter simple en memoria (max 30 llamadas/hora por sesión) ──────────
_rate_store: dict = defaultdict(list)
RATE_LIMIT = 30
RATE_WINDOW = 3600


def check_rate_limit(session_id: str) -> bool:
    now = time.time()
    calls = _rate_store[session_id]
    _rate_store[session_id] = [t for t in calls if now - t < RATE_WINDOW]
    if len(_rate_store[session_id]) >= RATE_LIMIT:
        return False
    _rate_store[session_id].append(now)
    return True


class AuthMiddleware(BaseHTTPMiddleware):
    PUBLIC = {"/login", "/api/login"}

    async def dispatch(self, request: Request, call_next):
        if request.url.path in self.PUBLIC:
            return await call_next(request)
        if not request.session.get("authenticated"):
            return RedirectResponse(url="/login", status_code=302)
        return await call_next(request)


app = FastAPI(title="Agentes IA", lifespan=lifespan)

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
        request.session["session_id"] = secrets.token_hex(16)
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

    session_id = request.session.get("session_id", "anonymous")
    if not check_rate_limit(session_id):
        raise HTTPException(status_code=429, detail="Límite de llamadas alcanzado (30/hora). Espera un momento.")

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


def _get_sheet():
    import json as _json
    import gspread
    from google.oauth2.service_account import Credentials
    if not GOOGLE_CREDENTIALS_JSON:
        raise ValueError("GOOGLE_CREDENTIALS_JSON no configurado en .env")
    # Strip cualquier prefijo accidental antes del JSON real
    raw = GOOGLE_CREDENTIALS_JSON
    idx = raw.find('{')
    if idx > 0:
        raw = raw[idx:]
    creds_dict = _json.loads(raw)
    creds = Credentials.from_service_account_info(creds_dict, scopes=["https://www.googleapis.com/auth/spreadsheets"])
    client = gspread.authorize(creds)
    sheet = client.open_by_key(GOOGLE_SHEET_ID).sheet1
    # Crear cabecera si la hoja está vacía
    if not sheet.row_values(1):
        sheet.append_row(["ID", "Fecha", "Tema", "Formato", "Contenido", "ImagenURL"])
    return sheet


@app.get("/api/historial")
async def get_historial(request: Request):
    if not GOOGLE_CREDENTIALS_JSON:
        return JSONResponse({"historial": [], "configured": False})
    try:
        rows = _get_sheet().get_all_records()
        return {"historial": rows, "configured": True}
    except Exception as e:
        return JSONResponse({"detail": str(e)}, status_code=500)


@app.post("/api/historial")
async def save_historial(request: Request):
    if not GOOGLE_CREDENTIALS_JSON:
        return JSONResponse({"ok": False, "detail": "Google Sheets no configurado"})
    try:
        body = await request.json()
        sheet = _get_sheet()
        sheet.append_row([
            str(body.get("id", "")),
            body.get("fecha", ""),
            body.get("tema", ""),
            body.get("formato", ""),
            body.get("contenido", ""),
            body.get("imagenUrl", ""),
        ])
        return {"ok": True}
    except Exception as e:
        return JSONResponse({"detail": str(e)}, status_code=500)


@app.get("/api/gemini-models")
async def list_gemini_models(request: Request):
    if not GEMINI_API_KEY:
        return JSONResponse({"detail": "GEMINI_API_KEY no configurado"}, status_code=503)
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(f"https://generativelanguage.googleapis.com/v1/models?key={GEMINI_API_KEY}")
    if resp.status_code == 200:
        names = [m["name"] for m in resp.json().get("models", []) if "generateContent" in m.get("supportedGenerationMethods", [])]
        return {"models": names}
    return JSONResponse({"detail": resp.text[:300]}, status_code=resp.status_code)


@app.post("/api/gemini")
async def proxy_gemini(request: Request):
    body = await request.json()
    prompt = body.get("prompt", "")
    max_tokens = body.get("max_tokens", 2048)
    force_json = body.get("json", False)

    # Intentar Gemini si hay clave configurada
    if GEMINI_API_KEY:
        gen_config = {"maxOutputTokens": max_tokens, "temperature": 0.7}
        if force_json:
            gen_config["responseMimeType"] = "application/json"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": gen_config,
        }
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-lite:generateContent?key={GEMINI_API_KEY}"
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(url, json=payload)
        if resp.status_code == 200:
            data = resp.json()
            text = data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
            return {"text": text}
        if resp.status_code not in (429, 503):
            return JSONResponse({"detail": f"Error Gemini {resp.status_code}: {resp.text[:200]}"}, status_code=resp.status_code)
        # 429/503 → fallback a Claude Haiku

    # Fallback: Claude Haiku
    if not ANTHROPIC_API_KEY:
        return JSONResponse({"detail": "Gemini no disponible y ANTHROPIC_API_KEY no configurado"}, status_code=503)

    headers = {"x-api-key": ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"}
    system = "Respond only with valid JSON. No preamble, no markdown, no code blocks. Just the raw JSON object." if force_json else None
    claude_payload = {"model": "claude-haiku-4-5-20251001", "max_tokens": max_tokens, "messages": [{"role": "user", "content": prompt}]}
    if system:
        claude_payload["system"] = system
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post("https://api.anthropic.com/v1/messages", json=claude_payload, headers=headers)
    if resp.status_code == 200:
        return {"text": resp.json().get("content", [{}])[0].get("text", "")}
    return JSONResponse({"detail": f"Error Claude fallback {resp.status_code}"}, status_code=resp.status_code)


@app.get("/api/jobs")
async def search_jobs(request: Request, q: str = "Product Owner UX"):
    ofertas: list = []
    vistas: set = set()

    # ── Adzuna (España) ────────────────────────────────────────────────────────
    if ADZUNA_APP_ID and ADZUNA_APP_KEY:
        params = {
            "app_id": ADZUNA_APP_ID,
            "app_key": ADZUNA_APP_KEY,
            "results_per_page": 10,
            "what": q,
            "sort_by": "date",
        }
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get("https://api.adzuna.com/v1/api/jobs/es/search/1", params=params)
            if resp.status_code == 200:
                for r in resp.json().get("results", []):
                    rid = r.get("id", "")
                    if rid in vistas:
                        continue
                    vistas.add(rid)
                    s_min, s_max = r.get("salary_min"), r.get("salary_max")
                    salario = f"{int(s_min):,} – {int(s_max):,} €/año".replace(",", ".") if s_min and s_max else "No especificado"
                    title_lower = r.get("title", "").lower()
                    modalidad = "Remoto" if "remoto" in title_lower or "remote" in title_lower else "Presencial/Híbrido"
                    ofertas.append({
                        "id": rid,
                        "titulo": r.get("title", ""),
                        "empresa": r.get("company", {}).get("display_name", "Sin especificar"),
                        "ubicacion": r.get("location", {}).get("display_name", "España"),
                        "modalidad": modalidad,
                        "salario": salario,
                        "descripcion": r.get("description", "")[:600],
                        "url": r.get("redirect_url", ""),
                        "fecha": r.get("created", "")[:10],
                        "fuente": "Adzuna",
                    })
        except Exception:
            pass

    # ── Remotive — búsqueda en categorías Product y Design únicamente ──────────
    remotive = await _fetch_remotive([(q, "Product"), (q, "Design")])
    for o in remotive:
        if o["id"] not in vistas:
            vistas.add(o["id"])
            ofertas.append(o)

    return {"ofertas": ofertas, "total": len(ofertas)}


@app.get("/api/perfil")
async def get_perfil(request: Request):
    import json as _json
    perfil_path = Path("/app/data/perfil.json")
    if not perfil_path.exists():
        return JSONResponse({"perfil": None})
    with open(perfil_path) as f:
        return {"perfil": _json.load(f)}


@app.post("/api/perfil")
async def save_perfil(request: Request):
    import json as _json
    body = await request.json()
    perfil_path = Path("/app/data/perfil.json")
    perfil_path.parent.mkdir(parents=True, exist_ok=True)
    with open(perfil_path, "w") as f:
        _json.dump(body, f, ensure_ascii=False, indent=2)
    return {"ok": True}


@app.post("/api/jobs/buscar-ahora")
async def buscar_ahora(request: Request):
    await busqueda_automatica()
    data_path = Path("/app/data/ofertas.json")
    if data_path.exists():
        with open(data_path) as f:
            return _json.load(f)
    return {"ofertas": [], "total": 0, "fecha_busqueda": None}


@app.get("/api/jobs/ultima-busqueda")
async def ultima_busqueda(request: Request):
    data_path = Path("/app/data/ofertas.json")
    if not data_path.exists():
        return {"ofertas": [], "total": 0, "fecha_busqueda": None}
    with open(data_path) as f:
        return _json.load(f)


@app.get("/api/image")
async def proxy_image(request: Request, prompt: str, width: int = 1200, height: int = 628, seed: int = 42):
    from urllib.parse import quote

    # Try Pollinations.ai (3 attempts, 3s apart)
    poll_url = f"https://image.pollinations.ai/prompt/{quote(prompt)}?width={width}&height={height}&model=flux&nologo=true&seed={seed}"
    for attempt in range(3):
        try:
            async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
                resp = await client.get(poll_url)
            if resp.status_code == 200 and resp.headers.get("content-type", "").startswith("image/"):
                return Response(content=resp.content, media_type=resp.headers["content-type"])
        except Exception:
            pass
        if attempt < 2:
            await asyncio.sleep(3)

    # Fallback: loremflickr — relevant stock photos, no API key, no rate limits
    keywords = ",".join(w for w in prompt.split() if len(w) > 3)[:80]
    fallback_url = f"https://loremflickr.com/{width}/{height}/{quote(keywords)}"
    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            resp = await client.get(fallback_url)
        if resp.status_code == 200:
            return Response(content=resp.content, media_type=resp.headers.get("content-type", "image/jpeg"))
    except Exception:
        pass

    return JSONResponse({"detail": "No se pudo generar la imagen"}, status_code=502)


static_path = Path(__file__).parent / "static"
app.mount("/", StaticFiles(directory=static_path, html=True), name="static")
