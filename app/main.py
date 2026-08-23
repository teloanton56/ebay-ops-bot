from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.routers import (
    auth, automation, channels, cj, cloud, compliance, connections, ebay,
    ebay_compliance, finance, opportunity_center, products, radar, research,
    settings, shop_spy, supplier_flow, suppliers, support, taxonomy, ui,
)
from app.services.cloud_auth import (
    COOKIE_NAME, allowed_hosts, allowed_origins, public_path, session_email,
    validate_cloud_configuration,
)
from app.services.ebay import EbayClient
from app.services.scheduler import start_scheduler, stop_scheduler
from app.config import get_settings

VERSION = "0.25.0"
BRAND_REV = "ops-knot-1"


@asynccontextmanager
async def lifespan(_: FastAPI):
    validate_cloud_configuration(get_settings())
    from app.services.db import init_db
    init_db()
    start_scheduler()
    try:
        yield
    finally:
        stop_scheduler()


app = FastAPI(title="eBay US · CJ Ops Bot", version=VERSION, docs_url=None, redoc_url=None, lifespan=lifespan)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts(get_settings()))
app.include_router(ebay_compliance.router)
app.include_router(cloud.router)
app.include_router(auth.router)
app.include_router(products.router)
app.include_router(ebay.router)
app.include_router(compliance.router)
app.include_router(research.router)
app.include_router(taxonomy.router)
app.include_router(automation.router)
app.include_router(settings.router)
app.include_router(cj.router)
app.include_router(connections.router)
app.include_router(finance.router)
app.include_router(radar.router)
app.include_router(opportunity_center.router)
app.include_router(suppliers.router)
app.include_router(supplier_flow.router)
app.include_router(shop_spy.router)
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
    settings = get_settings()
    return {
        "ok": True,
        "version": VERSION,
        "demo_mode": settings.demo_mode,
        "mode": "cloud" if settings.cloud_mode else "local",
        "operating_mode": "EBAY_US_CJ_ONLY",
        "marketplace": "EBAY_US",
        "currency": "USD",
        "destination_country": "US",
    }


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    context = {
        "request": request,
        "oauth": EbayClient().token_status(),
        "config": get_settings(),
        "version": VERSION,
    }
    html = templates.get_template("dashboard.html").render(context)
    html = html.replace("/static/app-icon.svg", f"/static/app-icon.svg?v={BRAND_REV}")
    return HTMLResponse(html)


@app.get("/manifest.webmanifest")
def manifest():
    return FileResponse("app/static/manifest.webmanifest", media_type="application/manifest+json")


@app.get("/service-worker.js")
def service_worker():
    return FileResponse(
        "app/static/service-worker.js",
        media_type="application/javascript",
        headers={"Service-Worker-Allowed": "/", "Cache-Control": "no-cache"},
    )


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
