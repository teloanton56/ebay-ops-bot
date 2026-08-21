from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.routers import (auth, automation, channels, cj, cloud, connections, ebay, finance, products,
                         radar, research, settings, suppliers, support, taxonomy, ui)
from app.services.cloud_auth import COOKIE_NAME, allowed_hosts, allowed_origins, public_path, session_email, validate_cloud_configuration
from app.services.db import init_db, list_products
from app.services.ebay import EbayClient
from app.services.risk import assess_product
from app.services.scheduler import start_scheduler, stop_scheduler
from app.config import get_settings

VERSION = "0.15.0"


@asynccontextmanager
async def lifespan(_: FastAPI):
    validate_cloud_configuration(get_settings())
    init_db()
    start_scheduler()
    try:
        yield
    finally:
        stop_scheduler()

# Swagger/Redoc are intentionally hidden from the normal app to avoid sending non-technical users
# into raw API screens. The API remains available to the frontend.
app = FastAPI(title="eBay Ops Bot", version=VERSION, docs_url=None, redoc_url=None, lifespan=lifespan)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts(get_settings()))
app.include_router(cloud.router)
app.include_router(auth.router)
app.include_router(products.router)
app.include_router(ebay.router)
app.include_router(research.router)
app.include_router(taxonomy.router)
app.include_router(automation.router)
app.include_router(settings.router)
app.include_router(cj.router)
app.include_router(connections.router)
app.include_router(finance.router)
app.include_router(radar.router)
app.include_router(suppliers.router)
app.include_router(support.router)
app.include_router(channels.router)
app.include_router(ui.router)
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")


@app.middleware("http")
async def local_security(request: Request, call_next):
    current_settings = get_settings()
    if current_settings.cloud_mode and not public_path(request.url.path):
        email = session_email(request.cookies.get(COOKIE_NAME), current_settings)
        if not email:
            if request.url.path.startswith("/api/"):
                return JSONResponse({"detail": "Session expirée. Reconnectez-vous."}, status_code=401)
            return RedirectResponse("/login", status_code=303)
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        origin = request.headers.get("origin")
        if origin and origin.rstrip("/") not in allowed_origins(current_settings):
            return JSONResponse({"detail": "Requête externe refusée par la protection de sécurité"}, status_code=403)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; img-src 'self' https: data:; style-src 'self' 'unsafe-inline'; "
        "script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    )
    if current_settings.cloud_mode:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    if request.url.path == "/" or request.url.path == "/login" or request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/health")
def health():
    return {"ok": True, "version": VERSION, "demo_mode": get_settings().demo_mode,
            "mode": "cloud" if get_settings().cloud_mode else "local"}


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    rows = []
    for p in list_products():
        rows.append({**p, "risk": assess_product(p)})
    context = {
        "request": request,
        "products": rows,
        "oauth": EbayClient().token_status(),
        "config": get_settings(),
        "version": VERSION,
    }
    html = templates.get_template("dashboard.html").render(context)
    html = html.replace(
        "</head>",
        f'<link rel="stylesheet" href="/static/product_research.css?v={VERSION}">\n</head>',
    )
    html = html.replace(
        "</body>",
        (
            f'<script src="/static/provider_cleanup.js?v={VERSION}" defer></script>\n'
            f'<script src="/static/product_research.js?v={VERSION}" defer></script>\n'
            "</body>"
        ),
    )
    return HTMLResponse(html)


@app.get("/manifest.webmanifest")
def manifest():
    return FileResponse("app/static/manifest.webmanifest", media_type="application/manifest+json")


@app.get("/service-worker.js")
def service_worker():
    return FileResponse("app/static/service-worker.js", media_type="application/javascript",
                        headers={"Service-Worker-Allowed": "/", "Cache-Control": "no-cache"})


@app.get("/offline", response_class=HTMLResponse)
def offline():
    return FileResponse("app/static/offline.html", media_type="text/html; charset=utf-8")


@app.get("/sample_supplier.csv")
def sample_supplier_csv():
    return FileResponse(
        "sample_supplier.csv",
        media_type="text/csv; charset=utf-8",
        filename="modele_fournisseur_ebay.csv",
    )
