"""Прогон логики бота без Telegram: aiogram подменяется заглушками, вызываются
настоящие обработчики из bot.py. Пишет стенограмму главного сценария в transcript.md.
Запуск: python test_bot_flow.py
"""
import asyncio
import datetime as dt
import io
import os
import re
import sys
import tempfile
import time
import types


# ---------------- заглушки aiogram
class _Magic:
    def __getattr__(self, name): return self
    def __call__(self, *a, **k): return self
    def __eq__(self, other): return self
    __hash__ = object.__hash__


class _Router:
    message = callback_query = pre_checkout_query = staticmethod(lambda *a, **k: (lambda fn: fn))


class _Obj:
    def __init__(self, *a, **k):
        self.args = a
        self.__dict__.update(k)


mods = {n: types.ModuleType(n) for n in [
    "aiogram", "aiogram.client", "aiogram.client.default", "aiogram.enums", "aiogram.filters", "aiogram.fsm",
    "aiogram.fsm.context", "aiogram.fsm.state", "aiogram.fsm.storage", "aiogram.fsm.storage.memory", "aiogram.types"]}
mods["aiogram"].Bot = _Obj; mods["aiogram"].Dispatcher = _Obj; mods["aiogram"].F = _Magic(); mods["aiogram"].Router = _Router
mods["aiogram.client.default"].DefaultBotProperties = _Obj
mods["aiogram.enums"].ParseMode = _Magic()
for n in ("Command", "CommandObject", "CommandStart"):
    setattr(mods["aiogram.filters"], n, _Obj)
mods["aiogram.fsm.context"].FSMContext = object
mods["aiogram.fsm.state"].State = lambda *a, **k: object()
mods["aiogram.fsm.state"].StatesGroup = object
mods["aiogram.fsm.storage.memory"].MemoryStorage = _Obj
for n in ("BufferedInputFile", "CallbackQuery", "InlineKeyboardButton", "InlineKeyboardMarkup", "KeyboardButton",
          "MenuButtonWebApp", "Message", "ReplyKeyboardMarkup", "WebAppInfo"):
    setattr(mods["aiogram.types"], n, _Obj)
sys.modules.update(mods)

TMP = tempfile.mkdtemp()
os.environ.update(BOT_TOKEN="test", KEY_RATE="16", DB_PATH=os.path.join(TMP, "t.sqlite3"),
                  MINIAPP_URL="https://example.github.io/zholtok/", BOT_LINK="t.me/zholtok_bot")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bot  # noqa: E402
import engine  # noqa: E402


# ---------------- фейковый Telegram
class State:
    def __init__(self): self.data, self.state = {}, None
    async def get_data(self): return dict(self.data)
    async def set_data(self, d): self.data = dict(d)
    async def update_data(self, **k): self.data.update(k)
    async def set_state(self, s): self.state = s
    async def clear(self): self.data, self.state = {}, None


class Chat: id = 1001
class User: id = 1001


LOG = []


class Msg:
    def __init__(self, text=""):
        self.text, self.chat, self.from_user = text, Chat(), User()
        if text:
            LOG.append(("user", text, None))
    async def answer(self, text, reply_markup=None, **k):
        LOG.append(("bot", text, reply_markup)); return self
    async def answer_document(self, file, caption=""):
        LOG.append(("file", file, caption))
    async def edit_reply_markup(self, reply_markup=None): pass


class CB:
    def __init__(self, data, label=None):
        self.data, self.message = data, Msg()
        LOG.append(("tap", label or data, None))
    async def answer(self, *a, **k): pass


class FakeBot:
    invoices = []
    async def send_invoice(self, **k): FakeBot.invoices.append(k)
    async def send_message(self, chat_id, text, **k):
        if chat_id == 666:
            raise RuntimeError("Forbidden: bot was blocked by the user")
        LOG.append(("bot", text, k.get("reply_markup")))
    async def send_document(self, chat_id, document, **k): LOG.append(("file", document, k.get("caption", "")))


def buttons():
    for kind, _, mk in reversed(LOG):
        if kind == "bot" and mk is not None and hasattr(mk, "inline_keyboard"):
            return [(b.text, b.callback_data) for row in mk.inline_keyboard for b in row]
    return []


