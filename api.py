"""HTTP API для Mini App: приём анкеты и «Мои дела».

Слушает только 127.0.0.1 — снаружи до него добираются через Caddy по HTTPS (deploy/https.sh).
Без внешних библиотек: маленький сервер на asyncio, который понимает ровно то, что шлёт Caddy.

Кто спрашивает — определяем по подписи, приложению не доверяем:
  Authorization: tma <initData>   — данные запуска от Telegram (меню, профиль бота, ссылка), подпись по токену бота;
  Authorization: tok <токен>      — токен из адреса кнопки «Открыть Желток» (там Telegram initData не даёт),
                                    его выдаёт бот, подпись тоже по токену бота, срок — 180 дней.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import time
import urllib.parse
from typing import Awaitable, Callable

log = logging.getLogger("zholtok.api")

MAX_HEAD = 16 * 1024
MAX_BODY = 64 * 1024
TOKEN_DAYS = 180
INIT_MAX_AGE = 24 * 3600

Handler = Callable[[int, dict], Awaitable[tuple[int, dict]]]


# ----------------------------------------------------------------- подписи
def check_init_data(init: str, bot_token: str, max_age: int = INIT_MAX_AGE) -> int | None:
    """Проверка initData по алгоритму Telegram: HMAC-SHA256, ключ = HMAC("WebAppData", токен бота).
    Возвращает id пользователя или None."""
    try:
        pairs = urllib.parse.parse_qsl(init, keep_blank_values=True, strict_parsing=True)
    except ValueError:
        return None
    data = dict(pairs)
    got = data.pop("hash", "")
    if not got or len(pairs) != len(data) + 1:          # повтор ключей = подделка
        return None
    check = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    want = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(want, got):
        return None
    try:
        if time.time() - int(data.get("auth_date", "0")) > max_age:
            return None
        uid = int(json.loads(data.get("user", "{}"))["id"])
    except (ValueError, KeyError, TypeError):
        return None
    return uid if uid > 0 else None


def _token_key(bot_token: str) -> bytes:
    return hmac.new(b"zholtok-app-token", bot_token.encode(), hashlib.sha256).digest()


def make_token(uid: int, bot_token: str, days: int = TOKEN_DAYS, now: float | None = None) -> str:
    exp = int((now or time.time()) + days * 86400)
    msg = f"{uid}.{exp}"
    sig = hmac.new(_token_key(bot_token), msg.encode(), hashlib.sha256).hexdigest()[:40]
    return f"{msg}.{sig}"


def check_token(tok: str, bot_token: str) -> int | None:
    try:
        uid_s, exp_s, sig = tok.split(".")
        uid, exp = int(uid_s), int(exp_s)
    except ValueError:
        return None
    want = hmac.new(_token_key(bot_token), f"{uid}.{exp}".encode(), hashlib.sha256).hexdigest()[:40]
    if not hmac.compare_digest(want, sig) or exp < time.time() or uid <= 0:
        return None
    return uid


def auth(header: str, bot_token: str) -> int | None:
    kind, _, value = (header or "").partition(" ")
    if kind == "tma":
        return check_init_data(value, bot_token)
    if kind == "tok":
        return check_token(value, bot_token)
    return None


# ----------------------------------------------------------------- ограничение частоты
class RateLimit:
    def __init__(self, per_minute: int):
        self.per_minute, self.hits = per_minute, {}

    def ok(self, key) -> bool:
        now = time.monotonic()
        q = [t for t in self.hits.get(key, []) if now - t < 60]
        if len(q) >= self.per_minute:
            self.hits[key] = q
            return False
        q.append(now)
        self.hits[key] = q
        if len(self.hits) > 50_000:            # не даём словарю расти бесконечно
            self.hits = {k: v for k, v in self.hits.items() if v and now - v[-1] < 60}
        return True


# ----------------------------------------------------------------- приложение
class Api:
    """routes: {("POST", "/api/me"): handler}. handler(uid, body) -> (status, json). Все маршруты, кроме
    /api/health, требуют подписи."""

    def __init__(self, bot_token: str, routes: dict[tuple[str, str], Handler], limits: dict[str, int] | None = None):
        self.bot_token, self.routes = bot_token, routes
        self.limits = {path: RateLimit(n) for path, n in (limits or {}).items()}
        self.default_limit = RateLimit(60)

    async def dispatch(self, method: str, path: str, headers: dict, body: bytes) -> tuple[int, dict]:
        path = path.split("?", 1)[0]
        if path == "/api/health":
            return 200, {"ok": True, "v": 1}
        handler = self.routes.get((method, path))
        if handler is None:
            return 404, {"ok": False, "error": "Не найдено"}
        uid = auth(headers.get("authorization", ""), self.bot_token)
        if uid is None:
            return 401, {"ok": False, "error": "Откройте приложение из чата с ботом ещё раз."}
        if not self.limits.get(path, self.default_limit).ok(uid):
            return 429, {"ok": False, "error": "Слишком много запросов. Подождите минуту."}
        try:
            data = json.loads(body or b"{}")
            if not isinstance(data, dict):
                raise ValueError
        except ValueError:
            return 400, {"ok": False, "error": "Не получилось прочитать данные."}
        try:
            return await handler(uid, data)
        except Exception:  # noqa: BLE001
            log.exception("api %s", path)
            return 500, {"ok": False, "error": "Что-то пошло не так. Попробуйте ещё раз через минуту."}

    # ------------------------------------------------------------- минимальный HTTP/1.1 (за Caddy)
    async def handle_conn(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        status, payload = 400, {"ok": False, "error": "Плохой запрос"}
        try:
            head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=10)
            if len(head) > MAX_HEAD:
                raise ValueError("head")
            lines = head.decode("latin-1").split("\r\n")
            method, target, _ = lines[0].split(" ", 2)
            headers = {}
            for line in lines[1:]:
                if ":" in line:
                    k, v = line.split(":", 1)
                    headers[k.strip().lower()] = v.strip()
            if "chunked" in headers.get("transfer-encoding", "").lower():
                raise ValueError("chunked")
            length = int(headers.get("content-length", "0") or 0)
            if length < 0 or length > MAX_BODY:
                status, payload = 413, {"ok": False, "error": "Слишком большой запрос"}
                raise ValueError("body")
            body = await asyncio.wait_for(reader.readexactly(length), timeout=10) if length else b""
            status, payload = await self.dispatch(method.upper(), target, headers, body)
        except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, asyncio.TimeoutError, ValueError, UnicodeError):
            pass
        except Exception:  # noqa: BLE001
            log.exception("api conn")
            status, payload = 500, {"ok": False, "error": "Ошибка сервера"}
        data = json.dumps(payload, ensure_ascii=False).encode()
        reason = {200: "OK", 400: "Bad Request", 401: "Unauthorized", 404: "Not Found", 413: "Payload Too Large",
                  429: "Too Many Requests", 500: "Internal Server Error"}.get(status, "OK")
        try:
            writer.write(f"HTTP/1.1 {status} {reason}\r\nContent-Type: application/json; charset=utf-8\r\n"
                         f"Content-Length: {len(data)}\r\nCache-Control: no-store\r\nConnection: close\r\n\r\n".encode()
                         + data)
            await writer.drain()
        except (ConnectionError, OSError):
            pass
        finally:
            writer.close()

    async def serve(self, port: int, host: str = "127.0.0.1") -> asyncio.base_events.Server:
        server = await asyncio.start_server(self.handle_conn, host, port, limit=MAX_HEAD)
        log.info("API слушает %s:%d", host, port)
        return server
