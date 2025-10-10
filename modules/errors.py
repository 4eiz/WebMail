class MailAuthError(Exception):
    """Ошибка при авторизации в почте."""
    pass

class UnknownMailDomainError(Exception):
    """Ошибка, если домен почты не поддерживается."""
    pass