def btn(prefix_or_text):
    for t, d in buttons():
        if d == prefix_or_text or t == prefix_or_text or d.startswith(prefix_or_text) or t.startswith(prefix_or_text):
            return CB(d, f"[{t}]")
    raise AssertionError(f"нет кнопки {prefix_or_text!r}; есть: {buttons()}")


def last_bot_text():
    return next(t for k, t, _ in reversed(LOG) if k == "bot")


def example_text(q):
    ex = q.get("example")
    if q["type"] == "date" and isinstance(ex, str) and ex.endswith("d"):
        return (engine.today() - dt.timedelta(days=abs(int(ex[:-1])))).strftime("%d.%m.%Y")
    return ex


async def answer_current(st, override=None):
    doc = bot.CAT.docs[st.data["doc"]]
    q = next(x for x in doc["questions"] if x["key"] == st.data["cur"])
    ex = (override or {}).get(q["key"], example_text(q))
    if q["type"] == "choice":
        i = [o["v"] for o in q["options"]].index(ex)
        await bot.on_choice(CB(f"a:{i}", f"[{q['options'][i]['label']}]"), st)
    elif q["type"] == "yesno":
        await bot.on_choice(CB("a:y" if ex else "a:n", "[Да]" if ex else "[Нет]"), st)
    elif q["type"] == "multi":
        for v in ex:
            i = [o["v"] for o in q["options"]].index(v)
            await bot.on_multi(CB(f"m:{i}", f"[{q['options'][i]['label']}]"), st)
        await bot.on_multi(CB("m:done", "[Готово]"), st)
    else:
        await bot.on_text(Msg(str(ex)), st)


async def fill_all(st, override=None, limit=80):
    for _ in range(limit):
        if st.state is None:
            return
        await answer_current(st, override)
    raise AssertionError("анкета не завершилась")


def write_transcript(path, start_idx):
    out = ["# Желток — стенограмма реального прогона бота",
           "",
           "Это вывод настоящих обработчиков `bot.py` (Telegram подменён заглушкой), а не макет.",
           "Разметка Telegram показана как есть: `<b>` — жирный, `<i>` — курсив. Кнопки — под сообщениями.",
           ""]
    for kind, text, mk in LOG[start_idx:]:
        if kind == "user":
            out.append(f"**Пользователь:** {text}\n")
        elif kind == "tap":
            out.append(f"**Пользователь нажимает:** {text}\n")
        elif kind == "file":
            out.append(f"**Бот присылает файл:** `{text.kwargs_filename if hasattr(text, 'kwargs_filename') else text.filename}` — {text and ''}{re.sub('<[^>]+>', '', text_caption(text))}\n")
        else:
            body = text.replace("\n", "  \n")
            out.append("**Бот:**  \n" + body)
            if mk is not None:
                rows = getattr(mk, "inline_keyboard", None) or getattr(mk, "keyboard", [])
                out.append("\n" + " · ".join(f"`{b.text}`" for row in rows for b in row)
                           + ("  _(кнопка под полем ввода, открывает Mini App)_" if hasattr(mk, "keyboard") else ""))
            out.append("")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(out))


CAPTIONS = {}


def text_caption(file_obj):
    return CAPTIONS.get(id(file_obj), "")


