from __future__ import annotations

import contextlib
import os
import logging
from pathlib import Path
from typing import Optional, Dict, Any, List

from fastapi import FastAPI, Request, Form
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.templating import Jinja2Templates

from modules.imap_client import IMAPClient
from modules.notletters_client import NotLettersClient
from modules.errors import MailAuthError


BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = BASE_DIR / "app" / "templates"
STATIC_DIR = BASE_DIR / "app" / "static"

# Домены, которые обслуживает NotLetters
NOTLETTERS_DOMAINS = {"notletters.com"}


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
        self.app = FastAPI(title="WebMail", version="1.1.0")
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

    # ------------------------------------------------------------------ #
    #  Провайдер: IMAP                                                     #
    # ------------------------------------------------------------------ #

    async def _fetch_messages_imap(
        self, email: str, password: str, limit: int = 20
    ) -> List[Dict[str, Any]]:
        """Получить письма через IMAP (imaplib + SSL)."""
        client = IMAPClient(email, password)
        try:
            await client.connect()
            return await client.get_messages(limit=limit, criteria="ALL", mark_seen=False)
        finally:
            await client.disconnect()

    # ------------------------------------------------------------------ #
    #  Провайдер: NotLetters API                                           #
    # ------------------------------------------------------------------ #

    async def _fetch_messages_notletters_api(
        self, email: str, password: str, limit: int = 20
    ) -> List[Dict[str, Any]]:
        """
        Получить письма через NotLetters REST API.
        API-ключ берётся из переменной окружения NOTLETTERS_API_KEY.
        """
        api_key = os.getenv("NOTLETTERS_API_KEY", "")
        if not api_key:
            raise MailAuthError(
                "Переменная окружения NOTLETTERS_API_KEY не задана. "
                "Используйте IMAP или добавьте ключ в .env."
            )
        client = NotLettersClient(api_key)
        return await client.get_letters(email, password, limit=limit)

    # ------------------------------------------------------------------ #
    #  Диспетчер: выбор провайдера                                         #
    # ------------------------------------------------------------------ #

    async def _fetch_messages(
        self,
        email: str,
        password: str,
        limit: int = 20,
        provider: str = "auto",
    ) -> List[Dict[str, Any]]:
        """
        Маршрутизация по провайдеру:
          - "api"  → NotLetters API
          - "imap" → IMAP
          - "auto" → API если домен в NOTLETTERS_DOMAINS, иначе IMAP
        """
        domain = email.split("@")[-1].strip().lower()

        if provider == "api":
            return await self._fetch_messages_notletters_api(email, password, limit)
        elif provider == "imap":
            return await self._fetch_messages_imap(email, password, limit)
        else:  # auto
            if domain in NOTLETTERS_DOMAINS:
                return await self._fetch_messages_notletters_api(email, password, limit)
            return await self._fetch_messages_imap(email, password, limit)

    # ------------------------------------------------------------------ #
    #  Роуты                                                               #
    # ------------------------------------------------------------------ #

    def _register_routes(self) -> None:

        @self.app.get("/", tags=["ui"])
        async def index(request: Request):
            if self._get_credentials(request):
                return RedirectResponse(url="/inbox", status_code=303)
            return self.templates.TemplateResponse("login.html", {"request": request})

        @self.app.post("/login", tags=["auth"])
        async def login(
            request: Request,
            email: str = Form(...),
            password: str = Form(...),
            provider: str = Form(default="auto"),
        ):
            """
            Принимает дополнительный параметр provider из формы:
              - auto  (по умолчанию) — автовыбор по домену
              - imap  — всегда IMAP
              - api   — всегда NotLetters API
            """
            email = email.strip()
            provider = provider.strip().lower()
            if provider not in ("auto", "imap", "api"):
                provider = "auto"

            # Проверяем подключение при логине
            try:
                if provider == "imap" or (
                    provider == "auto"
                    and email.split("@")[-1].strip().lower() not in NOTLETTERS_DOMAINS
                ):
                    # Для IMAP проверяем через IMAPClient.connect()
                    client = IMAPClient(email, password)
                    try:
                        await client.connect()
                    finally:
                        with contextlib.suppress(Exception):
                            await client.disconnect()
                else:
                    # Для NotLetters API проверяем через get_letters с limit=1
                    api_key = os.getenv("NOTLETTERS_API_KEY", "")
                    if not api_key:
                        raise MailAuthError(
                            "NOTLETTERS_API_KEY не задан. Используйте IMAP."
                        )
                    nl_client = NotLettersClient(api_key)
                    await nl_client.get_letters(email, password, limit=1)
            except Exception as exc:
                return self.templates.TemplateResponse(
                    "login.html",
                    {"request": request, "error": str(exc)},
                    status_code=401,
                )

            request.session["email"] = email
            request.session["password"] = password
            request.session["provider"] = provider
            return RedirectResponse(url="/inbox", status_code=303)

        @self.app.post("/logout", tags=["auth"])
        async def logout(request: Request):
            request.session.clear()
            return RedirectResponse(url="/", status_code=303)

        @self.app.get("/inbox", tags=["ui"])
        async def inbox(request: Request, limit: int = 20):
            creds = self._get_credentials(request)
            if not creds:
                return RedirectResponse(url="/", status_code=303)
            provider = request.session.get("provider", "auto")
            try:
                messages = await self._fetch_messages(
                    creds["email"], creds["password"], limit=limit, provider=provider
                )
            except Exception as e:
                self.logger.warning("Ошибка получения писем: %s", e)
                request.session.clear()
                return RedirectResponse(url="/", status_code=303)

            return self.templates.TemplateResponse(
                "inbox.html",
                {
                    "request": request,
                    "email": creds["email"],
                    "messages": messages,
                    "limit": limit,
                    "provider": provider,
                },
            )

    def get_app(self) -> FastAPI:
        return self.app


def create_app() -> FastAPI:
    secret = os.getenv("APP_SECRET_KEY", "dev-secret-change-me")
    logger = logging.getLogger("app.web")
    web = WebMailApp(secret_key=secret, logger=logger)
    return web.get_app()


app = create_app()
