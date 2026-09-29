"""Тексты и компоненты интерфейса «Желтка» (обычный Telegram-бот).

Один файл = один голос бренда: спокойно, на «вы», одна задача на сообщение.
Кнопки названы действиями. Эмодзи не используем; статусы дела — знаками ✓ и ○.
Оформление Telegram (фон, шрифт, цвет сообщений) бот не меняет — только текст и кнопки.
"""
from __future__ import annotations

import datetime as dt
import html

BRAND = "Желток"
TAGLINE = "Документы. По шагам."


def esc(s) -> str:
    return html.escape(str(s))


def _d(ts: int | None) -> str:
    return dt.date.fromtimestamp(ts).strftime("%d.%m.%Y") if ts else ""


# ---------------------------------------------------------------- кнопки
BTN_START = "Начать"
BTN_NEW = "Новая ситуация"
BTN_CONTINUE = "Продолжить: {name}"
BTN_CASES = "Мои дела · {n}"
BTN_BACK = "← Назад"
BTN_HOME = "На главную"
BTN_FILL = "Начать заполнение"
BTN_CONSENT = "Даю согласие, продолжить"
BTN_EXIT = "Сохранить и выйти"
BTN_KEEP = "Оставить как было"
BTN_YES, BTN_NO = "Да", "Нет"
BTN_DONE = "Готово"
BTN_TO_REVIEW = "К проверке сведений"
BTN_EDIT_SECTION = "Изменить: {title}"
BTN_EDIT_FIELD = "{label}: {value}"
BTN_EDIT_ANSWERS = "Изменить ответы"
BTN_OTHER_DOC = "Выбрать другой документ"
BTN_TO_DRAFT = "Всё верно — показать черновик"
BTN_DOWNLOAD = "Скачать документ"
BTN_OPEN_APP = "Открыть Желток"
BTN_MARK_SENT = "Отметить отправку"
BTN_TODAY, BTN_YESTERDAY, BTN_OTHER_DATE = "Сегодня", "Вчера", "Другая дата"
BTN_RESOLVED = "Вопрос решён"
BTN_NO_ANSWER = "Ответа нет или отказ"
BTN_PREPARE = "Подготовить: {name}"
BTN_DELETE_CASE = "Удалить дело"
BTN_ALL_CASES = "Мои дела"


# ---------------------------------------------------------------- главный экран и выбор
def home(draft: bool) -> str:
    text = ("<b>Разберёмся с вашей ситуацией</b>\n\n"
            "Ответьте на несколько вопросов — подготовим документ и объясним, что делать дальше.")
    if draft:
        text += "\n\nУ вас есть незаконченный документ — можно продолжить с того же места."
    return text


SITUATIONS = "<b>Что произошло?</b>\nВыберите, к чему ближе ваша ситуация."


def category(title: str) -> str:
    return f"<b>{esc(title)}</b>\nВыберите документ."


def doc_card(d: dict, price: str, in_app: bool = False) -> str:
    text = (f"<b>{esc(d['title'])}</b>\n\n{esc(d['short'])}\n\n"
            f"<b>Что вы получите</b>\n{esc(d['gives'])}\n\n"
            f"<b>Основания:</b> {esc('; '.join(d.get('basis', [])))}\n"
            f"<b>Стоимость:</b> {price}\n\n"
            "<i>Документ собирается автоматически по шаблону. Это не юридическая консультация.</i>")
    if in_app:
        text += f"\n\nУдобнее заполнить в приложении — кнопка «{BTN_OPEN_APP}» под полем ввода. Или прямо здесь, в чате."
    return text


APP_HINT = (f"Самые частые ситуации удобнее оформить в приложении — кнопка «{BTN_OPEN_APP}» под полем ввода. "
            "Остальные документы — в чате.")
APP_BAD_DATA = "Не получилось прочитать данные из приложения. Откройте его ещё раз и нажмите «Подготовить документ»."
APP_DUPLICATE = "Этот документ уже подготовлен — файл выше в чате."


def app_invalid(label: str | None) -> str:
    what = f" Проверьте поле «{esc(label)}»." if label else " Не хватает ответов."
    return "Документ пока не собрать." + what + " Откройте приложение — ваши ответы сохранены — и отправьте ещё раз."


