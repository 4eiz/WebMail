# app/web.py
from __future__ import annotations

import os
import logging
from pathlib import Path
from typing import Optional, Dict, Any, List

from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.templating import Jinja2Templates

from modules.imap_client import IMAPClient


BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        return response


class WebMailApp:
    def __init__(self, *, secret_key: str, logger: Optional[logging.Logger] = None):
        self._validate_paths()
        self.app = FastAPI(title="WebMail", version="1.0.0")
        self.app.add_middleware(SessionMiddleware, secret_key=secret_key)
        self.app.add_middleware(SecurityHeadersMiddleware)

        self.app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
        self.templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
        self.logger = logger or logging.getLogger("app.web")

        self._register_routes()

    def _validate_paths(self) -> None:
        if not TEMPLATES_DIR.exists():
            raise RuntimeError(f"Templates directory not found: {TEMPLATES_DIR}")
        if not STATIC_DIR.exists():
            raise RuntimeError(f"Static directory not found: {STATIC_DIR}")

    def _get_credentials(self, request: Request) -> Optional[Dict[str, str]]:
        email = request.session.get("email")
        password = request.session.get("password")
        return {"email": email, "password": password} if email and password else None

    async def _fetch_messages(self, email: str, password: str, limit: int = 20) -> List[Dict[str, Any]]:
        client = IMAPClient(email, password)
        try:
            await client.connect()
            return await client.get_messages(limit=limit, criteria="ALL", mark_seen=False)
        finally:
            await client.disconnect()

    def _register_routes(self) -> None:
        @self.app.get("/", tags=["ui"])
        async def index(request: Request):
            if self._get_credentials(request):
                return RedirectResponse(url="/inbox", status_code=303)
            return self.templates.TemplateResponse("login.html", {"request": request})

        @self.app.post("/login", tags=["auth"])
        async def login(request: Request, email: str = Form(...), password: str = Form(...)):
            client = IMAPClient(email, password)
            try:
                await client.connect()
            except Exception as e:
                raise HTTPException(status_code=401, detail=f"Не удалось войти: {e}")
            finally:
                await client.disconnect()

            request.session["email"] = email
            request.session["password"] = password
            return RedirectResponse(url="/inbox", status_code=303)

        @self.app.post("/logout", tags=["auth"])
        async def logout(request: Request):
            # Чистим сессию и отправляем на логин
            request.session.clear()
            return RedirectResponse(url="/", status_code=303)

        @self.app.get("/inbox", tags=["ui"])
        async def inbox(request: Request, limit: int = 20):
            creds = self._get_credentials(request)
            if not creds:
                return RedirectResponse(url="/", status_code=303)
            try:
                messages = await self._fetch_messages(creds["email"], creds["password"], limit=limit)
            except Exception as e:
                self.logger.warning("Ошибка получения писем: %s", e)
                request.session.clear()
                return RedirectResponse(url="/", status_code=303)

            return self.templates.TemplateResponse(
                "inbox.html",
                {"request": request, "email": creds["email"], "messages": messages, "limit": limit},
            )

    def get_app(self) -> FastAPI:
        return self.app


def create_app() -> FastAPI:
    secret = os.getenv("APP_SECRET_KEY", "dev-secret-change-me")
    logger = logging.getLogger("app.web")
    web = WebMailApp(secret_key=secret, logger=logger)
    return web.get_app()


app = create_app()
