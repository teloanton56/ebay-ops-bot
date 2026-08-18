from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.config import get_settings
from app.services.backups import create_backup, list_backups, resolve_backup
from app.services.cloud_auth import (
    COOKIE_NAME,
    clear_login_failures,
    create_session,
    credentials_match,
    login_blocked,
    record_login_failure,
    session_email,
)

router = APIRouter(tags=["Cloud"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    settings = get_settings()
    if not settings.cloud_mode:
        return RedirectResponse("/", status_code=303)
    if session_email(request.cookies.get(COOKIE_NAME), settings):
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(request=request, name="login.html", context={"error": ""})


@router.post("/api/cloud/login")
def login(request: Request, email: str = Form(), password: str = Form()):
    settings = get_settings()
    if not settings.cloud_mode:
        return RedirectResponse("/", status_code=303)
    client_id = request.client.host if request.client else "unknown"
    blocked, retry_after = login_blocked(client_id)
    if blocked:
        response = templates.TemplateResponse(
            request=request,
            name="login.html",
            context={"error": "Trop de tentatives. Réessayez dans quelques minutes."},
            status_code=429,
        )
        response.headers["Retry-After"] = str(retry_after)
        return response
    if not credentials_match(email, password, settings):
        record_login_failure(client_id)
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={"error": "Adresse ou mot de passe incorrect."},
            status_code=401,
        )
    clear_login_failures(client_id)
    response = RedirectResponse("/", status_code=303)
    response.set_cookie(
        COOKIE_NAME,
        create_session(settings.app_admin_email, settings),
        max_age=max(settings.app_session_days, 1) * 86400,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/",
    )
    return response


@router.post("/api/cloud/logout")
def logout():
    response = JSONResponse({"logged_out": True})
    response.delete_cookie(COOKIE_NAME, path="/", secure=get_settings().cloud_mode, samesite="lax")
    return response


@router.get("/api/cloud/status")
def cloud_status(request: Request):
    settings = get_settings()
    return {
        "mode": "cloud" if settings.cloud_mode else "local",
        "connected": settings.cloud_mode,
        "account": session_email(request.cookies.get(COOKIE_NAME), settings) if settings.cloud_mode else "local",
        "automatic_updates": settings.cloud_mode,
        "persistent_database": settings.cloud_mode and not settings.database_path.startswith("./"),
        "backup_enabled": settings.backup_enabled,
        "backup_retention": settings.backup_retention,
    }


@router.get("/api/cloud/backups")
def cloud_backups():
    return {"items": list_backups(), "retention": get_settings().backup_retention}


@router.post("/api/cloud/backups")
def make_cloud_backup():
    if not get_settings().backup_enabled:
        raise HTTPException(status_code=409, detail="Les sauvegardes sont désactivées.")
    return {"created": True, "backup": create_backup()}


@router.get("/api/cloud/backups/{name}")
def download_cloud_backup(name: str):
    path = resolve_backup(name)
    if path is None:
        raise HTTPException(status_code=404, detail="Sauvegarde introuvable.")
    return FileResponse(path, media_type="application/x-sqlite3", filename=path.name)
