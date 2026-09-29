/* Желток — логика анкеты для Mini App.
   Зеркало engine.py: следующий вопрос, проверка ответов, чистка устаревших ответов, предупреждения.
   Сверяется с Python-ядром тестом test_miniapp_logic.py. Работает и в браузере, и в Node. */
(function (root) {
  "use strict";

  var TODAY_OVERRIDE = null;           // для тестов: "YYYY-MM-DD"

  function today() {
    var d = TODAY_OVERRIDE ? new Date(TODAY_OVERRIDE + "T00:00:00") : new Date();
    return new Date(d.getFullYear(), d.getMonth(), d.getDate());
  }
  function parseISO(s) {
    if (typeof s !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(s)) return null;
    var p = s.split("-").map(Number);
    var d = new Date(p[0], p[1] - 1, p[2]);
    return (d.getFullYear() === p[0] && d.getMonth() === p[1] - 1 && d.getDate() === p[2]) ? d : null;
  }
  function daysSince(iso) {
    var d = parseISO(iso);
    if (!d) return NaN;
    return Math.round((today() - d) / 86400000);
  }
  function fmtDate(iso) {
    var d = parseISO(iso);
    if (!d) return "";
    var dd = String(d.getDate()).padStart(2, "0"), mm = String(d.getMonth() + 1).padStart(2, "0");
    return dd + "." + mm + "." + d.getFullYear();
  }
  function money(x) {
    var n = Number(x || 0);
    var int = Math.round(n * 100) % 100 === 0;
    var s = int ? String(Math.round(n)) : n.toFixed(2);
    var parts = s.split(".");
    parts[0] = parts[0].replace(/\B(?=(\d{3})+(?!\d))/g, " ");
    return parts.join(",");
  }

  var HELPERS = {
    days_since: daysSince,
    inc: function (arr, v) { return Array.isArray(arr) && arr.indexOf(v) >= 0; }
  };
  var compiled = {};
  function evalCond(expr, ctx) {
    if (!expr) return true;
    if (!compiled[expr]) {
      // условия приходят только из нашего catalog.json, не от пользователя
      compiled[expr] = new Function("c", "H", "with (H) { with (c) { return (" + expr + "); } }");
    }
    try { return !!compiled[expr](ctx, HELPERS); } catch (e) { return false; }
  }

  function baseContext(doc, answers) {
    var ctx = {};
    doc.questions.forEach(function (q) {
      ctx[q.key] = Object.prototype.hasOwnProperty.call(answers, q.key) ? answers[q.key]
        : (q.type === "multi" ? [] : null);
    });
    return ctx;
  }
  function isAsked(q, ctx) { return evalCond(q.when, ctx); }

  function nextQuestion(doc, answers) {
    var ctx = baseContext(doc, answers);
    for (var i = 0; i < doc.questions.length; i++) {
      var q = doc.questions[i];
      if (Object.prototype.hasOwnProperty.call(answers, q.key)) continue;
      if (isAsked(q, ctx)) return q;
    }
    return null;
  }

  function prune(doc, answers) {
    var a = Object.assign({}, answers), changed = true;
    while (changed) {
      changed = false;
      var ctx = baseContext(doc, a);
      for (var i = 0; i < doc.questions.length; i++) {
        var q = doc.questions[i];
        if (Object.prototype.hasOwnProperty.call(a, q.key) && !isAsked(q, ctx)) {
          delete a[q.key]; changed = true; break;
        }
      }
    }
    return a;
  }

  function warnings(doc, answers) {
    var ctx = baseContext(doc, answers);
    return doc.warnings.filter(function (w) { return evalCond(w.when, ctx); });
  }

  /* Проверка ответа. Возвращает {value} или {error}. Для дат значение — "YYYY-MM-DD". */
  function parseAnswer(q, raw) {
    var t = (raw == null ? "" : String(raw)).trim();
    if (q.optional && (t === "" || t === "-" || t === "—")) return { value: "" };
    if (!t) return { error: q.type === "date" ? "Укажите дату." : "Заполните поле, чтобы продолжить." };
    switch (q.type) {
      case "text":
        return t.length <= 500 ? { value: t } : { error: "Получилось длинно — сократите, пожалуйста, до 500 символов." };
      case "long":
        return t.length <= 1500 ? { value: t.replace(/\.+$/, "") } : { error: "Получилось длинно — сократите, пожалуйста, до 1500 символов." };
      case "fio": {
        var words = t.split(/\s+/);
        if (words.length < 2 || !words.every(function (w) { return /^[А-ЯЁа-яёA-Za-z-]+$/.test(w); }))
          return { error: "Укажите фамилию и имя (и отчество, если есть) буквами, например: Иванов Иван Иванович." };
        return { value: words.map(function (w) { return w.charAt(0).toUpperCase() + w.slice(1); }).join(" ") };
      }
      case "money": {
        var s = t.replace(/(руб\.?|р\.|₽|\s)/gi, "").replace(",", ".");
        var v = Number(s);
        if (!s || isNaN(v)) return { error: "Укажите сумму цифрами, например 24990 или 24990,50." };
        if (v <= 0 || v > 1e9) return { error: "Сумма должна быть больше нуля." };
        return { value: Math.round(v * 100) / 100 };
      }
      case "int":
        if (!/^\d{1,6}$/.test(t)) return { error: "Укажите целое число цифрами, например 10." };
        return Number(t) > 0 ? { value: Number(t) } : { error: "Число должно быть больше нуля." };
      case "date": {
        var d = parseISO(t);
        if (!d) return { error: "Укажите дату полностью: день, месяц и год." };
        if (q.past && d > today()) return { error: "Эта дата ещё не наступила — проверьте год и месяц." };
        var min = new Date(today()); min.setFullYear(min.getFullYear() - 30);
        if (d < min) return { error: "Дата слишком давняя — проверьте год." };
        return { value: t };
      }
      default:
        return { error: "Выберите вариант." };
    }
  }

  function optionLabel(q, v) {
    var o = (q.options || []).filter(function (x) { return x.v === v; })[0];
    return o ? o.label : String(v);
  }
  function fmtValue(q, v) {
    if (v === null || v === undefined || v === "" || (Array.isArray(v) && !v.length)) return null;
    switch (q.type) {
      case "date": return fmtDate(v);
      case "money": return money(v) + " ₽";
      case "yesno": return v ? "да" : "нет";
      case "choice": return optionLabel(q, v);
      case "multi": return v.map(function (x) { return optionLabel(q, x); }).join(", ");
      default: return String(v);
    }
  }

  function summary(doc, answers) {
    var ctx = baseContext(doc, answers), out = [];
    doc.sections.forEach(function (title) {
      var rows = doc.questions.filter(function (q) {
        return q.section === title && (Object.prototype.hasOwnProperty.call(answers, q.key) || isAsked(q, ctx));
      }).map(function (q) { return { q: q, value: fmtValue(q, answers[q.key]) }; });
      if (rows.length) out.push({ title: title, rows: rows });
    });
    return out;
  }

  function sectionInfo(doc, key) {
    var q = doc.questions.filter(function (x) { return x.key === key; })[0];
    return { n: doc.sections.indexOf(q.section) + 1, total: doc.sections.length, title: q.section };
  }

  /* Вопросы, которые задаются при текущих ответах, в порядке анкеты. */
  function sequence(doc, answers) {
    var ctx = baseContext(doc, answers);
    return doc.questions.filter(function (q) { return isAsked(q, ctx); });
  }

  var api = {
    sequence: sequence, nextQuestion: nextQuestion, prune: prune, warnings: warnings, parseAnswer: parseAnswer,
    summary: summary, sectionInfo: sectionInfo, fmtValue: fmtValue, fmtDate: fmtDate, money: money,
    daysSince: daysSince, today: today,
    _setToday: function (iso) { TODAY_OVERRIDE = iso; }
  };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.ZLogic = api;
})(typeof window !== "undefined" ? window : this);