async def main():
    st, fb = State(), FakeBot()
    orig_doc = Msg.answer_document

    async def answer_document(self, file, caption=""):
        CAPTIONS[id(file)] = caption
        await orig_doc(self, file, caption)
    Msg.answer_document = answer_document

    # ===== Главный сценарий (идёт в стенограмму)
    t0 = len(LOG)
    await bot.cmd_start(Msg("/start"), _Obj(args=""), st)
    assert "Разберёмся с вашей ситуацией" in last_bot_text()
    assert [t for t, _ in buttons()] == ["Начать"], "на пустом главном экране только «Начать»"
    await bot.cb_start(btn("start"))
    await bot.cb_cat(btn("cat:pokupki"))
    await bot.cb_doc(btn("doc:vozvrat_brak"))
    await bot.cb_fill(btn("fill:"), st)
    assert "Перед началом" in last_bot_text()
    await bot.cb_consent(btn("consent:"), st)
    assert "Раздел 1 из 4 · Покупка" in last_bot_text(), last_bot_text()

    for _ in range(3):
        await answer_current(st)
    # Сохранить и выйти -> на главном «Продолжить», ответы на месте
    answered = dict(st.data["answers"])
    await bot.cb_home(btn("home"), st)
    assert any(t.startswith("Продолжить") for t, _ in buttons()), "нет «Продолжить»"
    await bot.cb_resume(btn("resume"), st)
    assert st.data["answers"] == answered, "ответы потерялись при выходе"
    # Назад: предыдущий ответ показан, «Оставить как было» не теряет данные
    await bot.on_back(btn("nav:back"), st)
    assert "Сейчас указано" in last_bot_text()
    await bot.on_keep(btn("keep"), st)
    assert st.data["answers"] == answered, "«Оставить как было» изменило ответы"
    assert "Сейчас указано" not in last_bot_text(), "подсказка прежнего значения протекла дальше"
    await fill_all(st)
    assert "Проверьте сведения" in last_bot_text()

    # Изменить только сумму: остальные вопросы не задаются заново
    n_before = len(st.data["answers"])
    await bot.cb_edit_section(btn("es:0"), st)
    await bot.cb_edit_field(btn("Сумма:"), st)
    assert "Сейчас указано: 24" in last_bot_text()
    await bot.on_text(Msg("21990"), st)
    assert "Проверьте сведения" in last_bot_text(), "после изменения одного поля не вернулись к сводке"
    assert len(st.data["answers"]) == n_before and "21 990" in last_bot_text()

    # Смена требования на замену убирает ставший ненужным ответ «куда вернуть деньги»
    await bot.cb_edit_section(btn("es:1"), st)
    await bot.cb_edit_field(btn("Требование:"), st)
    await bot.on_choice(btn("[Заменить на такой же]") if False else CB("a:1", "[Заменить на такой же]"), st)
    assert "refund_method" not in st.data["answers"] and "Куда вернуть" not in last_bot_text()
    await bot.cb_edit_section(btn("es:1"), st)
    await bot.cb_edit_field(btn("Требование:"), st)
    await bot.on_choice(CB("a:0", "[Вернуть деньги]"), st)
    assert "Куда вернуть" in last_bot_text() or st.data.get("cur") == "refund_method"
    if st.state is not None:                          # спросили только новый нужный вопрос
        await answer_current(st)
    assert "Проверьте сведения" in last_bot_text()

    await bot.cb_draft(btn("draft"), st)
    assert last_bot_text().startswith("<b>Черновик</b>")
    await bot.on_buy(btn("buy"), st)
    files = [x for x in LOG if x[0] == "file"]
    docs_out = [f for f in files if "Документ подготовлен" in CAPTIONS[id(f[1])]]
    memos = [f for f in files if "Памятка" in CAPTIONS[id(f[1])]]
    assert docs_out and memos, "нужны и документ, и памятка"
    from docx import Document
    legal = Document(io.BytesIO(docs_out[-1][1].args[0]))
    full = "\n".join(p.text for p in legal.paragraphs)
    assert "Желток" not in full and "желток" not in full, "в юридическом документе не должно быть бренда"
    assert legal.core_properties.author == "", "в свойствах файла остался автор python-docx"
    memo_text = "\n".join(p.text for p in Document(io.BytesIO(memos[-1][1].args[0])).paragraphs)
    assert "Документы. По шагам." in memo_text and "t.me/zholtok_bot" in memo_text
    assert set(st.data) == {"src"}, "анкета не стёрта"
    assert "Отметить отправку" in [t for t, _ in buttons()]
    with bot.db() as con:
        assert con.execute("SELECT COUNT(*) FROM reminders WHERE due IS NULL").fetchone()[0] == 1, \
            "напоминание должно ждать подтверждения отправки"
    await bot.cb_sent(btn("sent:"))
    await bot.cb_sent_quick(btn("sd:"))
    assert "Отправка отмечена" in last_bot_text()
    await bot.cb_cases(btn("cases"))
    await bot.cb_case(btn("case:"))
    assert "✓ Отправка подтверждена" in last_bot_text()
    # Имитируем наступление срока: пользователь сообщает, что ответа нет
    await bot.cb_no_answer(btn("nx:"))
    assert "Жалоба в Роспотребнадзор" in last_bot_text()
    write_transcript(os.path.join(HERE, "transcript.md"), t0)
    print("Главный сценарий: главный экран → раздел → выход/продолжить → назад → сводка → "
          "изменить поле → черновик → документ → отправка → дело → следующий шаг: ok")

    # ===== Чужое дело: другой пользователь подделывает кнопки с кодом дела
    with bot.db() as con:
        cid, stage0 = con.execute("SELECT id, stage FROM cases WHERE chat_id=1001 ORDER BY created DESC LIMIT 1").fetchone()
    assert not str(cid).isdigit() and len(cid) >= 10, f"код дела должен быть случайным, а он {cid!r}"

    class Chat2: id = 2002
    class User2: id = 2002
    def cb2(data):
        c = CB(data); c.message.chat = Chat2(); c.message.from_user = User2(); return c
    n_log = len(LOG)
    st2 = State()
    for data in (f"case:{cid}", f"sent:{cid}", f"sd:{cid}:0", f"res:{cid}", f"nx:{cid}"):
        handler = {"case": bot.cb_case, "sent": bot.cb_sent, "sd": bot.cb_sent_quick, "res": bot.cb_resolved,
                   "nx": bot.cb_no_answer}[data.split(":")[0]]
        await handler(cb2(data))
    await bot.cb_delete_case(cb2(f"delc:{cid}"))
    with bot.db() as con:
        row = con.execute("SELECT stage FROM cases WHERE id=?", (cid,)).fetchone()
    assert row and row[0] == stage0, "чужой пользователь изменил или удалил дело"
    leaked = [t for k, t, _ in LOG[n_log:] if k == "bot" and "Претензия" in str(t)]
    assert not leaked, "чужому пользователю показали дело"
    # подделанные индексы не роняют бота
    await st2.set_data({"doc": "vozvrat_brak", "answers": {}, "hist": []})
    await bot.cb_edit_field(CB("ef:999"), st2); await bot.cb_edit_field(CB("ef:abc"), st2)
    await bot.cb_edit_section(CB("es:-1"), st2)
    print("Чужие дела недоступны, коды дел случайные, подделанные кнопки не роняют бота: ok")

    # ===== Защита от двойного нажатия
    await bot.on_buy(CB("buy"), st)
    assert sum(1 for x in LOG if x[0] == "file") == len(files), "документ выдан дважды"

    # ===== Блокировка с возможностью исправить дату
    await st.clear()
    await bot.cb_fill(CB("fill:obmen_25"), st)
    await fill_all(st, {"buy_date": (engine.today() - dt.timedelta(days=20)).strftime("%d.%m.%Y")})
    assert "не поможет" in last_bot_text()
    await bot.cb_review_edit(btn("review:edit"), st)
    await bot.cb_edit_section(btn("es:0"), st)
    await bot.cb_edit_field(btn("Дата покупки:"), st)
    await bot.on_text(Msg((engine.today() - dt.timedelta(days=3)).strftime("%d.%m.%Y")), st)
    assert "Проверьте сведения" in last_bot_text(), "после исправления даты не вышли к сводке"
    print("Блокировка → исправление даты → сводка: ok")

    # ===== Все документы
    ok = 0
    for doc_id in bot.CAT.docs:
        await st.clear()
        await bot.cb_fill(CB(f"fill:{doc_id}"), st)
        await fill_all(st)
        if not any(d == "draft" for _, d in buttons()):
            print(f"  {doc_id}: заблокирован примером")
            continue
        await bot.cb_draft(btn("draft"), st)
        await bot.on_buy(btn("buy"), st)
        assert set(st.data) <= {"src"}, doc_id
        ok += 1
    print(f"Все документы: выдано {ok} из {len(bot.CAT.docs)}")

    # ===== Данные из Mini App (настоящий payload из test_miniapp_ui.py, если он есть)
    import json as _json
    pl_path = os.path.join(HERE, "screens", "sent_payload.json")
    if os.path.exists(pl_path):
        payload = open(pl_path, encoding="utf-8").read()
    else:
        payload = _json.dumps({"v": 1, "id": "t1", "doc": "otkaz_strahovka", "a": {}})
    def app_msg(data):
        m = Msg(); m.web_app_data = _Obj(data=data); return m
    n_files = sum(1 for x in LOG if x[0] == "file")
    await st.clear()
    await bot.on_app_data(app_msg(payload), st)
    if os.path.exists(pl_path):
        assert sum(1 for x in LOG if x[0] == "file") == n_files + 2, "из приложения не выдан документ с памяткой"
        await bot.on_app_data(app_msg(payload), st)
        assert "уже подготовлен" in last_bot_text(), "повторная отправка выдала документ второй раз"
        assert sum(1 for x in LOG if x[0] == "file") == n_files + 2
        print("Mini App → бот: документ + памятка, повтор не дублирует: ok")
    # подделанные данные: чужой вариант ответа
    bad = _json.loads(payload); bad["id"] = "t-bad"; bad["a"]["kind"] = "maybe"
    await bot.on_app_data(app_msg(_json.dumps(bad)), st)
    assert "не собрать" in last_bot_text(), "подделанный ответ не отклонён"
    await bot.on_app_data(app_msg("{not json"), st)
    assert "Не получилось прочитать" in last_bot_text()
    bad2 = dict(bad, id="t-bad2", doc="no_such_doc")
    await bot.on_app_data(app_msg(_json.dumps(bad2)), st)
    assert "Не получилось прочитать" in last_bot_text(), "неизвестный документ принят"
    assert set(bot.MINIAPP_DOCS) == set(bot.CAT.docs), "в Mini App не все документы"
    print("Защита от подделанных и испорченных данных: ok")

    # ===== Тексты без «ты» и без эмодзи
    import ui
    src = open(os.path.join(HERE, "ui.py"), encoding="utf-8").read()
    assert not re.search(r"(?<![А-Яа-яЁё])(ты|тебе|тебя|твой)(?![А-Яа-яЁё])", src)
    assert not re.search("[\U0001F300-\U0001FAFF☀-⛿]", src + open(os.path.join(HERE, "bot.py"), encoding="utf-8").read())
    print("Тон и отсутствие эмодзи: ok")
    await api_checks()
    print("ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ")


