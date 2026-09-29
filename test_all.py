"""Прогон всех документов: анкета по примерам -> предупреждения -> текст -> .docx.

Запуск:  python test_all.py            (кладёт образцы в папку samples/)
Ветки покрываются вариантами из VARIANTS.
"""
import datetime as dt
import os
import sys

import engine

HERE = os.path.dirname(os.path.abspath(__file__))
CFG = {"key_rate": 16.0}   # в тестах любая ставка; в боте берётся из .env

VARIANTS = {
    "vozvrat_brak": [
        {},
        {"demand": "replace", "tech_complex": False, "channel": "online"},
        {"buy_date": "-40d", "essential": "repair_long", "refund_method": "details", "seller_inn": "-", "email": "-"},
        {"buy_date": "-40d", "essential": "none"},                      # должен заблокироваться
    ],
    "obmen_25": [{}, {"buy_date": "-20d"}],
    "otkaz_distant": [{}, {"info_given": False, "received_date": "-30d", "order_no": "-"}],
    "usluga": [{}, {"demand": "discount"}, {"demand": "refund", "refund_ground": "not_fixed"}, {"demand": "refund", "refund_ground": "none"}],
    "zhaloba_rpn": [{}, {"response": "refusal", "company_inn": "-"}],
    "spravka_dohod": [{}, {"fired": True, "docs": ["zarabotok", "dogovor", "prikazy"], "delivery": "mail"}],
    "zarplata": [{}, {"fired": True}, {"due_date": "-10d"}],
    "vychet_plan": [{}, {"types": ["med", "drugs", "edu", "fit", "exp"], "income": "300000"}, {"year": "2019"}],
    "spravka_vychet": [{}, {"org_type": "edu", "whom": "child", "delivery": "email"}, {"org_type": "fit", "contract": "-"}],
    "zalog_arenda": [{}, {"excuse": "damage", "act": False}, {"excuse": "early", "landlord_address": "г. Москва, ул. Хозяйская, д. 1"}],
    "akt_arenda": [{}, {"direction": "out"}],
    "otkaz_strahovka": [{}, {"with_credit": False, "policy_date": "-20d"}, {"policy_date": "-20d"}],
    "otzyv_pd": [{}, {"client": True, "spam": False}],
}


def example_value(q, override):
    v = override.get(q["key"], q.get("example"))
    typ = q["type"]
    if typ in ("choice", "yesno", "multi"):
        if typ == "choice":
            assert v in [o["v"] for o in q["options"]], f"{q['key']}: пример {v!r} не из вариантов"
        if typ == "multi":
            assert all(x in [o["v"] for o in q["options"]] for x in v), q["key"]
        return v
    if typ == "date" and isinstance(v, str) and v.endswith("d") and v[:-1].lstrip("-").isdigit():
        return engine.today() - dt.timedelta(days=abs(int(v[:-1])))
    val, err = engine.parse_answer(q, str(v))
    assert err is None, f"{q['key']}: пример {v!r} не прошёл проверку: {err}"
    return val


def run(cat, doc_id, override, out_dir, tag):
    doc = cat.docs[doc_id]
    answers, asked = {}, []
    while True:
        q = engine.next_question(doc, answers, CFG)
        if q is None:
            break
        answers[q["key"]] = example_value(q, override)
        asked.append(q["key"])
        assert len(asked) < 60, "анкета зациклилась"
    warns = engine.check_warnings(doc, answers, CFG)
    blocked = any(w["block"] for w in warns)
    status = "БЛОК" if blocked else "ok"
    if not blocked:
        text = engine.render_text(doc, answers, CFG)
        assert "{{" not in text and "{%" not in text, "не отрендерился Jinja"
        data = engine.build_docx(text)
        name = f"{doc_id}{'_' + tag if tag else ''}.docx"
        with open(os.path.join(out_dir, name), "wb") as f:
            f.write(data)
        engine.render_snippet(doc.get("after", ""), doc, answers, CFG)
        for fu in doc.get("followups") or []:
            engine.render_snippet(fu["text"], doc, answers, CFG)
            if fu.get("offer"):
                assert fu["offer"] in cat.docs, f"followup offer {fu['offer']} не найден"
        engine.preview_text(text)
    return status, len(asked), warns


def main():
    cat = engine.Catalog(os.path.join(HERE, "catalog.yaml"))
    out_dir = os.path.join(HERE, "samples")
    os.makedirs(out_dir, exist_ok=True)
    fails = 0
    for doc_id in cat.docs:
        for i, ov in enumerate(VARIANTS.get(doc_id, [{}])):
            try:
                status, n, warns = run(cat, doc_id, ov, out_dir, f"v{i}" if i else "")
                wtxt = f" | предупреждений: {len(warns)}" if warns else ""
                print(f"{status:5} {doc_id:16} v{i}  вопросов: {n}{wtxt}")
            except Exception as e:  # noqa: BLE001
                fails += 1
                print(f"FAIL  {doc_id:16} v{i}  {type(e).__name__}: {e}")
    print(f"\nДокументов: {len(cat.docs)}, ошибок: {fails}")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
