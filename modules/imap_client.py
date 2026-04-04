# modules/imap_client.py
import asyncio
import html
import imaplib
import socket
import email
from email.header import decode_header, make_header
from email.message import Message
from typing import Any, Dict, List, Optional, Tuple

from .imap_config import IMAP_SERVERS, DEFAULT_PORT, RAMBLER_SPAM_FOLDERS
from .errors import UnknownMailDomainError, MailAuthError
from .logger import get_logger

logger = get_logger(__name__)


class IMAPClient:
    """Асинхронный IMAP клиент: подключение, авторизация, получение писем."""

    # Таймаут снижен до 8 сек чтобы быстрее переключаться на API
    def __init__(self, email_addr: str, password: str, *, timeout: int = 8):
        self.email = email_addr
        self.password = password
        self.timeout = timeout
        self.server: Optional[imaplib.IMAP4_SSL] = None
        self._connected_host: Optional[str] = None

    def _candidate_hosts(self) -> List[str]:
        """
        Возвращает список IMAP-кандидатов.
        Если домен известен — его хост.
        Если нет — пробуем только firstmail.
        """
        domain = self.email.split("@")[-1].strip().lower()
        host = IMAP_SERVERS.get(domain)
        if host:
            return [host]
        return ["imap.firstmail.ltd"]

    def _is_rambler(self) -> bool:
        """Проверяет, является ли адрес Rambler-почтой."""
        domain = self.email.split("@")[-1].strip().lower()
        return domain in ("rambler.ru", "lenta.ru", "myrambler.ru", "ro.ru", "rambler.ua")

    async def _to_thread(self, func, *args, **kwargs):
        """Запуск блокирующих вызовов в отдельном потоке."""
        return await asyncio.to_thread(func, *args, **kwargs)

    def _connect_imap_ssl(self, host: str, port: int) -> imaplib.IMAP4_SSL:
        """
        Создаёт IMAP4_SSL с таймаутом.
        Используем socket.setdefaulttimeout — работает на всех версиях Python.
        """
        old_timeout = socket.getdefaulttimeout()
        socket.setdefaulttimeout(self.timeout)
        try:
            return imaplib.IMAP4_SSL(host, port)
        finally:
            socket.setdefaulttimeout(old_timeout)

    async def connect(self):
        """Пробует все кандидаты по очереди. Успешный — фиксируем и выходим."""
        last_error: Optional[Exception] = None

        for host in self._candidate_hosts():
            try:
                self.server = await self._to_thread(
                    self._connect_imap_ssl, host, DEFAULT_PORT
                )
                result, _ = await self._to_thread(self.server.login, self.email, self.password)
                if result == "OK":
                    self._connected_host = host
                    logger.info("Успешный вход в %s (host=%s)", self.email, host)
                    return
                try:
                    await self._to_thread(self.server.logout)
                except Exception:
                    pass
                self.server = None
                last_error = MailAuthError(f"Не удалось войти в почту на {host}")
            except (imaplib.IMAP4.error, OSError, socket.timeout) as e:
                logger.debug("Ошибка подключения к %s: %s", host, e)
                last_error = e
                self.server = None
                continue

        raise MailAuthError(
            f"Не удалось подключиться ни к одному IMAP-хосту для {self.email}. "
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

    async def _find_spam_folder(self) -> Optional[str]:
        """
        Определяет реальное имя папки спама из списка возможных вариантов.
        Возвращает первое найденное имя или None.
        """
        if not self.server:
            return None
        try:
            typ, folders = await self._to_thread(self.server.list)
            if typ != "OK":
                return None
            folder_names: List[str] = []
            for f in (folders or []):
                if isinstance(f, bytes):
                    # Формат: (\Noselect) "/" "INBOX"
                    parts = f.decode(errors="replace").split('"')
                    name = parts[-1].strip().strip('"') if len(parts) >= 1 else ""
                    if name:
                        folder_names.append(name)
            for candidate in RAMBLER_SPAM_FOLDERS:
                if candidate in folder_names:
                    return candidate
        except Exception as e:
            logger.warning("Не удалось получить список папок: %s", e)
        return None

    async def get_messages(
        self,
        *,
        mailbox: str = "INBOX",
        criteria: str = "ALL",
        limit: int = 50,
        mark_seen: bool = False,
    ) -> List[Dict[str, Any]]:
        """Возвращает список писем в виде словарей (включая HTML).

        Для Rambler-аккаунтов автоматически добавляет письма из папки Спам,
        чтобы отображались все письма включая спам.
        """
        if not self.server:
            raise MailAuthError("Нет активного соединения IMAP.")

        messages = await self._get_messages_from_mailbox(
            mailbox=mailbox, criteria=criteria, limit=limit, mark_seen=mark_seen
        )

        # Для Rambler — дополнительно грузим спам-папку
        if self._is_rambler():
            spam_folder = await self._find_spam_folder()
            if spam_folder:
                logger.info("Rambler: загружаю спам из папки '%s'", spam_folder)
                try:
                    spam_messages = await self._get_messages_from_mailbox(
                        mailbox=spam_folder,
                        criteria=criteria,
                        limit=limit,
                        mark_seen=mark_seen,
                        is_spam=True,
                    )
                    messages = messages + spam_messages
                    # Сортируем все письма по дате (новые сначала, без дат — в конец)
                    messages.sort(key=lambda m: m.get("date") or "", reverse=True)
                    logger.info(
                        "Rambler: итого писем после добавления спама: %s", len(messages)
                    )
                except Exception as e:
                    logger.warning("Не удалось загрузить спам-папку '%s': %s", spam_folder, e)
            else:
                logger.info("Rambler: папка спама не найдена, показываем только INBOX")

        return messages

    async def _get_messages_from_mailbox(
        self,
        *,
        mailbox: str,
        criteria: str,
        limit: int,
        mark_seen: bool,
        is_spam: bool = False,
    ) -> List[Dict[str, Any]]:
        """Вспомогательный метод: получает письма из конкретного ящика/папки."""
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

        msg_ids = msg_ids[-limit:]
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
                    "is_spam": is_spam,
                    "mailbox": mailbox,
                }
            )

        messages.reverse()
        logger.info(
            "Загружено писем из '%s': %s (host=%s)",
            mailbox,
            len(messages),
            self._connected_host or "-",
        )
        return messages

    def _decode_maybe_encoded(self, value: Optional[str]) -> str:
        if value is None:
            return ""
        try:
            return str(make_header(decode_header(value)))
        except Exception:
            return value

    def _extract_bodies(self, msg: Message) -> Tuple[str, str]:
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
        return "<pre style='white-space:pre-wrap;margin:0'>" + html.escape(text) + "</pre>"
