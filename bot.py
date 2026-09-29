"""Желток — Telegram-бот, который по шагам готовит документы для бытовых ситуаций.

Без ИИ: каждый документ стоит 0 ₽, платите только за сервер.
Ответы анкеты живут в памяти до выдачи файла и сразу стираются.
На диске: отметка о согласии, дела (только тип документа и этапы), напоминания, статистика без ПД.

Запуск:  python bot.py   (настройки — в .env рядом)
"""
from __future__ import annotations

import asyncio
import datetime as dt
import html
import json
import logging
import os
import secrets
import sqlite3
import time

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (BufferedInputFile, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup,
                           KeyboardButton, Message, ReplyKeyboardMarkup, WebAppInfo)

import engine
import ui

HERE = os.path.dirname(os.path.abspath(__file__))


# ================================================================= config
def load_env(path: str) -> None:
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


load_env(os.path.join(HERE, ".env"))
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
MINIAPP_URL = os.environ.get("MINIAPP_URL", "")                # https://имя.github.io/zholtok/ — адрес Mini App
def _miniapp_docs() -> list[str]:
    """Какие документы есть в Mini App — берём из того же miniapp/catalog.json, что публикуется на сайт.
    Так список в боте и в приложении не расходится, и .env править не нужно."""
    try:
        with open(os.path.join(HERE, "miniapp", "catalog.json"), encoding="utf-8") as f:
            return [d["id"] for d in json.load(f)["docs"]]
    except (OSError, ValueError, KeyError):
        return []


MINIAPP_DOCS = _miniapp_docs()
BOT_LINK = os.environ.get("BOT_LINK", "")                      # t.me/имя_бота — для памятки
try:
    KEY_RATE = float(os.environ.get("KEY_RATE", "0").replace(",", ".").replace("%", "").strip() or 0)
except ValueError:
    KEY_RATE = 0.0
POLICY_URL = os.environ.get("POLICY_URL", "")
SUPPORT = os.environ.get("SUPPORT", "")
ADMIN_IDS = {int(x) for x in os.environ.get("ADMIN_IDS", "").replace(" ", "").split(",") if x}
DB_PATH = os.environ.get("DB_PATH", os.path.join(HERE, "zholtok.sqlite3"))

CAT = engine.Catalog(os.path.join(HERE, "catalog.yaml"))
CFG = {"key_rate": KEY_RATE}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("zholtok")


# ================================================================= storage (без ПД из анкет)
def db() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH)
    con.execute("CREATE TABLE IF NOT EXISTS consent (chat_id INTEGER PRIMARY KEY, ts INTEGER, policy TEXT)")
    con.execute("CREATE TABLE IF NOT EXISTS cases (id TEXT PRIMARY KEY, chat_id INTEGER, doc TEXT, stage TEXT,"
                " created INTEGER, sent_at INTEGER, offer TEXT)")
    con.execute("CREATE TABLE IF NOT EXISTS reminders (id INTEGER PRIMARY KEY, case_id TEXT, chat_id INTEGER,"
                " days INTEGER, due INTEGER, text TEXT)")
    con.execute("CREATE TABLE IF NOT EXISTS sales (id INTEGER PRIMARY KEY, ts INTEGER, doc TEXT, price INTEGER, mode TEXT, src TEXT)")
    con.execute("CREATE TABLE IF NOT EXISTS submissions (id TEXT PRIMARY KEY, chat_id INTEGER, ts INTEGER)")
    con.execute("CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, ts INTEGER, kind TEXT, doc TEXT, src TEXT)")
    return con


def has_consent(chat_id: int) -> bool:
    with db() as con:
        return con.execute("SELECT 1 FROM consent WHERE chat_id=?", (chat_id,)).fetchone() is not None


def event(kind: str, doc: str = "", src: str = "") -> None:
    with db() as con:
        con.execute("INSERT INTO events (ts, kind, doc, src) VALUES (?,?,?,?)", (int(time.time()), kind, doc, src))


def open_cases(chat_id: int) -> list[tuple]:
    with db() as con:
        return con.execute("SELECT id, doc, stage, created, sent_at, offer FROM cases WHERE chat_id=? "
                           "ORDER BY id DESC LIMIT 10", (chat_id,)).fetchall()


def get_case(chat_id: int, cid: str) -> tuple | None:
    with db() as con:
        return con.execute("SELECT id, doc, stage, created, sent_at, offer FROM cases WHERE chat_id=? AND id=?",
                           (chat_id, cid)).fetchone()


def next_reminder(cid: str) -> int | None:
    with db() as con:
        r = con.execute("SELECT MIN(due) FROM reminders WHERE case_id=? AND due IS NOT NULL", (cid,)).fetchone()
    return r[0] if r else None


