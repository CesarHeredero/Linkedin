# Contexto del proyecto — César Heredero

## Perfil profesional
- **Nombre:** César Heredero Herranz
- **Rol:** Lead UX/UI & Senior Product Owner
- **Empresa actual:** Grupo Flexicar (desde abril 2023) — ecommerce automoción, España y Portugal
- **Anterior:** Devoteam / Toyota España (6.5 años). Ganador Hackathon CardioXplore (nivel europeo)
- **Skills:** n8n, Figma, UX/UI Design, Product Owner, SEO Técnico, GTM Server-Side, BigQuery, GA4, A/B Testing, Agile/Scrum, Docker, APIs, Core Web Vitals, CMS Headless
- **Ubicación:** Algete, Madrid, España (preferencia remoto/híbrido)
- **Email:** heredero.cesar@gmail.com
- **LinkedIn:** linkedin.com/in/cesarheredero

## Infraestructura del VPS

### Ficha técnica
- **IP Pública:** 135.125.102.63
- **SO:** Debian 12 (vps-6b426220)
- **Usuario SSH:** debian
- **Dominio maestro:** cesarheredero.com
- **Gestor de tráfico:** Nginx Proxy Manager (puertos 80, 81, 443) — panel en `135.125.102.63:81`

### Servicios activos y puertos
| Servicio | Carpeta | Puerto | URL |
|----------|---------|--------|-----|
| Nginx Proxy Manager | — | 80, 81, 443 | panel en :81 |
| n8n | ~/n8n-docker | 5678 | n8n.cesarheredero.com |
| tools (estático) | ~/tools (repo: CesarHeredero/tools) | 4001 | tools.cesarheredero.com |
| Intranet frontend | — | 4000 | intracesar.cesarheredero.com |
| Intranet backend | — | 4000 | — |
| Deploys | — | 8000 | ops.cesarheredero.com |
| Ollama | — | — | ollama.cesarheredero.com |
| Agentes IA (este repo) | ~/agentes | 8082 | agentes.cesarheredero.com |

### Puertos libres recomendados para nuevos servicios
8081, 8083, 8084, 8090, 9000, 9001, 3000, 3001

### Ecosistema de automatización
- **n8n Profesional:** instancia principal, webhook URL base: `https://n8n.cesarheredero.com/webhook/`
- **Runner Python:** imagen distroless con Selenium inyectado vía ensurepip + PYTHONPATH
- **Selenium Chrome:** contenedor `selenium-chrome` v4.41+, conexión en `http://selenium-chrome:4444` (sin `/wd/hub`)

### Reglas de oro del VPS
1. **RAM limitada** — siempre incluir `driver.quit()` en bloque `try/finally` en scripts Selenium
2. **Error 502** → revisar primero si el contenedor está `Up` y si hay pico de RAM (`free -h`)
3. **Carpetas** — cada servicio en su propia carpeta en `~/` (ej: `~/agentes`, `~/n8n-docker`)
4. **DNS primero** — para nuevos subdominios: registro A en DNS → luego Proxy Host en NPM
5. **Conectividad entre contenedores** — usar nombre del contenedor como hostname dentro de la red Docker

### Comandos frecuentes
```bash
sudo docker compose up -d          # arrancar servicios
sudo docker compose up -d --build  # reconstruir y arrancar
sudo docker logs -f [nombre]       # ver logs en tiempo real
free -h                            # monitorear RAM
sudo docker ps                     # ver contenedores activos
```

### Flujo de deploy para nuevos servicios
1. Añadir registro A en proveedor DNS → `agentes` / IP: `135.125.102.63`
2. Crear carpeta en `~/nombre-servicio` y clonar repo
3. Copiar `.env.example` → `.env` y rellenar valores
4. `sudo docker compose up -d --build`
5. En NPM: nuevo Proxy Host → dominio + IP + puerto + Advanced config
6. Activar SSL con Let's Encrypt en pestaña SSL del Proxy Host

### Configuración Advanced para NPM (streaming/SSE)
```
proxy_buffering off;
proxy_read_timeout 120s;
proxy_set_header Host $host;
proxy_set_header X-Real-IP $remote_addr;
proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
proxy_set_header X-Forwarded-Proto $scheme;
```

## Credenciales y servicios externos
- **Telegram Bot Token:** en `.env` como `TELEGRAM_BOT_TOKEN`
- **Telegram Chat ID:** en `.env` como `TELEGRAM_CHAT_ID`
- **n8n Webhook (Telegram fallback):** `https://n8n.cesarheredero.com/webhook/1bef1e0b-5be5-4bea-b747-561fbbdbd3f3`
- **Anthropic API Key:** en `.env` como `ANTHROPIC_API_KEY` (crear en console.anthropic.com)

## Convenciones de este proyecto
- Autenticación: login con sesión cifrada (SessionMiddleware + cookie 7 días)
- Variables sensibles: siempre en `.env`, nunca en código
- Frontend: HTML self-contained con React + Babel CDN (sin build step)
- Tema visual: dark theme, Space Mono, accent `#2dd4bf`
