# modules/imap_client.py  (или твой путь)
import asyncio
import html
import imaplib
import email
from email.header import decode_header, make_header
from email.message import Message
from typing import Any, Dict, List, Optional, Tuple

from .imap_config import IMAP_SERVERS, DEFAULT_PORT
from .errors import UnknownMailDomainError, MailAuthError
from .logger import get_logger

logger = get_logger(__name__)


class IMAPClient:
    """Асинхронный IMAP клиент: подключение, авторизация, получение писем."""

    def __init__(self, email_addr: str, password: str, *, timeout: int = 30):
        self.email = email_addr
        self.password = password
        self.timeout = timeout
        self.server: Optional[imaplib.IMAP4_SSL] = None
        self._connected_host: Optional[str] = None  # удобно логировать, к какому хосту подключились

    # ---------- candidates & threading ----------

    def _candidate_hosts(self) -> List[str]:
        """
        Возвращает список кандидатов для подключения.
        Если домен известен — он один.
        Если нет — пробуем оба кастомных: firstmail, notletters.
        """
        domain = self.email.split("@")[-1].strip().lower()
        host = IMAP_SERVERS.get(domain)
        if host:
            return [host]
        # фолбэк-кандидаты (порядок важен)
        return ["imap.firstmail.ltd", "imap.notletters.com"]

    async def _to_thread(self, func, *args, **kwargs):
        """Запуск блокирующих вызовов imaplib в отдельном потоке."""
        return await asyncio.to_thread(func, *args, **kwargs)

    # ---------- connect / disconnect ----------

    async def connect(self):
        """Пробует все кандидаты по очереди. Успешный — фиксируем и выходим."""
        last_error: Optional[Exception] = None

        for host in self._candidate_hosts():
            try:
                # timeout поддерживается в Python 3.11: imaplib.IMAP4_SSL(..., timeout=...)
                self.server = await self._to_thread(
                    imaplib.IMAP4_SSL, host, DEFAULT_PORT, None, None, None, self.timeout
                )
                result, _ = await self._to_thread(self.server.login, self.email, self.password)
                if result == "OK":
                    self._connected_host = host
                    logger.info("Успешный вход в %s (host=%s)", self.email, host)
                    return
                # логин вернул не OK — закрываем соединение и пробуем следующий
                try:
                    await self._to_thread(self.server.logout)
                except Exception:
                    pass
                self.server = None
                last_error = MailAuthError(f"Не удалось войти в почту на {host}")
            except (imaplib.IMAP4.error, OSError) as e:
                # любые ошибки сокета/SSL/IMAP — пробуем следующий хост
                logger.debug("Ошибка подключения к %s: %s", host, e)
                last_error = e
                self.server = None
                continue

        # если сюда дошли — ни один хост не подошёл
        raise MailAuthError(
            f"Не удалось подключиться ни к одному IMAP-хосту для {self.email}. "
            f"Пробовали: {', '.join(self._candidate_hosts())}. "
            f"Последняя ошибка: {last_error}"
        )

    async def disconnect(self):
        """Разрыв соединения."""
        if self.server:
            try:
                await self._to_thread(self.server.logout)
                logger.info("Отключено от %s (host=%s)", self.email, self._connected_host or "-")
            except Exception as e:
                logger.warning("Ошибка при отключении: %s", e)
            finally:
                self.server = None
                self._connected_host = None

    # ---------- API ----------

    async def get_messages(
        self,
        *,
        mailbox: str = "INBOX",
        criteria: str = "ALL",
        limit: int = 50,
        mark_seen: bool = False,
    ) -> List[Dict[str, Any]]:
        """Возвращает список писем в виде словарей (включая HTML)."""
        if not self.server:
            raise MailAuthError("Нет активного соединения IMAP.")

        typ, _ = await self._to_thread(self.server.select, mailbox, readonly=True)
        if typ != "OK":
            raise MailAuthError(f"Не удалось выбрать ящик {mailbox}")

        typ, data = await self._to_thread(self.server.search, None, criteria)
        if typ != "OK":
            raise MailAuthError("Ошибка поиска писем.")

        msg_ids = (data[0] or b"").split()
        if not msg_ids:
            return []

        msg_ids = msg_ids[-limit:]  # последние N
        fetch_items = "(RFC822)" if mark_seen else "(BODY.PEEK[])"

        messages: List[Dict[str, Any]] = []

        for msg_id in msg_ids:
            typ, data = await self._to_thread(self.server.fetch, msg_id, fetch_items)
            if typ != "OK" or not data or data[0] is None:
                continue

            raw_email = data[0][1]
            msg: Message = email.message_from_bytes(raw_email)

            subject = self._decode_maybe_encoded(msg.get("Subject"))
            from_ = self._decode_maybe_encoded(msg.get("From"))
            to = self._decode_maybe_encoded(msg.get("To"))
            date = self._decode_maybe_encoded(msg.get("Date"))
            msg_id_val = msg.get("Message-ID", "")

            body_text, body_html = self._extract_bodies(msg)
            if not body_html and body_text:
                body_html = self._plaintext_to_minimal_html(body_text)

            messages.append(
                {
                    "subject": subject,
                    "from": from_,
                    "to": to,
                    "date": date,
                    "message_id": msg_id_val,
                    "body_text": body_text,
                    "body_html": body_html,
                }
            )

        messages.reverse()  # новые сверху
        logger.info("Загружено писем: %s (host=%s)", len(messages), self._connected_host or "-")
        return messages

    # ---------- utils ----------

    def _decode_maybe_encoded(self, value: Optional[str]) -> str:
        """Декодирует RFC2047-заголовки вроде =?utf-8?B?...?="""
        if value is None:
            return ""
        try:
            return str(make_header(decode_header(value)))
        except Exception:
            return value

    def _extract_bodies(self, msg: Message) -> Tuple[str, str]:
        """Возвращает текстовую и HTML-версии тела письма."""
        plain_parts: List[str] = []
        html_parts: List[str] = []

        if msg.is_multipart():
            for part in msg.walk():
                ctype = part.get_content_type()
                disp = part.get("Content-Disposition", "")
                if part.get_content_maintype() == "multipart":
                    continue
                if disp and "attachment" in disp.lower():
                    continue

                payload = part.get_payload(decode=True)
                charset = part.get_content_charset() or "utf-8"

                try:
                    text = (payload or b"").decode(charset, errors="replace")
                except Exception:
                    text = (payload or b"").decode("utf-8", errors="replace")

                if ctype == "text/plain":
                    plain_parts.append(text)
                elif ctype == "text/html":
                    html_parts.append(text)
        else:
            payload = msg.get_payload(decode=True)
            charset = msg.get_content_charset() or "utf-8"
            text = (payload or b"").decode(charset, errors="replace")
            if msg.get_content_type() == "text/html":
                html_parts.append(text)
            else:
                plain_parts.append(text)

        return ("\n".join(plain_parts).strip(), "\n".join(html_parts).strip())

    def _plaintext_to_minimal_html(self, text: str) -> str:
        """Простой и безопасный фолбэк: экранируем и переведём \\n в <pre>."""
        return "<pre style='white-space:pre-wrap;margin:0'>" + html.escape(text) + "</pre>"
