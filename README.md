# 📬 WebMail

![banner](https://i.imgur.com/3spmSzz.png)

**WebMail** is a modern asynchronous web mail client built with **FastAPI**.  
It allows you to log into any email account and view messages directly in your browser.  
The application is implemented in an **OOP** style with a sleek dark-blue interface and fully responsive design.

---

## 🚀 Features

- 🌐 Web interface powered by **FastAPI + Jinja2**
- 📩 IMAP email support (Gmail, Yandex, Mail.ru, Outlook, etc.)
- 🔁 Asynchronous connection and message fetching (`asyncio + imaplib`)
- 🧠 Smart IMAP server detection  
  → if a domain is unknown, the client automatically tries  
  `imap.firstmail.ltd` or `imap.notletters.com`
- 🖤 Dark theme with modern flat design
- 🔐 Session-based authentication (login/logout)
- 🧱 Beautiful colored logging via **RichHandler**

---

## ⚙️ Installation & Setup

### 1. Clone the repository
```bash
git clone https://github.com/4eiz/WebMail.git
cd WebMail
```

### 2. Create virtual environment & install dependencies
```bash
python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # Linux / macOS

pip install -U pip
pip install -r requirements.txt
```

### 3. Run the server
```bash
python main.py
```

or directly via **uvicorn**:

```bash
uvicorn app.web:app --reload
```

After startup, the app will be available at:
```
http://127.0.0.1:8000
```

---

## 🖥️ Interface

- Login form (email + password)
- “Inbox” page with all received emails
- Emails are rendered safely using **sandboxed iframes**  
  (scripts inside the email body won’t be executed)
- Navigation bar displays current user and “Logout” button

---

## 📂 Project Structure

```
WebMail/
├─ main.py                    # Entry point – FastAPI runner
├─ modules/
│   ├─ imap_client.py         # Asynchronous IMAP client
│   ├─ imap_config.py         # IMAP server list
│   ├─ logger.py              # Custom Rich logger
│   └─ errors.py              # Custom exceptions
├─ app/
│   ├─ web.py                 # OOP-style FastAPI application
│   ├─ templates/             # Jinja2 HTML templates (login.html, inbox.html)
│   └─ static/                # CSS, icons, fonts
└─ requirements.txt
```

---

## 🧰 Technologies

| Component | Description |
|------------|-------------|
| **Backend** | FastAPI, asyncio, imaplib |
| **Frontend** | HTML + Jinja2, Tailwind-style CSS |
| **Logging** | RichHandler, Colorama |
| **Session/Auth** | Starlette SessionMiddleware |
| **Design** | Flat UI, dark blue theme |

---

## 🧠 Example Code

```python
client = IMAPClient("example@gmail.com", "password123")

await client.connect()
messages = await client.get_messages(limit=10)

for msg in messages:
    print(msg["subject"], "from", msg["from"])
await client.disconnect()
```

---

## 🪄 Future Improvements

- 🔄 Pagination & mailbox filtering  
- 📎 Attachments download  
- 🔔 Push notifications for new emails  
- 🧩 OAuth authorization (Google, Outlook)  
- 🗄️ Database caching & user profile storage

---

## 📜 License

This project is distributed under the **MIT License**.  
You are free to use, modify, and distribute the code with proper attribution.

---

## 👨‍💻 Author

Developer: **4eiz**  
📧 [GitHub](https://github.com/4eiz)

> Minimalism. Speed. Asynchrony.  
> Everything you need to make email feel modern.