MEMO_FILENAME = "Памятка_Желток.docx"
MEMO_CAPTION = "Памятка: что делать дальше. Она для вас — адресату отправляйте только документ."
MEMO_FALLBACK = "<b>Что дальше</b>\nРаспечатайте и подпишите документ, отправьте его адресату и сохраните подтверждение отправки."


def consent(policy_url: str) -> str:
    link = f'\n\n<a href="{esc(policy_url)}">Политика обработки данных</a>' if policy_url else ""
    return ("<b>Перед началом</b>\n\n"
            "Для документа понадобятся ваши ФИО, адрес и сведения о ситуации. "
            "Они нужны только для этого файла: хранятся, пока вы заполняете анкету, "
            "и удаляются после выдачи документа." + link)


# ---------------------------------------------------------------- вопросы
def question(q: dict, n: int, total: int, section: str, editing: bool, prev_label: str | None) -> str:
    head = f"<b>Изменение · {esc(section)}</b>" if editing else f"<b>Раздел {n} из {total} · {esc(section)}</b>"
    parts = [head, "", esc(q["q"])]
    if q.get("why"):
        parts.append(f"<i>{esc(q['why'])}</i>")
    ex = q.get("example")
    if q["type"] in ("text", "long", "fio", "money", "int") and ex and "Например" not in q["q"]:
        parts.append(f"<i>Например: {esc(ex)}</i>")
    if q["type"] == "date":
        parts.append("<i>Например: 05.09.2026</i>")
    if prev_label:
        parts.append(f"\nСейчас указано: {esc(prev_label)}")
    return "\n".join(parts)


def input_error(err: str) -> str:
    return f"{esc(err)}\nПопробуйте ещё раз — остальные ответы сохранены."


STALE_BUTTON = "Этот вопрос уже позади"
MULTI_EMPTY = "Отметьте хотя бы один вариант"


# ---------------------------------------------------------------- проверка
def review(doc: dict, sections: list, notes: list[str]) -> str:
    parts = ["<b>Проверьте сведения</b>", esc(doc["title"]), ""]
    for title, rows in sections:
        parts.append(f"<b>{esc(title)}</b>")
        for label, value in rows:
            v = f"<i>{esc(value)}</i>" if value == "не указано" else esc(value)
            parts.append(f"{esc(label)}: {v}")
        parts.append("")
    if notes:
        parts.append("<b>Обратите внимание</b>")
        parts += [esc(n) for n in notes]
        parts.append("")
    parts.append("Если всё верно, покажу черновик документа.")
    text = "\n".join(parts)
    return text if len(text) < 3900 else text[:3880] + "…"


def edit_section(title: str) -> str:
    return f"<b>{esc(title)}</b>\nЧто изменить? Остальные ответы сохранятся."


def blocked(text: str) -> str:
    return (f"<b>Этот документ сейчас не поможет</b>\n\n{esc(text)}\n\n"
            "Если вы ошиблись в ответе (например, в дате), его можно исправить.")


# ---------------------------------------------------------------- черновик и выдача
def draft(doc: dict, shown_escaped: str, rest: int) -> str:
    tail = f"\n… ещё {rest} абз. в полном документе." if rest else ""
    return (f"<b>Черновик</b> · {esc(doc['title'])}\n\n<pre>{shown_escaped}</pre>{tail}\n\n"
            "Полный документ — файл .docx: откроется в Word, Google Документах и на телефоне. "
            "Его нужно распечатать и подписать.")


ALREADY_ISSUED = "Этот документ уже выдан — файл выше в чате."
NOT_READY = "Сначала ответьте на все вопросы."
PAY_STALE = "Данные анкеты устарели. Заполните документ заново, пожалуйста."


def prepared_caption(doc: dict) -> str:
    return f"<b>Документ подготовлен</b>\n{esc(doc['title'])} · .docx"


def after_delivery(after_html: str, tracked: bool) -> str:
    text = after_html or "<b>Что дальше</b>\nРаспечатайте и подпишите документ."
    text += "\n\nДанные анкеты удалены. Файл остаётся в этом чате."
    if tracked:
        text += "\n\nКогда отправите или вручите документ, отметьте это — подскажу, когда проверять ответ."
    return text