# ================================================================= state helpers
class Form(StatesGroup):
    filling = State()
    sent_date = State()


def pack(answers: dict) -> dict:
    return {k: ({"__d": v.isoformat()} if isinstance(v, dt.date) else v) for k, v in answers.items()}


def unpack(answers: dict) -> dict:
    return {k: (dt.date.fromisoformat(v["__d"]) if isinstance(v, dict) and "__d" in v else v)
            for k, v in answers.items()}


def esc(s) -> str:
    return html.escape(str(s))


def escaped_answers(answers: dict) -> dict:
    return {k: (html.escape(v) if isinstance(v, str) else v) for k, v in answers.items()}


def kb(rows: list[list[tuple[str, str]]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=t, callback_data=d) for t, d in row]
                                                 for row in rows if row])


def price_text(doc: dict) -> str:
    return "бесплатно"          # оплата отключена: собираем статистику спроса


def app_keyboard() -> ReplyKeyboardMarkup | None:
    """Кнопка Mini App под полем ввода. Только reply-кнопка позволяет приложению передать данные боту."""
    if not MINIAPP_URL:
        return None
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=ui.BTN_OPEN_APP, web_app=WebAppInfo(url=MINIAPP_URL))]],
                               resize_keyboard=True, is_persistent=True)


def has_draft(data: dict) -> bool:
    return bool(data.get("doc")) and "answers" in data


router = Router()


# ================================================================= главный экран
async def show_home(target: Message, state: FSMContext) -> None:
    await state.set_state(None)
    data = await state.get_data()
    rows = []
    if has_draft(data):
        rows.append([(ui.BTN_CONTINUE.format(name=CAT.docs[data["doc"]]["button"]), "resume")])
        rows.append([(ui.BTN_NEW, "start")])
    else:
        rows.append([(ui.BTN_START, "start")])
    active = [c for c in open_cases(target.chat.id) if c[2] in ("prepared", "sent", "next")]
    if active:
        rows.append([(ui.BTN_CASES.format(n=len(active)), "cases")])
    await target.answer(ui.home(has_draft(data)), reply_markup=kb(rows))


@router.message(CommandStart())
async def cmd_start(m: Message, command: CommandObject, state: FSMContext) -> None:
    args = (command.args or "").strip()
    doc_id, _, src = args.partition("__")          # t.me/bot?start=vozvrat_brak__vk1
    if doc_id not in CAT.docs:
        src, doc_id = args, ""
    await state.update_data(src=src)
    event("start", doc_id, src)
    if MINIAPP_URL:
        await m.answer(ui.APP_HINT, reply_markup=app_keyboard())
    if doc_id:
        await send_doc_card(m, doc_id)
    else:
        await show_home(m, state)


@router.message(Command("menu"))
async def cmd_menu(m: Message, state: FSMContext) -> None:
    await show_home(m, state)


