IMAP_SERVERS = {
    "rambler.ru": "imap.rambler.ru",
    "lenta.ru": "imap.rambler.ru",
    "myrambler.ru": "imap.rambler.ru",
    "ro.ru": "imap.rambler.ru",
    "rambler.ua": "imap.rambler.ru",
    "yandex.ru": "imap.yandex.ru",
    "mail.ru": "imap.mail.ru",
    "outlook.com": "imap-mail.outlook.com",
    "hotmail.com": "imap-mail.outlook.com",
    "icloud.com": "imap.mail.me.com",
}

DEFAULT_PORT = 993

# Возможные названия папки спама на серверах Rambler.
# Проверяем по очереди — первый найденный будет использован.
RAMBLER_SPAM_FOLDERS = [
    "Spam",
    "Спам",
    "SPAM",
    "Junk",
    "Junk Email",
    "Junk Mail",
]
