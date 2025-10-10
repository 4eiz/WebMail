# main.py
import os
import logging
import asyncio
import uvicorn

from modules.logger import init_logging, get_logger
from app.web import create_app

# Логгер твоего проекта
init_logging(level=logging.INFO, log_file="app.log")
logger = get_logger(__name__)
logger.info("Приложение запущено")

# Можно задать секрет через переменные окружения
os.environ.setdefault("APP_SECRET_KEY", "dev-secret-change-me")

async def main():
    app = create_app()
    config = uvicorn.Config(
        app=app,
        host="127.0.0.1",
        port=8000,
        log_level="info",
        loop="asyncio",
        reload=False,
    )
    server = uvicorn.Server(config)
    await server.serve()

if __name__ == "__main__":
    asyncio.run(main())
