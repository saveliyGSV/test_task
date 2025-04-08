from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
from uuid import uuid4
from datetime import datetime, timedelta
from cryptography.fernet import Fernet
import asyncpg
import asyncio
import os
import uvicorn

# Генерация ключа шифрования (в проде — хранить безопасно)
FERNET_KEY = Fernet.generate_key()
fernet = Fernet(FERNET_KEY)

# Псевдо-кеш (можно заменить на Redis/CacheTools)
memory_cache = {}

# Настройки окружения (использовать os.environ в docker)
DB_SETTINGS = {
    "user": os.getenv("POSTGRES_USER", "postgres"),
    "password": os.getenv("POSTGRES_PASSWORD", "postgres"),
    "database": os.getenv("POSTGRES_DB", "secrets_db"),
    "host": os.getenv("POSTGRES_HOST", "localhost"),
    "port": int(os.getenv("POSTGRES_PORT", 5432)),
}

# FastAPI и CORS
app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Pydantic схемы
class SecretCreate(BaseModel):
    secret: str
    passphrase: Optional[str] = None
    ttl_seconds: Optional[int] = 3600

class SecretResponse(BaseModel):
    secret_key: str

class SecretOut(BaseModel):
    secret: str

class DeleteResponse(BaseModel):
    status: str

# Подключение к БД
@app.on_event("startup")
async def startup():
    app.state.db = await asyncpg.create_pool(**DB_SETTINGS)
    async with app.state.db.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS logs (
                id SERIAL PRIMARY KEY,
                action TEXT,
                secret_key TEXT,
                ip TEXT,
                created_at TIMESTAMP DEFAULT now()
            );
        """)

# Хелперы
async def log_action(db, action, secret_key, ip):
    await db.execute(
        "INSERT INTO logs (action, secret_key, ip) VALUES ($1, $2, $3)",
        action, secret_key, ip
    )

# Эндпоинты
@app.post("/secret", response_model=SecretResponse)
async def create_secret(data: SecretCreate, request: Request):
    secret_key = str(uuid4())
    encrypted = fernet.encrypt(data.secret.encode())
    expires_at = datetime.utcnow() + timedelta(seconds=data.ttl_seconds or 3600)

    memory_cache[secret_key] = {
        "secret": encrypted,
        "passphrase": data.passphrase,
        "expires_at": expires_at,
    }

    await log_action(app.state.db, "created", secret_key, request.client.host)
    return {"secret_key": secret_key}

@app.get("/secret/{secret_key}", response_model=SecretOut)
async def get_secret(secret_key: str, request: Request):
    secret_data = memory_cache.pop(secret_key, None)
    if not secret_data:
        raise HTTPException(status_code=404, detail="Secret not found or already retrieved")

    if datetime.utcnow() > secret_data["expires_at"]:
        raise HTTPException(status_code=410, detail="Secret expired")

    await log_action(app.state.db, "retrieved", secret_key, request.client.host)
    decrypted = fernet.decrypt(secret_data["secret"]).decode()
    return {"secret": decrypted}

@app.delete("/secret/{secret_key}", response_model=DeleteResponse)
async def delete_secret(secret_key: str, passphrase: Optional[str] = None, request: Request = None):
    secret_data = memory_cache.get(secret_key)
    if not secret_data:
        raise HTTPException(status_code=404, detail="Secret not found or already retrieved")

    if secret_data["passphrase"] and secret_data["passphrase"] != passphrase:
        raise HTTPException(status_code=403, detail="Incorrect passphrase")

    memory_cache.pop(secret_key)
    await log_action(app.state.db, "deleted", secret_key, request.client.host)
    return {"status": "secret_deleted"}

# Запрет кеширования на клиенте
@app.middleware("http")
async def add_no_cache_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

# Фоновая задача очистки
async def cleanup_expired():
    while True:
        now = datetime.utcnow()
        to_delete = [key for key, val in memory_cache.items() if val["expires_at"] < now]
        for key in to_delete:
            memory_cache.pop(key)
        await asyncio.sleep(60)

@app.on_event("startup")
async def start_cleanup():
    asyncio.create_task(cleanup_expired())

# Запуск (для dev)
if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
