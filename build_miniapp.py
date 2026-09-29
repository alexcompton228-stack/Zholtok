"""Собирает данные для Mini App из catalog.yaml.

Запуск:  python build_miniapp.py
Результат: miniapp/catalog.json (+ картинки бренда в miniapp/img/).
Какие документы попадают в приложение — список MINIAPP_DOCS ниже (или переменная окружения).
Условия вопросов переводятся из синтаксиса Jinja в JavaScript; перевод проверяется тестом test_miniapp_logic.py.
"""
import json
import os
import re
import shutil

import engine

HERE = os.path.dirname(os.path.abspath(__file__))
MINIAPP_DOCS = os.environ.get("MINIAPP_DOCS", "vozvrat_brak,zalog_arenda,otkaz_strahovka").split(",")

ALLOWED = re.compile(r"^[\w\s'().<>=!&|,-]*$")


def to_js(expr: str | None) -> str | None:
    """Переводит простое условие Jinja в JS. Поддерживаются: and/or/not, ==, !=, <, >, <=, >=,
    числа, строки в одинарных кавычках, days_since(x), 'v' in list, true/false."""
    if not expr:
        return None
    s = expr.strip()
    s = re.sub(r"'([^']*)'\s+in\s+(\w+)", r"inc(\2, '\1')", s)
    s = re.sub(r"\bnot\s+", "!", s)
    s = re.sub(r"\band\b", "&&", s)
    s = re.sub(r"\bor\b", "||", s)
    s = re.sub(r"(?<![=!<>])==(?!=)", "===", s)
    s = re.sub(r"!=(?!=)", "!==", s)
    if not ALLOWED.match(s):
        raise ValueError(f"условие не переводится в JS: {expr!r}")
    return s


def export() -> dict:
    cat = engine.Catalog(os.path.join(HERE, "catalog.yaml"))
    docs = []
    for doc_id in MINIAPP_DOCS:
        d = cat.docs[doc_id]
        qs = []
        for q in d["questions"]:
            item = {k: q[k] for k in ("key", "type", "q", "label", "section") if k in q}
            for k in ("options", "optional", "past", "why"):
                if k in q:
                    item[k] = q[k]
            ex = q.get("example")
            if ex is not None and q["type"] in ("text", "long", "fio", "money", "int") and "Например" not in q["q"]:
                item["example"] = str(ex)
            item["when"] = to_js(q.get("when"))
            qs.append(item)
        docs.append({
            "id": d["id"], "title": d["title"], "button": d["button"], "short": d["short"], "gives": d["gives"],
            "basis": d.get("basis", []), "sections": d["_sections"], "questions": qs,
            "warnings": [{"when": to_js(w["when"]), "block": bool(w.get("block")), "text": w["text"]}
                         for w in d.get("warnings") or []],
        })
    return {"version": 1, "docs": docs}


def main() -> None:
    out_dir = os.path.join(HERE, "miniapp")
    os.makedirs(os.path.join(out_dir, "img"), exist_ok=True)
    data = export()
    with open(os.path.join(out_dir, "catalog.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    for name in ("wordmark.png", "wordmark-dark.png", "mark-tagline.png", "mark-tagline-dark.png"):
        shutil.copy(os.path.join(HERE, "brand", name), os.path.join(out_dir, "img", name))
    print(f"miniapp/catalog.json: {len(data['docs'])} документа: {', '.join(d['id'] for d in data['docs'])}")


if __name__ == "__main__":
    main()
