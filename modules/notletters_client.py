# modules/notletters_client.py
"""
Клиент для NotLetters API (https://api.notletters.com/v1/).

Поддерживает:
 - get_me()       — получить информацию об аккаунте
 - get_letters()  — получить письма для конкретного email/password
"""
from __future__ import annotations

import html
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx

from .errors import MailAuthError
from .logger import get_logger

logger = get_logger(__name__)

API_BASE = "https://api.notletters.com/v1"


class NotLettersClient:
    """Обёртка над NotLetters REST API для получения писем."""

    def __init__(self, api_key: str, *, timeout: int = 15):
        self.api_key = api_key
        self.timeout = timeout
        self._headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }

    async def get_me(self) -> Dict[str, Any]:
        """Возвращает данные аккаунта."""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(f"{API_BASE}/me", headers=self._headers)
        if response.status_code == 401:
            raise MailAuthError("Неверный API-ключ NotLetters.")
        response.raise_for_status()
        return response.json().get("data", {})

    async def get_letters(
        self,
        email: str,
        password: str,
        *,
        search: Optional[str] = None,
        star: Optional[bool] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """
        Получает письма для конкретного email/password через NotLetters API.
        Возвращает список в том же формате, что IMAPClient.get_messages().
        """
        payload: Dict[str, Any] = {
            "email": email,
            "password": password,
            "filters": {},
        }
        if search:
            payload["filters"]["search"] = search
        if star is not None:
            payload["filters"]["star"] = star

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{API_BASE}/letters",
                json=payload,
                headers=self._headers,
            )

        if response.status_code == 401:
            raise MailAuthError("Неверный email/пароль для NotLetters API.")
        if response.status_code == 403:
            raise MailAuthError("Доступ запрещён — проверьте API-ключ.")
        response.raise_for_status()

        result = response.json()
        # API возвращает {"data": {"letters": [...]}} без поля code
        raw_letters: List[Dict[str, Any]] = result.get("data", {}).get("letters", [])
        messages = [self._normalize(letter) for letter in raw_letters]
        messages.reverse()
        messages = messages[:limit]
        logger.info("NotLetters API: получено %d писем для %s", len(messages), email)
        return messages

    @staticmethod
    def _normalize(letter: Dict[str, Any]) -> Dict[str, Any]:
        ts = letter.get("date", 0)
        try:
            date_str = datetime.fromtimestamp(ts).strftime("%a, %d %b %Y %H:%M:%S")
        except (OSError, OverflowError, ValueError):
            date_str = str(ts)

        sender = letter.get("sender", "")
        sender_name = letter.get("sender_name", "")
        from_str = f"{sender_name} <{sender}>" if sender_name else sender

        body_text: str = letter.get("letter", {}).get("text", "")
        body_html: str = (
            "<pre style='white-space:pre-wrap;margin:0'>"
            + html.escape(body_text)
            + "</pre>"
        ) if body_text else ""

        return {
            "subject": letter.get("subject", ""),
            "from": from_str,
            "to": "",
            "date": date_str,
            "message_id": letter.get("id", ""),
            "body_text": body_text,
            "body_html": body_html,
        }