@router.callback_query(F.data == "home")
async def cb_home(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    await show_home(cb.message, state)


@router.callback_query(F.data == "start")
async def cb_start(cb: CallbackQuery) -> None:
    rows = [[(c["title"], f"cat:{c['id']}")] for c in CAT.categories] + [[(ui.BTN_BACK, "home")]]
    await cb.message.answer(ui.SITUATIONS, reply_markup=kb(rows))
    await cb.answer()


@router.callback_query(F.data.startswith("cat:"))
async def cb_cat(cb: CallbackQuery) -> None:
    cat_id = cb.data[4:]
    title = next((c["title"] for c in CAT.categories if c["id"] == cat_id), "")
    rows = [[(f"{d['button']} · {price_text(d)}", f"doc:{d['id']}")] for d in CAT.in_category(cat_id)]
    rows.append([(ui.BTN_BACK, "start")])
    await cb.message.answer(ui.category(title), reply_markup=kb(rows))
    await cb.answer()


async def send_doc_card(target: Message, doc_id: str) -> None:
    d = CAT.docs[doc_id]
    event("card", doc_id)
    await target.answer(ui.doc_card(d, price_text(d), in_app=bool(MINIAPP_URL) and doc_id in MINIAPP_DOCS),
                        reply_markup=kb([[(ui.BTN_FILL, f"fill:{doc_id}")], [(ui.BTN_BACK, f"cat:{d['category']}")]]))


@router.callback_query(F.data.startswith("doc:"))
async def cb_doc(cb: CallbackQuery) -> None:
    if cb.data[4:] in CAT.docs:
        await send_doc_card(cb.message, cb.data[4:])
    await cb.answer()


# ================================================================= согласие и старт анкеты
@router.callback_query(F.data.startswith("fill:"))
async def cb_fill(cb: CallbackQuery, state: FSMContext) -> None:
    doc_id = cb.data[5:]
    await cb.answer()
    if not has_consent(cb.message.chat.id):
        await cb.message.answer(ui.consent(POLICY_URL), disable_web_page_preview=True,
                                reply_markup=kb([[(ui.BTN_CONSENT, f"consent:{doc_id}")], [(ui.BTN_BACK, f"doc:{doc_id}")]]))
        return
    await begin(cb.message, state, doc_id)


@router.callback_query(F.data.startswith("consent:"))
async def cb_consent(cb: CallbackQuery, state: FSMContext) -> None:
    with db() as con:
        con.execute("INSERT OR REPLACE INTO consent (chat_id, ts, policy) VALUES (?,?,?)",
                    (cb.message.chat.id, int(time.time()), POLICY_URL or "v1"))
    await cb.answer()
    await begin(cb.message, state, cb.data[8:])


async def begin(target: Message, state: FSMContext, doc_id: str) -> None:
    data = await state.get_data()
    await state.set_data({"doc": doc_id, "answers": {}, "hist": [], "msel": [], "mode": "fill",
                          "src": data.get("src", "")})
    event("fill", doc_id, data.get("src", ""))
    await ask_next(target, state)


@router.callback_query(F.data == "resume")
async def cb_resume(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    data = await state.get_data()
    if not has_draft(data):
        await show_home(cb.message, state)
        return
    await ask_next(cb.message, state)


# ================================================================= вопросы
async def ask_next(target: Message, state: FSMContext) -> None:
    data = await state.get_data()
    doc = CAT.docs[data["doc"]]
    answers = unpack(data["answers"])
    q = engine.next_question(doc, answers, CFG)
    if q is None:
        await show_review(target, state)
        return
    await state.set_state(Form.filling)
    await state.update_data(cur=q["key"], msel=[])
    n, total, title = engine.section_info(doc, q["key"])
    editing = data.get("mode") == "edit"
    head = ui.question(q, n, total, title, editing, data.get("prev_label"))
    nav = [(ui.BTN_TO_REVIEW, "review")] if editing else ([(ui.BTN_BACK, "nav:back")] if data["hist"] else [])
    nav = nav + [(ui.BTN_EXIT, "home")]
    keep = [[(ui.BTN_KEEP, "keep")]] if data.get("prev") is not None else []
    typ = q["type"]
    if typ == "choice":
        rows = [[(o["label"][:60], f"a:{i}")] for i, o in enumerate(q["options"])]
        await target.answer(head, reply_markup=kb(rows + keep + [nav]))
    elif typ == "yesno":
        await target.answer(head, reply_markup=kb([[(ui.BTN_YES, "a:y"), (ui.BTN_NO, "a:n")]] + keep + [nav]))
    elif typ == "multi":
        await target.answer(head, reply_markup=multi_kb(q, [], keep + [nav]))
    else:
        await target.answer(head, reply_markup=kb(keep + [nav]))


def multi_kb(q: dict, selected: list[int], tail: list) -> InlineKeyboardMarkup:
    rows = [[(("✓ " if i in selected else "") + o["label"][:58], f"m:{i}")] for i, o in enumerate(q["options"])]
    return kb(rows + [[(ui.BTN_DONE, "m:done")]] + tail)


def current_q(data: dict) -> dict | None:
    if not data.get("doc") or not data.get("cur"):
        return None
    return next((q for q in CAT.docs[data["doc"]]["questions"] if q["key"] == data["cur"]), None)


async def store(target: Message, state: FSMContext, value) -> None:
    data = await state.get_data()
    doc = CAT.docs[data["doc"]]
    answers = unpack(data["answers"])
    answers[data["cur"]] = value
    answers = engine.prune(doc, answers, CFG)
    hist = [k for k in data["hist"] if k in answers]
    if data["cur"] not in hist:
        hist.append(data["cur"])
    await state.update_data(answers=pack(answers), hist=hist, prev=None, prev_label=None)
    await ask_next(target, state)


@router.message(Form.filling, F.text)
async def on_text(m: Message, state: FSMContext) -> None:
    q = current_q(await state.get_data())
    if q is None:
        await show_home(m, state)
        return
    value, err = engine.parse_answer(q, m.text)
    if err:
        await m.answer(ui.input_error(err))
        return
    await store(m, state, value)


@router.callback_query(Form.filling, F.data.startswith("a:"))
async def on_choice(cb: CallbackQuery, state: FSMContext) -> None:
    q = current_q(await state.get_data())
    code = cb.data[2:]
    if q and q["type"] == "yesno" and code in ("y", "n"):
        value = code == "y"
    elif q and q["type"] == "choice" and code.isdigit() and int(code) < len(q["options"]):
        value = q["options"][int(code)]["v"]
    else:
        await cb.answer(ui.STALE_BUTTON)
        return
    await cb.answer()
    await cb.message.edit_reply_markup(reply_markup=None)
    await store(cb.message, state, value)


@router.callback_query(Form.filling, F.data.startswith("m:"))
async def on_multi(cb: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    q = current_q(data)
    if not q or q["type"] != "multi":
        await cb.answer(ui.STALE_BUTTON)
        return
    sel = list(data.get("msel", []))
    if cb.data == "m:done":
        if not sel:
            await cb.answer(ui.MULTI_EMPTY, show_alert=True)
            return
        await cb.answer()
        await cb.message.edit_reply_markup(reply_markup=None)
        await store(cb.message, state, [q["options"][i]["v"] for i in sorted(sel)])
        return
    code = cb.data[2:]
    if not code.isdigit() or int(code) >= len(q["options"]):
        await cb.answer(ui.STALE_BUTTON)
        return
    i = int(code)
    sel.remove(i) if i in sel else sel.append(i)
    await state.update_data(msel=sel)
    tail = [[(ui.BTN_BACK, "nav:back")]] if data.get("hist") and data.get("mode") != "edit" else []
    await cb.message.edit_reply_markup(reply_markup=multi_kb(q, sel, tail + [[(ui.BTN_EXIT, "home")]]))
    await cb.answer()


@router.callback_query(F.data == "nav:back")
async def on_back(cb: CallbackQuery, state: FSMContext) -> None:
    """Шаг назад: предыдущий ответ открывается для исправления, остальные сохраняются."""
    data = await state.get_data()
    await cb.answer()
    if not has_draft(data) or not data.get("hist"):
        return
    last = data["hist"][-1]
    answers = dict(data["answers"])
    prev = answers.pop(last, None)
    await state.update_data(answers=answers, hist=data["hist"][:-1], prev=prev,
                            prev_label=_fmt_prev(data["doc"], last, prev))
    await ask_next(cb.message, state)


def _fmt_prev(doc_id: str, key: str, packed_value) -> str:
    q = next(x for x in CAT.docs[doc_id]["questions"] if x["key"] == key)
    return engine.fmt_value(q, unpack({key: packed_value})[key])


@router.callback_query(F.data == "keep")
async def on_keep(cb: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    await cb.answer()
    if not has_draft(data) or data.get("prev") is None:
        return
    await store(cb.message, state, unpack({"x": data["prev"]})["x"])


# ================================================================= проверка (сводка)
async def show_review(target: Message, state: FSMContext) -> None:
    await state.set_state(None)
    data = await state.get_data()
    doc = CAT.docs[data["doc"]]
    answers = unpack(data["answers"])
    await state.update_data(mode="review", prev_label=None)
    warns = engine.check_warnings(doc, answers, CFG)
    block = next((w for w in warns if w["block"]), None)
    if block:
        event("blocked", doc["id"], data.get("src", ""))
        await target.answer(ui.blocked(block["text"]),
                            reply_markup=kb([[(ui.BTN_EDIT_ANSWERS, "review:edit")],
                                             [(ui.BTN_OTHER_DOC, "start")], [(ui.BTN_HOME, "home")]]))
        return
    sections = engine.summary(doc, answers, CFG)
    rows = [[(ui.BTN_EDIT_SECTION.format(title=t), f"es:{i}")] for i, (t, _) in enumerate(sections)]
    rows.append([(ui.BTN_TO_DRAFT, "draft")])
    await target.answer(ui.review(doc, sections, [w["text"] for w in warns]), reply_markup=kb(rows))


@router.callback_query(F.data == "review")
async def cb_review(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    data = await state.get_data()
    if not has_draft(data):
        await show_home(cb.message, state)
        return
    if data.get("prev") is not None and data.get("cur") not in data["answers"]:
        answers = dict(data["answers"])
        answers[data["cur"]] = data["prev"]            # вышли из изменения — возвращаем прежний ответ
        await state.update_data(answers=answers, prev=None)
    await show_review(cb.message, state)


@router.callback_query(F.data == "review:edit")
async def cb_review_edit(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    data = await state.get_data()
    if not has_draft(data):
        await show_home(cb.message, state)
        return
    doc = CAT.docs[data["doc"]]
    sections = engine.summary(doc, unpack(data["answers"]), CFG)
    rows = [[(ui.BTN_EDIT_SECTION.format(title=t), f"es:{i}")] for i, (t, _) in enumerate(sections)]
    await cb.message.answer(ui.review(doc, sections, []), reply_markup=kb(rows + [[(ui.BTN_HOME, "home")]]))


@router.callback_query(F.data.startswith("es:"))
async def cb_edit_section(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    data = await state.get_data()
    if not has_draft(data):
        await show_home(cb.message, state)
        return
    doc = CAT.docs[data["doc"]]
    answers = unpack(data["answers"])
    sections = engine.summary(doc, answers, CFG)
    code = cb.data[3:]
    if not code.isdigit() or int(code) >= len(sections):
        return
    i = int(code)
    title = sections[i][0]
    rows = []
    for qi, q in enumerate(doc["questions"]):
        if q["section"] == title and q["key"] in answers:
            value = engine.fmt_value(q, answers[q["key"]])
            value = value if len(value) <= 28 else value[:27] + "…"
            rows.append([(ui.BTN_EDIT_FIELD.format(label=q["label"], value=value), f"ef:{qi}")])
    rows.append([(ui.BTN_TO_REVIEW, "review")])
    await cb.message.answer(ui.edit_section(title), reply_markup=kb(rows))


@router.callback_query(F.data.startswith("ef:"))
async def cb_edit_field(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    data = await state.get_data()
    if not has_draft(data):
        await show_home(cb.message, state)
        return
    doc = CAT.docs[data["doc"]]
    code = cb.data[3:]
    if not code.isdigit() or int(code) >= len(doc["questions"]):
        return
    q = doc["questions"][int(code)]
    if q["key"] not in data["answers"]:
        return
    answers = dict(data["answers"])
    prev = answers.pop(q["key"], None)
    await state.update_data(answers=answers, mode="edit", prev=prev,
                            prev_label=_fmt_prev(data["doc"], q["key"], prev))
    await ask_next(cb.message, state)


# ================================================================= черновик и оплата
@router.callback_query(F.data == "draft")
async def cb_draft(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    data = await state.get_data()
    if not has_draft(data):
        await cb.message.answer(ui.ALREADY_ISSUED, reply_markup=kb([[(ui.BTN_HOME, "home")]]))
        return
    doc = CAT.docs[data["doc"]]
    text = engine.render_text(doc, unpack(data["answers"]), CFG)
    shown, rest = engine.preview_text(text)
    event("preview", doc["id"], data.get("src", ""))
    await cb.message.answer(ui.draft(doc, esc(shown[:2600]), rest),
                            reply_markup=kb([[(ui.BTN_DOWNLOAD, "buy")], [(ui.BTN_TO_REVIEW, "review")]]))


@router.callback_query(F.data == "buy")
async def on_buy(cb: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    if not has_draft(data):
        await cb.answer(ui.ALREADY_ISSUED, show_alert=True)
        return
    doc = CAT.docs[data["doc"]]
    answers = unpack(data["answers"])
    if engine.next_question(doc, answers, CFG) or any(w["block"] for w in engine.check_warnings(doc, answers, CFG)):
        await cb.answer(ui.NOT_READY, show_alert=True)
        return
    await cb.answer()
    await state.set_data({"src": data.get("src", "")})                    # анкета стёрта до выдачи: второй клик ничего не выдаст
    await deliver(cb.message, doc, answers, src=data.get("src", ""))


async def deliver(target: Message, doc: dict, answers: dict, src: str = "") -> None:
    """Выдача: документ (строгий, без бренда) + фирменная памятка + следующий шаг. Ответы не сохраняются."""
    text = engine.render_text(doc, answers, CFG)
    await target.answer_document(BufferedInputFile(engine.build_docx(text, doc["title"]), filename=doc["filename"]),
                                 caption=ui.prepared_caption(doc))
    safe = escaped_answers(answers)
    after = engine.render_snippet(doc["after"], doc, safe, CFG) if doc.get("after") else ""
    memo = engine.build_memo(doc["title"], after or ui.MEMO_FALLBACK, os.path.join(HERE, "brand", "wordmark.png"), BOT_LINK)
    await target.answer_document(BufferedInputFile(memo, filename=ui.MEMO_FILENAME), caption=ui.MEMO_CAPTION)
    now = int(time.time())
    track = doc.get("track", True)
    followups = doc.get("followups") or []
    with db() as con:
        cid = None
        if track:
            cid = secrets.token_urlsafe(9)          # случайный код дела вместо порядкового номера
            con.execute("INSERT INTO cases (id, chat_id, doc, stage, created, sent_at, offer) VALUES (?,?,?,?,?,?,?)",
                        (cid, target.chat.id, doc["id"], "prepared", now, None,
                         next((f.get("offer") for f in followups if f.get("offer")), "")))
            for fu in followups:           # напоминания ждут подтверждения отправки (due пустой)
                con.execute("INSERT INTO reminders (case_id, chat_id, days, due, text) VALUES (?,?,?,?,?)",
                            (cid, target.chat.id, fu["days"], None, engine.render_snippet(fu["text"], doc, safe, CFG)))
        con.execute("INSERT INTO sales (ts, doc, price, mode, src) VALUES (?,?,?,?,?)", (now, doc["id"], 0, "free", src))
    event("issued", doc["id"], src)
    rows = [[(ui.BTN_MARK_SENT, f"sent:{cid}")]] if cid else []
    rows.append([(ui.BTN_HOME, "home")])
    await target.answer(ui.after_delivery(after, tracked=bool(cid)), reply_markup=kb(rows),
                        disable_web_page_preview=True)


# ================================================================= данные из Mini App
def answers_from_app(doc: dict, raw: dict) -> tuple[dict | None, str | None]:
    """Перепроверяем каждый ответ на сервере: приложению не доверяем."""
    answers: dict = {}
    for q in doc["questions"]:
        if q["key"] not in raw:
            continue
        v, t = raw[q["key"]], q["type"]
        if t == "choice":
            if v not in [o["v"] for o in q["options"]]:
                return None, q["label"]
        elif t == "yesno":
            if not isinstance(v, bool):
                return None, q["label"]
        elif t == "multi":
            opts = [o["v"] for o in q["options"]]
            if not isinstance(v, list) or not v or any(x not in opts for x in v):
                return None, q["label"]
        elif t == "date":
            try:
                v = dt.date.fromisoformat(str(v)).strftime("%d.%m.%Y")
            except ValueError:
                return None, q["label"]
            v, err = engine.parse_answer(q, v)
            if err:
                return None, q["label"]
        else:
            if q.get("optional") and v == "":
                answers[q["key"]] = ""
                continue
            v, err = engine.parse_answer(q, str(v).replace(".", ",") if t == "money" else str(v))
            if err:
                return None, q["label"]
        answers[q["key"]] = v
    return engine.prune(doc, answers, CFG), None


@router.message(F.web_app_data)
async def on_app_data(m: Message, state: FSMContext) -> None:
    try:
        payload = json.loads(m.web_app_data.data)
        sid, doc_id, raw = str(payload["id"])[:40], payload["doc"], payload["a"]
        assert payload.get("v") == 1 and isinstance(raw, dict)
    except Exception:  # noqa: BLE001
        await m.answer(ui.APP_BAD_DATA)
        return
    if doc_id not in CAT.docs or doc_id not in MINIAPP_DOCS:
        await m.answer(ui.APP_BAD_DATA)
        return
    with db() as con:
        if con.execute("SELECT 1 FROM submissions WHERE id=? AND chat_id=?", (sid, m.chat.id)).fetchone():
            await m.answer(ui.APP_DUPLICATE)             # повторная отправка — документ уже выдан
            return
        con.execute("INSERT INTO submissions (id, chat_id, ts) VALUES (?,?,?)", (sid, m.chat.id, int(time.time())))
        con.execute("INSERT OR REPLACE INTO consent (chat_id, ts, policy) VALUES (?,?,?)",
                    (m.chat.id, int(time.time()), "miniapp:" + (POLICY_URL or "v1")))
    doc = CAT.docs[doc_id]
    answers, bad = answers_from_app(doc, raw)
    if answers is None or engine.next_question(doc, answers, CFG):
        with db() as con:
            con.execute("DELETE FROM submissions WHERE id=?", (sid,))   # разрешаем исправить и отправить снова
        await m.answer(ui.app_invalid(bad), reply_markup=app_keyboard())
        return
    block = next((w for w in engine.check_warnings(doc, answers, CFG) if w["block"]), None)
    if block:
        await m.answer(ui.blocked(block["text"]))
        return
    data = await state.get_data()
    event("fill", doc_id, "miniapp")
    await deliver(m, doc, answers, src=data.get("src") or "miniapp")


# ================================================================= дела
def case_view(c: tuple) -> tuple[str, InlineKeyboardMarkup]:
    cid, doc_id, stage, created, sent_at, offer = c
    doc = CAT.docs.get(doc_id, {"title": doc_id, "button": doc_id})
    rem = next_reminder(cid)
    text = ui.case_card(doc["title"], stage, created, sent_at, rem)
    rows = []
    if stage == "prepared":
        rows.append([(ui.BTN_MARK_SENT, f"sent:{cid}")])
    elif stage == "sent":
        rows.append([(ui.BTN_RESOLVED, f"res:{cid}")])
        rows.append([(ui.BTN_NO_ANSWER, f"nx:{cid}")])
    elif stage == "next" and offer in CAT.docs:
        rows.append([(ui.BTN_PREPARE.format(name=CAT.docs[offer]["button"]), f"doc:{offer}")])
    rows.append([(ui.BTN_DELETE_CASE, f"delc:{cid}")])
    rows.append([(ui.BTN_ALL_CASES, "cases")])
    return text, kb(rows)


@router.callback_query(F.data == "cases")
async def cb_cases(cb: CallbackQuery) -> None:
    await cb.answer()
    cases = open_cases(cb.message.chat.id)
    if not cases:
        await cb.message.answer(ui.NO_CASES, reply_markup=kb([[(ui.BTN_HOME, "home")]]))
        return
    rows = [[(f"{CAT.docs[c[1]]['button']} · {ui.STAGE_SHORT[c[2]]}", f"case:{c[0]}")]
            for c in cases if c[1] in CAT.docs]
    await cb.message.answer(ui.CASES_TITLE, reply_markup=kb(rows + [[(ui.BTN_HOME, "home")]]))


@router.callback_query(F.data.startswith("case:"))
async def cb_case(cb: CallbackQuery) -> None:
    await cb.answer()
    c = get_case(cb.message.chat.id, cb.data[5:])
    if c:
        text, markup = case_view(c)
        await cb.message.answer(text, reply_markup=markup)


@router.callback_query(F.data.startswith("sent:"))
async def cb_sent(cb: CallbackQuery) -> None:
    await cb.answer()
    cid = cb.data[5:]
    if not get_case(cb.message.chat.id, cid):
        return
    await cb.message.answer(ui.ASK_SENT_DATE, reply_markup=kb([[(ui.BTN_TODAY, f"sd:{cid}:0"), (ui.BTN_YESTERDAY, f"sd:{cid}:1")],
                                                               [(ui.BTN_OTHER_DATE, f"sdx:{cid}")]]))


@router.callback_query(F.data.startswith("sd:"))
async def cb_sent_quick(cb: CallbackQuery) -> None:
    await cb.answer()
    _, cid, ago = cb.data.split(":")
    if ago not in ("0", "1"):
        return
    await confirm_sent(cb.message, cid, engine.today() - dt.timedelta(days=int(ago)))


@router.callback_query(F.data.startswith("sdx:"))
async def cb_sent_other(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    await state.set_state(Form.sent_date)
    await state.update_data(sent_case=cb.data[4:])
    await cb.message.answer(ui.ASK_SENT_DATE_TEXT)


@router.message(Form.sent_date, F.text)
async def on_sent_date(m: Message, state: FSMContext) -> None:
    d, err = engine.parse_answer({"type": "date", "past": True}, m.text)
    if err:
        await m.answer(ui.input_error(err))
        return
    data = await state.get_data()
    await state.set_state(None)
    await confirm_sent(m, data.get("sent_case", ""), d)


async def confirm_sent(target: Message, cid: str, d: dt.date) -> None:
    c = get_case(target.chat.id, cid)
    if not c:
        return
    base = int(dt.datetime.combine(d, dt.time(10, 0)).timestamp())
    now = int(time.time())
    with db() as con:
        con.execute("UPDATE cases SET stage='sent', sent_at=? WHERE id=? AND chat_id=?", (base, cid, target.chat.id))
        for rid, days in con.execute("SELECT id, days FROM reminders WHERE case_id=?", (cid,)).fetchall():
            con.execute("UPDATE reminders SET due=? WHERE id=?", (max(now + 60, base + days * 86400), rid))
    event("sent", c[1])
    rem = next_reminder(cid)
    await target.answer(ui.sent_confirmed(d, rem), reply_markup=kb([[(ui.BTN_ALL_CASES, "cases")], [(ui.BTN_HOME, "home")]]))


@router.callback_query(F.data.startswith("res:"))
async def cb_resolved(cb: CallbackQuery) -> None:
    await cb.answer()
    cid = cb.data[4:]
    if not get_case(cb.message.chat.id, cid):
        return
    with db() as con:
        con.execute("UPDATE cases SET stage='resolved' WHERE id=? AND chat_id=?", (cid, cb.message.chat.id))
        con.execute("DELETE FROM reminders WHERE case_id=?", (cid,))
    await cb.message.answer(ui.RESOLVED, reply_markup=kb([[(ui.BTN_HOME, "home")]]))


@router.callback_query(F.data.startswith("nx:"))
async def cb_no_answer(cb: CallbackQuery) -> None:
    await cb.answer()
    cid = cb.data[3:]
    c = get_case(cb.message.chat.id, cid)
    if not c:
        return
    with db() as con:
        con.execute("UPDATE cases SET stage='next' WHERE id=? AND chat_id=?", (cid, cb.message.chat.id))
        con.execute("DELETE FROM reminders WHERE case_id=?", (cid,))
    offer = c[5]
    if offer in CAT.docs:
        await cb.message.answer(ui.next_step(CAT.docs[offer]["title"]),
                                reply_markup=kb([[(ui.BTN_PREPARE.format(name=CAT.docs[offer]["button"]), f"doc:{offer}")],
                                                 [(ui.BTN_HOME, "home")]]))
    else:
        await cb.message.answer(ui.NEXT_STEP_GENERIC, reply_markup=kb([[(ui.BTN_OTHER_DOC, "start")], [(ui.BTN_HOME, "home")]]))


@router.callback_query(F.data.startswith("delc:"))
async def cb_delete_case(cb: CallbackQuery) -> None:
    await cb.answer()
    cid = cb.data[5:]
    with db() as con:
        con.execute("DELETE FROM reminders WHERE case_id=? AND chat_id=?", (cid, cb.message.chat.id))
        con.execute("DELETE FROM cases WHERE id=? AND chat_id=?", (cid, cb.message.chat.id))
    await cb.message.answer(ui.CASE_DELETED, reply_markup=kb([[(ui.BTN_ALL_CASES, "cases")], [(ui.BTN_HOME, "home")]]))


# ================================================================= служебные команды
@router.message(Command("help"))
async def cmd_help(m: Message) -> None:
    await m.answer(ui.help_text(SUPPORT))


@router.message(Command("privacy"))
async def cmd_privacy(m: Message) -> None:
    await m.answer(ui.privacy(POLICY_URL), disable_web_page_preview=True)


@router.message(Command("delete"))
async def cmd_delete(m: Message, state: FSMContext) -> None:
    await state.clear()
    with db() as con:
        for t in ("reminders", "cases", "consent"):
            con.execute(f"DELETE FROM {t} WHERE chat_id=?", (m.chat.id,))
    await m.answer(ui.DELETED)


@router.message(Command("stats"))
async def cmd_stats(m: Message) -> None:
    if m.from_user.id not in ADMIN_IDS:
        return
    week = int(time.time()) - 7 * 86400
    with db() as con:
        rows = con.execute("SELECT doc, COUNT(*), SUM(price) FROM sales GROUP BY doc ORDER BY 2 DESC").fetchall()
        funnel = con.execute("SELECT kind, COUNT(*) FROM events WHERE ts > ? GROUP BY kind", (week,)).fetchall()
        srcs = con.execute("SELECT src, COUNT(*), SUM(price) FROM sales GROUP BY src ORDER BY 3 DESC").fetchall()
        stages = con.execute("SELECT stage, COUNT(*) FROM cases GROUP BY stage").fetchall()
    lines = ["<b>Выдано документов</b>"] + [f"{d}: {n}" for d, n, s in rows]
    lines += ["", "<b>Воронка за 7 дней</b>"] + [f"{k}: {n}" for k, n in funnel]
    lines += ["", "<b>Источники</b>"] + [f"{s or '—'}: {n}" for s, n, r in srcs]
    lines += ["", "<b>Дела по этапам</b>"] + [f"{k}: {n}" for k, n in stages]
    await m.answer("\n".join(lines))


@router.message(F.text)
async def fallback(m: Message, state: FSMContext) -> None:
    await show_home(m, state)


# ================================================================= напоминания
async def reminder_loop(bot: Bot) -> None:
    while True:
        try:
            with db() as con:
                due = con.execute("SELECT id, case_id, chat_id, text FROM reminders WHERE due IS NOT NULL AND due <= ?",
                                  (int(time.time()),)).fetchall()
            for rid, cid, chat_id, text in due:
                markup = kb([[(ui.BTN_RESOLVED, f"res:{cid}")], [(ui.BTN_NO_ANSWER, f"nx:{cid}")]])
                try:
                    await bot.send_message(chat_id, ui.reminder(text), reply_markup=markup)
                except Exception as e:  # noqa: BLE001 — пользователь мог заблокировать бота
                    log.warning("reminder %s failed: %s", rid, e)
                with db() as con:
                    con.execute("DELETE FROM reminders WHERE id=?", (rid,))
        except Exception as e:  # noqa: BLE001
            log.exception("reminder loop: %s", e)
        await asyncio.sleep(60)


async def main() -> None:
    if not BOT_TOKEN:
        raise SystemExit("Нет BOT_TOKEN в .env")
    if KEY_RATE <= 0:
        raise SystemExit("Впишите в .env KEY_RATE — текущую ключевую ставку ЦБ (cbr.ru)")
    bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    asyncio.create_task(reminder_loop(bot))
    log.info("Желток запущен: %d документов, Mini App: %s", len(CAT.docs), MINIAPP_URL or "не подключён")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
