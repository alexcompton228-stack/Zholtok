"""Сверка логики Mini App (miniapp/logic.js) с Python-ядром на случайных анкетах.
Сравниваются: следующий вопрос, чистка устаревших ответов, предупреждения, проверка ответов.
Запуск: python test_miniapp_logic.py   (нужен Node.js)
"""
import datetime as dt
import json
import os
import random
import subprocess

os.environ["ENGINE_TODAY"] = "29.09.2026"
import build_miniapp  # noqa: E402
import engine  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
TODAY_ISO = "2026-09-29"
CFG = {"key_rate": 16.0}
N = 600


def rand_value(q, rnd):
    t = q["type"]
    if t == "choice":
        return rnd.choice(q["options"])["v"]
    if t == "yesno":
        return rnd.random() < 0.5
    if t == "multi":
        return [o["v"] for o in q["options"] if rnd.random() < 0.5] or [q["options"][0]["v"]]
    if t == "date":
        return (engine.today() - dt.timedelta(days=rnd.randint(0, 900))).isoformat()
    if t == "money":
        return float(rnd.randint(100, 3000000 if q["key"] == "income" else 200000))
    if t == "int":
        if q["key"] == "year":                      # проверяем условия с today.year
            return engine.today().year - rnd.randint(-1, 6)
        return rnd.randint(1, 20)
    return str(q.get("example", "текст"))


def to_py(q, v):
    return dt.date.fromisoformat(v) if q["type"] == "date" else v


def main():
    data = build_miniapp.export()
    cat = engine.Catalog(os.path.join(HERE, "catalog.yaml"))
    rnd = random.Random(7)
    cases = []
    for jd in data["docs"]:
        pd = cat.docs[jd["id"]]
        qmap = {q["key"]: q for q in pd["questions"]}
        for _ in range(N):
            ans = {}
            for q in pd["questions"]:
                if rnd.random() < 0.12:
                    break
                ans[q["key"]] = rand_value(q, rnd)
            py_ans = {k: to_py(qmap[k], v) for k, v in ans.items()}
            nq = engine.next_question(pd, py_ans, CFG)
            pr = engine.prune(pd, py_ans, CFG)
            full = engine.next_question(pd, pr, CFG) is None
            warns = [w["text"] for w in engine.check_warnings(pd, pr, CFG)] if full else None
            cases.append({"doc": jd["id"], "answers": ans, "next": nq["key"] if nq else None,
                          "pruned": sorted(pr), "warnings": warns})
    # проверка ответов (parseAnswer) на наборе строк
    samples = {"money": ["24990", "24 990", "24990,50", "0", "abc", "1e12", "₽ 100"],
               "fio": ["Иванов Иван", "иванов иван иванович", "Иван", "Ivanov-Petrov Ivan", "Иванов 123"],
               "int": ["10", "0", "-1", "3.5", "1234567"],
               "text": ["", "ООО «Ромашка»", "x" * 501],
               "date": ["2026-09-29", "2026-10-01", "1990-01-01", "2026-02-30"]}
    pchecks = []
    for typ, vals in samples.items():
        for v in vals:
            q = {"type": typ, "past": True}
            raw = v
            if typ == "date":
                d = dt.date.fromisoformat(v) if v != "2026-02-30" else None
                raw = d.strftime("%d.%m.%Y") if d else "30.02.2026"
            val, err = engine.parse_answer(q, raw)
            if isinstance(val, dt.date):
                val = val.isoformat()
            pchecks.append({"q": q, "raw": v, "ok": err is None, "value": val})

    js = f"""
const L = require({json.dumps(os.path.join(HERE, 'miniapp', 'logic.js'))});
L._setToday({json.dumps(TODAY_ISO)});
const data = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const docs = Object.fromEntries(data.catalog.docs.map(d => [d.id, d]));
let fails = [];
for (const c of data.cases) {{
  const d = docs[c.doc];
  const nq = L.nextQuestion(d, c.answers);
  const pr = Object.keys(L.prune(d, c.answers)).sort();
  if ((nq ? nq.key : null) !== c.next) fails.push(['next', c.doc, c.next, nq && nq.key]);
  if (JSON.stringify(pr) !== JSON.stringify(c.pruned)) fails.push(['prune', c.doc, c.pruned, pr]);
  if (c.warnings) {{
    const p = L.prune(d, c.answers);
    const w = L.warnings(d, p).map(x => x.text);
    if (JSON.stringify(w) !== JSON.stringify(c.warnings)) fails.push(['warn', c.doc, c.warnings, w]);
  }}
}}
for (const p of data.pchecks) {{
  const r = L.parseAnswer(p.q, p.raw);
  const ok = !r.error;
  if (ok !== p.ok || (ok && JSON.stringify(r.value) !== JSON.stringify(p.value)))
    fails.push(['parse', p.q.type, p.raw, p.ok, p.value, r]);
}}
console.log(JSON.stringify({{n: data.cases.length, p: data.pchecks.length, fails: fails.slice(0, 10), nf: fails.length}}));
"""
    res = subprocess.run(["node", "-e", js], input=json.dumps({"catalog": data, "cases": cases, "pchecks": pchecks}),
                         capture_output=True, text=True, check=True)
    out = json.loads(res.stdout)
    print(f"Анкет сверено: {out['n']}, проверок ввода: {out['p']}, расхождений: {out['nf']}")
    for f in out["fails"]:
        print("  ", f)
    raise SystemExit(1 if out["nf"] else 0)


if __name__ == "__main__":
    main()