async def http(port, method, path, body=None, auth=None, raw=None):
    """Запрос к API как от Caddy: HTTP/1.1, Content-Length, Connection: close."""
    import json as _json
    r, w = await asyncio.open_connection("127.0.0.1", port)
    data = raw if raw is not None else (_json.dumps(body).encode() if body is not None else b"")
    head = f"{method} {path} HTTP/1.1\r\nHost: x\r\nContent-Length: {len(data)}\r\n"
    if auth:
        head += f"Authorization: {auth}\r\n"
    w.write((head + "\r\n").encode() + data)
    await w.drain()
    resp = await r.read()
    w.close()
    status = int(resp.split(b" ", 2)[1])
    return status, _json.loads(resp.split(b"\r\n\r\n", 1)[1] or b"{}")


def init_data(uid, token="test", age=0, tamper=False):
    import hashlib, hmac, json as _json, urllib.parse
    fields = {"user": _json.dumps({"id": uid, "first_name": "Иван"}), "auth_date": str(int(time.time()) - age),
              "query_id": "AAE1"}
    check = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    if tamper:
        fields["user"] = _json.dumps({"id": uid + 1, "first_name": "Иван"})
    return urllib.parse.urlencode(fields)


async def api_checks():
    import api
    import json as _json
    bot.API_PORT = 1
    server = await bot.make_api(FakeBot()).serve(0)
    port = server.sockets[0].getsockname()[1]
    uid = 1001
    ok_auth = "tma " + init_data(uid)
    # здоровье, подписи
    assert (await http(port, "GET", "/api/health"))[0] == 200
    assert (await http(port, "POST", "/api/me", {}))[0] == 401, "без подписи пустили"
    assert (await http(port, "POST", "/api/me", {}, auth="tma " + init_data(uid, tamper=True)))[0] == 401, "подделанный user"
    assert (await http(port, "POST", "/api/me", {}, auth="tma " + init_data(uid, token="other")))[0] == 401, "чужой токен"
    assert (await http(port, "POST", "/api/me", {}, auth="tma " + init_data(uid, age=2 * 86400)))[0] == 401, "старые данные"
    tok = api.make_token(uid, "test")
    assert api.check_token(tok, "test") == uid and api.check_token(tok, "x") is None
    assert api.check_token(api.make_token(uid, "test", now=time.time() - 200 * 86400), "test") is None, "просроченный токен"
    bad_tok = tok.split(".")[0].replace("1001", "1002") + "." + ".".join(tok.split(".")[1:])
    assert (await http(port, "POST", "/api/me", {}, auth="tok " + bad_tok))[0] == 401, "подменили id в токене"
    st, res = await http(port, "POST", "/api/me", {}, auth="tok " + tok)
    assert st == 200 and res["ok"], res
    n_before = len(res["cases"])
    # персональная кнопка приложения содержит токен
    url = bot.app_url(uid)
    assert "t=" in url and api.check_token(url.split("t=")[1], "test") == uid
    # мусор и размер
    assert (await http(port, "POST", "/api/me", raw=b"{not json", auth=ok_auth))[0] == 400
    assert (await http(port, "POST", "/api/me", raw=b"x" * 70000, auth=ok_auth))[0] == 413
    assert (await http(port, "POST", "/api/nope", {}, auth=ok_auth))[0] == 404
    # отправка анкеты через API: документ + памятка приходят в чат, дело появляется
    payload = {"v": 1, "id": "api-1", "doc": "zalog_arenda", "a": {}}
    doc = bot.CAT.docs["zalog_arenda"]
    ans = {}
    while True:
        q = engine.next_question(doc, ans, bot.CFG)
        if q is None:
            break
        ans[q["key"]] = example_value_app(q)
    payload["a"] = ans
    files = sum(1 for x in LOG if x[0] == "file")
    st, res = await http(port, "POST", "/api/submit", {"p": payload}, auth=ok_auth)
    assert st == 200 and res["ok"], res
    assert sum(1 for x in LOG if x[0] == "file") == files + 2, "через API не пришли документ и памятка"
    assert res["cases"][0]["doc"] == "zalog_arenda" and len(res["cases"]) == min(n_before + 1, 20), res["cases"][:2]
    st, res = await http(port, "POST", "/api/submit", {"p": payload}, auth=ok_auth)
    assert res["status"] == "duplicate", res
    bad = dict(payload, id="api-2", a=dict(ans, excuse="maybe"))
    st, res = await http(port, "POST", "/api/submit", {"p": bad}, auth=ok_auth)
    assert res["status"] == "invalid" and "<" not in res["error"], res
    # человек не запускал бота — документ не дошёл, отправку можно повторить
    st, res = await http(port, "POST", "/api/submit", {"p": dict(payload, id="api-3")}, auth="tma " + init_data(666))
    assert res["status"] == "undelivered", res
    # действия с делом
    cid = (await http(port, "POST", "/api/me", {}, auth=ok_auth))[1]["cases"][0]["id"]
    st, res = await http(port, "POST", "/api/case", {"id": cid, "action": "sent", "date": "2099-01-01"}, auth=ok_auth)
    assert st == 400, "дата из будущего принята"
    today = engine.today().isoformat()
    st, res = await http(port, "POST", "/api/case", {"id": cid, "action": "sent", "date": today}, auth=ok_auth)
    c = next(x for x in res["cases"] if x["id"] == cid)
    assert c["stage"] == "sent" and c["sent"] == today and c["reminder"], c
    other = "tma " + init_data(2002)
    assert (await http(port, "POST", "/api/case", {"id": cid, "action": "delete"}, auth=other))[0] == 404, "чужое дело"
    st, res = await http(port, "POST", "/api/case", {"id": cid, "action": "next"}, auth=ok_auth)
    c = next(x for x in res["cases"] if x["id"] == cid)
    assert c["stage"] == "next" and c["reminder"] is None, c
    st, res = await http(port, "POST", "/api/case", {"id": cid, "action": "delete"}, auth=ok_auth)
    assert all(x["id"] != cid for x in res["cases"])
    # частота отправок
    codes = [(await http(port, "POST", "/api/submit", {"p": {}}, auth="tma " + init_data(3003)))[0] for _ in range(8)]
    assert 429 in codes, codes
    server.close()
    bot.API_PORT = 0
    print("API: подписи, токен кнопки, приём анкеты, дубли, недоставка, дела, чужие дела, лимиты: ok")
    print("ВСЕ ПРОВЕРКИ API ПРОЙДЕНЫ")


def example_value_app(q):
    import test_all
    v = test_all.example_value(q, {})
    return v.isoformat() if isinstance(v, dt.date) else v


asyncio.run(main())
