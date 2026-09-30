/* Желток — Mini App. Экраны: главный → документ → вопросы по разделам → проверка → отправка в бота.
   Ответы хранятся только на устройстве (черновик) и уходят боту через Telegram.WebApp.sendData. */
(function () {
  "use strict";
  var L = window.ZLogic;
  var tg = window.Telegram && window.Telegram.WebApp;
  // Внутри Telegram platform — ios/android/tdesktop/…, в обычном браузере скрипт Telegram ставит "unknown".
  var inTG = !!(tg && tg.platform && tg.platform !== "unknown");
  // sendData работает только в приложении, открытом кнопкой под полем ввода. При таком запуске initData пустой;
  // при запуске из меню, профиля бота, по ссылке или из инлайн-кнопки Telegram передаёт подписанный initData.
  var canSend = inTG && !tg.initData;
  var APP_BUTTON = "Открыть Желток";
  var DRAFT_KEY = "zholtok.draft.v1", CONSENT_KEY = "zholtok.consent.v1";
  var BRAND_YELLOW = "#F4C542", ON_YELLOW = "#24251F";

  var S = { docs: {}, order: [], doc: null, answers: {}, mode: "fill", submitId: null, sentAt: null };
  var KEEP_SENT_MS = 24 * 3600 * 1000;   // после отправки ответы живут на устройстве сутки
  var $app = document.getElementById("app");
  var $cta = document.getElementById("cta"), $ctabar = document.getElementById("ctabar");
  var $back = document.getElementById("back");

  // ------------------------------------------------------------ утилиты
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function store(key, val) {
    try { if (val === undefined) localStorage.removeItem(key); else localStorage.setItem(key, JSON.stringify(val)); } catch (e) {}
  }
  function load(key) {
    try { var v = localStorage.getItem(key); return v ? JSON.parse(v) : null; } catch (e) { return null; }
  }
  function plural(n, one, few, many) {
    var m10 = n % 10, m100 = n % 100;
    if (m10 === 1 && m100 !== 11) return one;
    if (m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14)) return few;
    return many;
  }
  function uid() { return Date.now().toString(36) + Math.random().toString(36).slice(2, 8); }
  function haptic(kind) {
    try {
      if (!inTG || !tg.HapticFeedback) return;
      if (kind === "error") tg.HapticFeedback.notificationOccurred("error");
      else tg.HapticFeedback.selectionChanged();
    } catch (e) {}
  }
  function todayISO() {
    var d = L.today();
    return d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0");
  }
  function show(html) {
    $app.innerHTML = html;
    $app.style.animation = "none"; void $app.offsetWidth; $app.style.animation = "";
    window.scrollTo(0, 0);
  }

  // ------------------------------------------------------------ тема
  function applyTheme() {
    var dark = inTG ? tg.colorScheme === "dark"
      : (window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches);
    if (/[?&]theme=dark/.test(location.search)) dark = true;
    if (/[?&]theme=light/.test(location.search)) dark = false;
    document.documentElement.dataset.theme = dark ? "dark" : "light";
    var src = dark ? "img/wordmark-dark.png" : "img/wordmark.png";
    document.getElementById("wordmark").src = src;
    document.getElementById("brandmark").src = src;
    if (inTG) {
      var bg = getComputedStyle(document.documentElement).getPropertyValue("--bg").trim();
      try { tg.setHeaderColor(bg); tg.setBackgroundColor(bg); } catch (e) {}
      try { if (tg.setBottomBarColor) tg.setBottomBarColor(bg); } catch (e) {}
    }
  }

  // ------------------------------------------------------------ главная кнопка и «назад»
  var ctaHandler = null, backHandler = null;
  function cta(text, handler, disabled) {
    ctaHandler = handler;
    if (inTG) {
      tg.MainButton.setParams({ text: text, color: BRAND_YELLOW, text_color: ON_YELLOW,
                                is_active: !disabled, is_visible: true });
    } else {
      $cta.textContent = text; $cta.disabled = !!disabled; $ctabar.hidden = false;
      document.body.classList.add("has-cta");
    }
  }
  function ctaEnabled(on) {
    if (inTG) { if (on) tg.MainButton.enable(); else tg.MainButton.disable(); }
    else $cta.disabled = !on;
  }
  function hideCta() {
    ctaHandler = null;
    if (inTG) tg.MainButton.hide();
    else { $ctabar.hidden = true; document.body.classList.remove("has-cta"); }
  }
  function back(handler) {
    backHandler = handler;
    if (inTG) { if (handler) tg.BackButton.show(); else tg.BackButton.hide(); $back.hidden = true; }
    else $back.hidden = !handler;
  }
  $cta.addEventListener("click", function () { if (ctaHandler && !$cta.disabled) ctaHandler(); });
  $back.addEventListener("click", function () { if (backHandler) backHandler(); });
  if (inTG) {
    tg.MainButton.onClick(function () { if (ctaHandler) ctaHandler(); });
    tg.BackButton.onClick(function () { if (backHandler) backHandler(); });
  }

  // ------------------------------------------------------------ черновик
  function saveDraft() {
    if (S.doc) store(DRAFT_KEY, { doc: S.doc.id, answers: S.answers, submitId: S.submitId, sentAt: S.sentAt });
  }
  function dropDraft() { store(DRAFT_KEY, undefined); }
  function loadDraft() {
    var d = load(DRAFT_KEY);
    if (d && d.sentAt && Date.now() - d.sentAt > KEEP_SENT_MS) { dropDraft(); return null; }
    return d;
  }
  function openDraft(d, draft) {
    S.doc = d; S.answers = L.prune(d, draft.answers || {}); S.submitId = draft.submitId || null;
    S.sentAt = draft.sentAt || null; S.mode = "fill";
  }

  // ------------------------------------------------------------ главный экран
  function renderHome() {
    back(null); hideCta();
    var draft = loadDraft();
    var d = draft && S.docs[draft.doc];
    var html = '<h1>Разберёмся с вашей ситуацией</h1>' +
      '<p class="lead">Ответьте на несколько вопросов — подготовим документ и объясним, что делать дальше.</p>';
    if (d && draft.sentAt) {
      html += '<section class="card" aria-labelledby="sent-t">' +
        '<p class="eyebrow">Документ отправлен в чат</p>' +
        '<h3 id="sent-t">' + esc(d.title) + '</h3>' +
        '<p class="small muted">Если он не пришёл или нужно что-то исправить, откройте ответы. ' +
        'Через сутки после отправки они удалятся с устройства автоматически.</p>' +
        '<div class="row-actions"><button class="btn btn-secondary" id="reopen" type="button">Открыть ответы</button></div>' +
        '<button class="btn-link" id="drop" type="button">Удалить ответы с устройства</button></section>';
    } else if (d) {
      var n = Object.keys(draft.answers || {}).length;
      var complete = !L.nextQuestion(d, L.prune(d, draft.answers || {}));
      html += '<section class="card card-soft" aria-labelledby="draft-t">' +
        '<p class="eyebrow">' + (complete ? "Все ответы заполнены" : "Незаконченный документ") + '</p>' +
        '<h3 id="draft-t">' + esc(d.title) + '</h3>' +
        '<p class="small muted">' + (complete ? "Осталось проверить сведения и нажать «Подготовить документ»."
          : "Сохранено " + n + " " + plural(n, "ответ", "ответа", "ответов") + ". Продолжите с того же места.") + '</p>' +
        '<div class="row-actions"><button class="btn btn-primary" id="resume" type="button">' +
        (complete ? "Проверить и отправить" : "Продолжить") + '</button></div>' +
        '<button class="btn-link" id="drop" type="button">Удалить черновик</button></section>';
    }
    var groups = S.cats.map(function (c) {
      return { c: c, ids: S.order.filter(function (id) { return S.docs[id].category === c.id; }) };
    }).filter(function (g) { return g.ids.length; });
    if (groups.length > 1) {
      html += '<nav class="chips" aria-label="Разделы">' + groups.map(function (g) {
        return '<button type="button" class="chip" data-jump="cat-' + esc(g.c.id) + '">' + esc(g.c.title) + '</button>';
      }).join("") + '</nav>';
    }
    groups.forEach(function (g) {
      html += '<p class="section-title" id="cat-' + esc(g.c.id) + '">' + esc(g.c.title) + '</p>' +
        '<div role="list" aria-labelledby="cat-' + esc(g.c.id) + '">';
      g.ids.forEach(function (id) { html += card(id); });
      html += '</div>';
    });
    show(html);
    Array.prototype.forEach.call($app.querySelectorAll("[data-jump]"), function (b) {
      b.addEventListener("click", function () {
        var el = document.getElementById(b.dataset.jump);
        if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
      });
    });
    bindHome(d, draft);
  }

  function card(id) {
    var doc = S.docs[id], k = doc.sections.length;
    return '<button class="choice-card" type="button" role="listitem" data-doc="' + esc(id) + '">' +
        '<span class="body"><span class="title">' + esc(doc.button) + '</span>' +
        '<span class="desc">' + esc(doc.short) + '</span>' +
        '<span class="meta">' + k + ' ' + plural(k, "раздел", "раздела", "разделов") + ' · бесплатно</span></span>' +
        '<svg class="chev" width="20" height="20" viewBox="0 0 20 20" aria-hidden="true"><path d="M7.5 4.5 13 10l-5.5 5.5" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>' +
        '</button>';
  }

  function bindHome(d, draft) {
    Array.prototype.forEach.call($app.querySelectorAll("[data-doc]"), function (b) {
      b.addEventListener("click", function () { renderIntro(S.docs[b.dataset.doc]); });
    });
    if (d && draft.sentAt) {
      document.getElementById("reopen").addEventListener("click", function () { openDraft(d, draft); renderReview(); });
    } else if (d) {
      document.getElementById("resume").addEventListener("click", function () {
        openDraft(d, draft);
        var q = L.nextQuestion(S.doc, S.answers);
        if (q) renderQuestion(q); else renderReview();
      });
    }
    if (d) document.getElementById("drop").addEventListener("click", function () { dropDraft(); renderHome(); });
  }

  // ------------------------------------------------------------ карточка документа и согласие
  function renderIntro(doc) {
    back(renderHome);
    var consented = !!load(CONSENT_KEY);
    var html = '<p class="eyebrow">Документ</p><h1>' + esc(doc.title) + '</h1>' +
      '<p class="muted">' + esc(doc.short) + '</p>' +
      '<section class="card"><h3>Что вы получите</h3><p>' + esc(doc.gives) + '</p>' +
      '<p class="small muted" style="margin:0">Основания: ' + esc(doc.basis.join("; ")) + '</p></section>' +
      '<p class="small muted" style="margin-top:16px">Документ собирается автоматически по шаблону. Это не юридическая консультация.</p>';
    if (!consented) {
      html += '<section class="card"><label class="check"><input type="checkbox" id="consent">' +
        '<span>Даю согласие на обработку моих данных для подготовки этого документа</span></label>' +
        '<details><summary>Как хранятся данные</summary><p class="small muted" style="margin:8px 0 0">' +
        'Пока вы заполняете анкету, ответы хранятся только на вашем устройстве. ' +
        'Когда вы нажмёте «Подготовить документ», они передаются боту через Telegram, бот собирает документ и не сохраняет ответы. ' +
        'На устройстве ответы остаются ещё сутки, чтобы можно было исправить и отправить заново, затем удаляются. ' +
        'Удалить их раньше можно на главном экране.</p></details></section>';
    }
    show(html);
    cta("Начать", function () { start(doc); }, !consented);
    if (!consented) {
      document.getElementById("consent").addEventListener("change", function (e) { ctaEnabled(e.target.checked); });
    }
  }

  function start(doc) {
    store(CONSENT_KEY, { at: new Date().toISOString() });
    var draft = loadDraft();
    if (draft && draft.doc === doc.id && !draft.sentAt) openDraft(doc, draft);
    else { S.doc = doc; S.answers = {}; S.submitId = null; S.sentAt = null; S.mode = "fill"; }
    var q = L.nextQuestion(doc, S.answers);
    if (q) renderQuestion(q); else renderReview();
  }

  // ------------------------------------------------------------ вопрос
  function renderQuestion(q) {
    var doc = S.doc, info = L.sectionInfo(doc, q.key), editing = S.mode === "edit";
    var has = Object.prototype.hasOwnProperty.call(S.answers, q.key), cur = S.answers[q.key];
    var bars = "";
    for (var i = 1; i <= info.total; i++) bars += '<span class="' + (i < info.n ? "done" : i === info.n ? "now" : "") + '"></span>';
    var html = '<div class="progress" role="img" aria-label="Раздел ' + info.n + ' из ' + info.total + '">' + bars + '</div>' +
      '<p class="eyebrow">' + (editing ? "Изменение · " + esc(info.title) : "Раздел " + info.n + " из " + info.total + " · " + esc(info.title)) + '</p>';
    var t = q.type;
    if (t === "choice" || t === "yesno" || t === "multi") {
      var opts = t === "yesno" ? [{ v: true, label: "Да" }, { v: false, label: "Нет" }] : q.options;
      var role = t === "multi" ? "" : ' role="radiogroup"';
      html += '<h2 id="ql">' + esc(q.q) + '</h2>' + (q.why ? '<p class="why">' + esc(q.why) + '</p>' : "") +
        '<div' + role + ' aria-labelledby="ql">';
      opts.forEach(function (o, idx) {
        var sel = t === "multi" ? (Array.isArray(cur) && cur.indexOf(o.v) >= 0) : (has && cur === o.v);
        html += t === "multi"
          ? '<button type="button" class="option multi" aria-pressed="' + sel + '" data-i="' + idx + '"><span class="mark"></span><span>' + esc(o.label) + '</span></button>'
          : '<button type="button" class="option" role="radio" aria-checked="' + sel + '" data-i="' + idx + '"><span class="mark"></span><span>' + esc(o.label) + '</span></button>';
      });
      html += '</div><p class="error" id="err" role="alert"></p>';
      show(html);
      var buttons = $app.querySelectorAll(".option");
      if (t === "multi") {
        var picked = Array.isArray(cur) ? cur.slice() : [];
        Array.prototype.forEach.call(buttons, function (b) {
          b.addEventListener("click", function () {
            var v = opts[+b.dataset.i].v, k = picked.indexOf(v);
            if (k >= 0) picked.splice(k, 1); else picked.push(v);
            b.setAttribute("aria-pressed", String(k < 0)); haptic();
          });
        });
        cta(editing ? "Сохранить" : "Далее", function () {
          if (!picked.length) { fieldError("Отметьте хотя бы один вариант."); return; }
          var ordered = q.options.map(function (o) { return o.v; }).filter(function (v) { return picked.indexOf(v) >= 0; });
          commit(q, ordered);
        });
      } else {
        Array.prototype.forEach.call(buttons, function (b) {
          b.addEventListener("click", function () {
            Array.prototype.forEach.call(buttons, function (x) { x.setAttribute("aria-checked", "false"); });
            b.setAttribute("aria-checked", "true"); haptic();
            var v = opts[+b.dataset.i].v;
            setTimeout(function () { commit(q, v); }, 160);
          });
        });
        if (has) cta(editing ? "Сохранить" : "Далее", function () { commit(q, cur); });
        else hideCta();
      }
    } else {
      var val = has ? (t === "money" ? String(cur).replace(".", ",") : String(cur)) : "";
      var common = ' id="f" class="input" aria-describedby="err' + (q.example ? ' hint' : '') + '"';
      html += '<label class="field-label" for="f">' + esc(q.q) + '</label>' + (q.why ? '<p class="why">' + esc(q.why) + '</p>' : "");
      if (t === "long") {
        html += '<textarea' + common + ' rows="4">' + esc(val) + '</textarea>';
      } else if (t === "date") {
        html += '<input' + common + ' type="date" value="' + esc(val) + '"' + (q.past ? ' max="' + todayISO() + '"' : '') + '>';
      } else {
        var extra = ' type="text" value="' + esc(val) + '"';
        if (t === "money") extra += ' inputmode="decimal"';
        if (t === "int") extra += ' inputmode="numeric"';
        if (q.key === "phone") extra = ' type="tel" autocomplete="tel" value="' + esc(val) + '"';
        if (q.key === "email") extra = ' type="email" autocomplete="email" value="' + esc(val) + '"';
        if (q.key === "fio") extra += ' autocomplete="name"';
        if (q.key === "address") extra += ' autocomplete="street-address"';
        html += '<input' + common + extra + ' enterkeyhint="next">';
      }
      if (q.example) html += '<p class="hint" id="hint">Например: ' + esc(q.example) + '</p>';
      html += '<p class="error" id="err" role="alert"></p>';
      if (q.optional) html += '<button type="button" class="btn-link" id="skip">Пропустить</button>';
      show(html);
      var input = document.getElementById("f");
      var submit = function () {
        var raw = input.value;
        if (q.optional && raw.trim() === "") { commit(q, ""); return; }
        var r = L.parseAnswer(q, raw);
        if (r.error) { fieldError(r.error); return; }
        commit(q, r.value);
      };
      input.addEventListener("input", function () { input.removeAttribute("aria-invalid"); document.getElementById("err").textContent = ""; });
      if (t !== "long") input.addEventListener("keydown", function (e) { if (e.key === "Enter") { e.preventDefault(); submit(); } });
      if (q.optional) document.getElementById("skip").addEventListener("click", function () { commit(q, ""); });
      cta(editing ? "Сохранить" : "Далее", submit);
      try { input.focus({ preventScroll: true }); } catch (e) {}
    }
    back(editing ? renderReview : function () { prevQuestion(q); });
  }

  function fieldError(msg) {
    var el = document.getElementById("err");
    if (el) el.textContent = msg;
    var f = document.getElementById("f");
    if (f) { f.setAttribute("aria-invalid", "true"); try { f.focus({ preventScroll: true }); } catch (e) {} }
    haptic("error");
  }

  function commit(q, value) {
    S.answers[q.key] = value;
    S.answers = L.prune(S.doc, S.answers);
    S.submitId = null; S.sentAt = null;      // ответы изменились — это новая отправка
    saveDraft();
    if (S.mode === "edit") {
      var nq = L.nextQuestion(S.doc, S.answers);        // спрашиваем только то, что стало нужно
      if (nq) renderQuestion(nq); else { S.mode = "fill"; renderReview(); }
      return;
    }
    var seq = L.sequence(S.doc, S.answers);
    var idx = seq.findIndex(function (x) { return x.key === q.key; });
    var next = seq[idx + 1] || L.nextQuestion(S.doc, S.answers);
    if (next) renderQuestion(next); else renderReview();
  }

  function prevQuestion(q) {
    var seq = L.sequence(S.doc, S.answers);
    var idx = seq.findIndex(function (x) { return x.key === q.key; });
    if (idx > 0) renderQuestion(seq[idx - 1]); else renderIntro(S.doc);
  }

  // ------------------------------------------------------------ проверка
  function renderReview(errorText) {
    S.mode = "fill";
    var doc = S.doc;
    var warns = L.warnings(doc, S.answers);
    var block = warns.filter(function (w) { return w.block; })[0];
    var html = '<p class="eyebrow">Проверка</p><h1>Проверьте сведения</h1><p class="muted">' + esc(doc.title) + '</p>';
    if (errorText) html += '<section class="card card-err" role="alert"><p style="margin:0">' + esc(errorText) + '</p></section>';
    if (block) {
      html += '<section class="card card-err" role="alert"><h2>Этот документ сейчас не поможет</h2><p>' + esc(block.text) + '</p>' +
        '<p class="small muted" style="margin:0">Если вы ошиблись в ответе, например в дате, исправьте его ниже.</p></section>';
    } else if (warns.length) {
      html += '<section class="card card-soft"><h3>Обратите внимание</h3><ul class="list">' +
        warns.map(function (w) { return '<li class="small">' + esc(w.text) + '</li>'; }).join("") + '</ul></section>';
    }
    L.summary(doc, S.answers).forEach(function (sec) {
      html += '<section class="card summary-card"><h3>' + esc(sec.title) + '</h3>';
      sec.rows.forEach(function (r) {
        html += '<div class="srow"><div class="body"><span class="k">' + esc(r.q.label) + '</span>' +
          (r.value === null ? '<span class="v missing">Не указано</span>' : '<span class="v">' + esc(r.value) + '</span>') +
          '</div><button type="button" class="btn-link edit" data-key="' + esc(r.q.key) + '" aria-label="Изменить: ' + esc(r.q.label) + '">Изменить</button></div>';
      });
      html += '</section>';
    });
    if (!block) html += '<p class="small muted" style="margin-top:16px">Документ придёт в чат с ботом файлом .docx вместе с памяткой, что делать дальше.</p>';
    show(html);
    Array.prototype.forEach.call($app.querySelectorAll("[data-key]"), function (b) {
      b.addEventListener("click", function () {
        S.mode = "edit";
        renderQuestion(S.doc.questions.filter(function (q) { return q.key === b.dataset.key; })[0]);
      });
    });
    back(function () { var seq = L.sequence(S.doc, S.answers); renderQuestion(seq[seq.length - 1]); });
    if (block) hideCta(); else cta("Подготовить документ", send);
  }

  // ------------------------------------------------------------ отправка
  function send() {
    if (!S.submitId) S.submitId = uid();
    var payload = JSON.stringify({ v: 1, id: S.submitId, doc: S.doc.id, a: S.answers });
    if (new Blob([payload]).size > 4000) {
      renderReview("Ответы получились слишком длинными для передачи. Сократите, пожалуйста, самые длинные описания.");
      return;
    }
    if (!canSend) { saveDraft(); renderNotInTelegram(); return; }
    S.sentAt = Date.now();
    saveDraft();                         // сутки храним, чтобы можно было исправить; бот не выдаст дважды по одному id
    renderSending();
    tg.sendData(payload);
  }

  function stateScreen(title, text) {
    var dark = document.documentElement.dataset.theme === "dark";
    return '<div class="state"><img class="big-mark" src="img/' + (dark ? "mark-tagline-dark.png" : "mark-tagline.png") +
      '" alt="желток. Документы. По шагам."><h2>' + title + '</h2><p class="muted">' + text + '</p></div>';
  }
  function renderSending() {
    back(null); hideCta();
    show(stateScreen("Готовим документ", "Он придёт в чат с ботом через несколько секунд. Это окно закроется само."));
  }
  function renderNotInTelegram() {
    back(renderReview); hideCta();
    var how = "Закройте это окно и нажмите кнопку «" + APP_BUTTON + "» под полем ввода в чате с ботом " +
      "(если кнопки не видно — значок с квадратиками справа от поля). Ответы сохранены — на главном экране останется нажать «Проверить и отправить».";
    show(inTG
      ? stateScreen("Откройте «Желток» кнопкой под полем ввода", how) +
        '<div class="row-actions"><button type="button" class="btn btn-primary" id="cl">Закрыть окно</button></div>' +
        '<button type="button" class="btn-link" id="rv">Вернуться к проверке</button>'
      : stateScreen("Откройте приложение в Telegram",
        "Отправить документ в чат можно только из Telegram. Откройте бота «Желток» и нажмите кнопку «" + APP_BUTTON + "» под полем ввода.") +
        '<div class="row-actions"><button type="button" class="btn btn-secondary" id="rv">Вернуться к проверке</button></div>');
    document.getElementById("rv").addEventListener("click", function () { renderReview(); });
    var cl = document.getElementById("cl");
    if (cl) cl.addEventListener("click", function () { tg.close(); });
  }
  function renderLoadError() {
    back(null);
    show(stateScreen("Не удалось загрузить приложение", "Проверьте подключение к интернету и попробуйте ещё раз. Уже введённые ответы сохранены."));
    cta("Повторить", init);
  }

  // ------------------------------------------------------------ запуск
  function init() {
    hideCta();
    show('<p class="muted" style="padding-top:48px;text-align:center">Загружаем…</p>');
    fetch("catalog.json", { cache: "no-cache" })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(function (data) {
        S.docs = {}; S.order = []; S.cats = data.categories || [];
        data.docs.forEach(function (d) { S.docs[d.id] = d; S.order.push(d.id); });
        var m = /[?&]doc=([\w]+)/.exec(location.search);
        if (m && S.docs[m[1]]) renderIntro(S.docs[m[1]]); else renderHome();
      })
      .catch(renderLoadError);
  }

  if (inTG) {
    tg.ready(); tg.expand();
    tg.onEvent("themeChanged", applyTheme);
  } else if (window.matchMedia) {
    try { window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", applyTheme); } catch (e) {}
  }
  applyTheme();
  init();
})();