# ---------------------------------------------------------------- дела
STAGE_SHORT = {"prepared": "подготовлен", "sent": "ожидается ответ", "next": "нужен следующий шаг",
               "resolved": "решено"}
CASES_TITLE = "<b>Мои дела</b>\nВыберите дело, чтобы посмотреть этап и следующий шаг."
NO_CASES = "Дел пока нет. Они появятся после того, как вы получите первый документ."


def case_card(title: str, stage: str, created: int, sent_at: int | None, rem: int | None) -> str:
    done = "✓"
    todo = "○"
    lines = [f"<b>{esc(title)}</b>", "",
             f"{done} Сведения собраны",
             f"{done} Документ подготовлен · {_d(created)}"]
    if stage == "prepared":
        lines += [f"{todo} Отправка подтверждена", f"{todo} Ожидается ответ", f"{todo} Следующий шаг",
                  "", "Когда отправите документ, отметьте отправку."]
    else:
        lines.append(f"{done} Отправка подтверждена · {_d(sent_at)}")
        if stage == "sent":
            lines.append(f"{todo} Ожидается ответ" + (f" · напомню {_d(rem)}" if rem else ""))
            lines += [f"{todo} Следующий шаг", "", "Пришёл ответ? Отметьте результат."]
        elif stage == "resolved":
            lines += [f"{done} Ответ получен", f"{done} Вопрос решён"]
        else:
            lines += [f"{done} Ответ не получен или отказ", f"{todo} Следующий шаг"]
    return "\n".join(lines)


ASK_SENT_DATE = "<b>Когда вы отправили или вручили документ?</b>\nОт этой даты считаются сроки ответа."
ASK_SENT_DATE_TEXT = "Укажите дату отправки в формате ДД.ММ.ГГГГ, например 05.09.2026."


def sent_confirmed(d: dt.date, rem: int | None) -> str:
    text = f"<b>Отправка отмечена: {d.strftime('%d.%m.%Y')}</b>\nОжидаем ответ."
    if rem:
        text += f"\n{_d(rem)} напомню проверить, пришёл ли ответ, и подскажу следующий шаг."
    else:
        text += "\nКогда придёт ответ, отметьте результат в разделе «Мои дела»."
    return text


def reminder(text: str) -> str:
    return f"<b>Проверка ответа</b>\n\n{text}"


RESOLVED = "<b>Вопрос решён</b>\nДело закрыто. Если понадобится другой документ — начните с главного экрана."


def next_step(title: str) -> str:
    return (f"<b>Следующий шаг</b>\n\nЕсли ответа нет или вам отказали, следующий документ — «{esc(title)}». "
            "Готовить его или нет, решаете вы.")


NEXT_STEP_GENERIC = ("<b>Следующий шаг</b>\n\nВарианты действий описаны в инструкции к документу выше в чате. "
                     "Можно выбрать другой документ.")
CASE_DELETED = "Дело удалено вместе с напоминаниями."


# ---------------------------------------------------------------- служебное
def help_text(support: str) -> str:
    text = (f"<b>{BRAND}</b> — {TAGLINE}\n\n"
            "1. Выберите ситуацию и ответьте на вопросы.\n"
            "2. Проверьте сведения и черновик.\n"
            "3. Скачайте документ и отметьте отправку — подскажу, когда проверять ответ.\n\n"
            "/menu — главный экран\n/privacy — какие данные хранятся\n/delete — удалить мои данные")
    return text + (f"\n\nПоддержка: {esc(support)}" if support else "")


def privacy(policy_url: str) -> str:
    text = ("<b>Какие данные хранятся</b>\n\n"
            "Ответы анкеты — только в оперативной памяти бота или на вашем устройстве (в приложении), пока вы заполняете документ; "
            "после выдачи файла они удаляются. "
            "На сервере остаются: отметка о согласии, ваши дела (какой документ и на каком этапе), "
            "напоминания о сроках и обезличенная статистика.")
    return text + (f'\n\n<a href="{esc(policy_url)}">Политика обработки данных</a>' if policy_url else "")


DELETED = "Готово: дела, напоминания и отметка о согласии удалены."
