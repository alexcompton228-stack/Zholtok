"""Прогон Mini App в Chromium: путь пользователя, ошибки JS, скриншоты 360/390/430 (светлая и тёмная тема).
Режим Telegram имитируется заглушкой telegram-web-app.js; отправленные боту данные сохраняются в
screens/sent_payload.json — их потом проверяет test_bot_flow.py.
Запуск: python test_miniapp_ui.py
"""
import functools
import http.server
import json
import os
import threading

from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(HERE, "miniapp")
OUT = os.path.join(HERE, "screens")
os.makedirs(OUT, exist_ok=True)

TG_STUB = """
window.__sent = null; window.__main = {visible:false, text:'', active:true};
window.Telegram = {WebApp: {
  initData: 'test', colorScheme: (new URLSearchParams(location.search).get('theme')||'light'),
  ready(){}, expand(){}, onEvent(){}, setHeaderColor(){}, setBackgroundColor(){}, setBottomBarColor(){},
  HapticFeedback: {selectionChanged(){}, notificationOccurred(){}},
  MainButton: {_cb:null, setParams(p){ Object.assign(window.__main, {visible: p.is_visible, text: p.text, active: p.is_active!==false}); },
               show(){window.__main.visible=true}, hide(){window.__main.visible=false},
               enable(){window.__main.active=true}, disable(){window.__main.active=false}, onClick(cb){this._cb=cb}},
  BackButton: {_cb:null, show(){}, hide(){}, onClick(cb){this._cb=cb}},
  sendData(d){ window.__sent = d; }
}};
"""
NO_TG = "window.Telegram = undefined;"


def serve():
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=APP)
    handler.log_message = lambda *a: None
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def main():
    srv = serve()
    base = f"http://127.0.0.1:{srv.server_address[1]}/index.html"
    errors = []
    with sync_playwright() as p:
        br = p.chromium.launch(executable_path="/opt/pw-browsers/chromium")

        def page(width, theme, tg):
            ctx = br.new_context(viewport={"width": width, "height": 800}, device_scale_factor=2,
                                 color_scheme="dark" if theme == "dark" else "light")
            pg = ctx.new_page()
            pg.on("pageerror", lambda e: errors.append(f"{width}/{theme}: {e}"))
            pg.route("**/telegram-web-app.js", lambda r: r.fulfill(body=TG_STUB if tg else NO_TG,
                                                                   content_type="application/javascript"))
            pg.route("https://fonts.googleapis.com/**", lambda r: r.fulfill(body="", content_type="text/css"))
            pg.goto(f"{base}?theme={theme}")
            pg.wait_for_selector("h1")
            pg.wait_for_timeout(300)
            return pg

        def shot(pg, path):
            pg.wait_for_timeout(300)            # дождаться окончания анимации появления
            pg.screenshot(path=path, full_page=True)

        def no_hscroll(pg, tag):
            w = pg.evaluate("[document.documentElement.scrollWidth, window.innerWidth]")
            assert w[0] <= w[1], f"горизонтальная прокрутка на {tag}: {w}"

        # ---------- полный путь в браузере (без Telegram) + скриншоты
        for width in (360, 390, 430):
            for theme in ("light", "dark"):
                pg = page(width, theme, tg=False)
                tag = f"{width}-{theme}"
                no_hscroll(pg, tag)
                shot(pg, f"{OUT}/1-home-{tag}.png")
                pg.click("[data-doc=vozvrat_brak]")
                pg.wait_for_selector("#consent")
                assert pg.is_disabled("#cta"), "«Начать» активна без согласия"
                pg.check("#consent")
                if width == 390:
                    shot(pg, f"{OUT}/2-intro-{tag}.png")
                pg.click("#cta")
                # вопрос 1: пустой ответ -> ошибка
                pg.wait_for_selector("#f")
                pg.click("#cta")
                assert pg.inner_text("#err"), "нет сообщения об ошибке"
                if width == 390:
                    shot(pg, f"{OUT}/3-error-{tag}.png")
                pg.fill("#f", "Смартфон Xiaomi Redmi Note 13")
                pg.click("#cta")
                pg.fill("#f", "24 990")
                pg.click("#cta")
                pg.fill("#f", "2026-09-20")
                pg.click("#cta")
                pg.click("text=В магазине")
                pg.wait_for_timeout(250)
                if width == 390:
                    shot(pg, f"{OUT}/4-choice-{tag}.png")
                # назад сохраняет ответ
                pg.click("#back")
                pg.wait_for_selector("[aria-checked=true]")
                assert pg.inner_text("[aria-checked=true]").strip() == "В магазине", "назад потерял ответ"
                pg.click("#cta")            # «Далее» с сохранённым выбором
                pg.click("text=Да")
                pg.wait_for_timeout(250)
                pg.fill("#f", "перестал заряжаться через неделю")
                pg.click("#cta")
                pg.click("text=Кассовый чек"); pg.wait_for_timeout(250)
                pg.click("text=Вернуть деньги"); pg.wait_for_timeout(250)
                pg.click("text=На карту, с которой платили"); pg.wait_for_timeout(250)
                for v in ["ООО «Техномаркет»", "123000, г. Москва, ул. Тверская, д. 5"]:
                    pg.fill("#f", v); pg.click("#cta")
                pg.click("#skip")           # ИНН — необязательный
                for v in ["Иванов Иван Иванович", "123456, г. Москва, ул. Садовая, д. 1, кв. 10", "+7 900 123-45-67"]:
                    pg.fill("#f", v); pg.click("#cta")
                pg.fill("#f", "ivanov@mail.ru"); pg.click("#cta")
                pg.wait_for_selector("text=Проверьте сведения")
                assert "Не указано" in pg.inner_text("main"), "пропущенное поле не помечено"
                no_hscroll(pg, tag + " review")
                if width == 390:
                    shot(pg, f"{OUT}/5-review-{tag}.png")
                # изменить сумму -> сразу обратно к проверке, остальное на месте
                pg.click("[data-key=price]")
                assert pg.input_value("#f") == "24990"
                pg.fill("#f", "21990"); pg.click("#cta")
                pg.wait_for_selector("text=Проверьте сведения")
                assert "21 990" in pg.inner_text("main")
                # сменить требование: вопрос «куда вернуть» уходит из сводки
                pg.click("[data-key=demand]"); pg.click("text=Заменить на такой же"); pg.wait_for_timeout(250)
                assert "Куда вернуть" not in pg.inner_text("main")
                pg.click("#cta")
                pg.wait_for_selector("text=Откройте приложение из Telegram")
                if width == 390:
                    shot(pg, f"{OUT}/6-not-in-telegram-{tag}.png")
                # черновик на главном
                pg.goto(f"{base}?theme={theme}"); pg.wait_for_selector("#resume")
                if width == 390:
                    shot(pg, f"{OUT}/7-draft-{tag}.png")
                pg.context.close()

        # ---------- режим Telegram: блокировка и отправка боту
        pg = page(390, "light", tg=True)
        pg.click("[data-doc=otkaz_strahovka]")
        pg.check("#consent")
        pg.evaluate("Telegram.WebApp.MainButton._cb()")
        pg.click("text=Полис на моё имя, договор со страховой"); pg.wait_for_timeout(250)
        pg.fill("#f", "НЖ-123456789"); pg.evaluate("Telegram.WebApp.MainButton._cb()")
        pg.fill("#f", "2026-01-10"); pg.evaluate("Telegram.WebApp.MainButton._cb()")      # давно -> будет блок
        for v in ["48000", "ООО СК «Надёжная Жизнь»", "123000, г. Москва, ул. Страховая, д. 1",
                  "АО «Т-Банк», БИК 044525974, счёт 40817810000000000000"]:
            pg.fill("#f", v); pg.evaluate("Telegram.WebApp.MainButton._cb()")
        for v in ["Иванов Иван Иванович", "123456, г. Москва, ул. Садовая, д. 1, кв. 10", "+7 900 123-45-67", "ivanov@mail.ru"]:
            pg.fill("#f", v); pg.evaluate("Telegram.WebApp.MainButton._cb()")
        pg.wait_for_selector("text=Этот документ сейчас не поможет")
        assert not pg.evaluate("window.__main.visible"), "при блоке главная кнопка видна"
        shot(pg, f"{OUT}/8-blocked-390-light.png")
        import datetime as dt
        recent = (dt.date.today() - dt.timedelta(days=3)).isoformat()
        pg.click("[data-key=policy_date]"); pg.fill("#f", recent); pg.evaluate("Telegram.WebApp.MainButton._cb()")
        pg.wait_for_selector("text=Проверьте сведения")
        assert pg.evaluate("window.__main.visible && window.__main.text") == "Подготовить документ"
        pg.evaluate("Telegram.WebApp.MainButton._cb()")
        sent = pg.evaluate("window.__sent")
        assert sent, "sendData не вызван"
        shot(pg, f"{OUT}/9-sending-390-light.png")
        with open(os.path.join(OUT, "sent_payload.json"), "w", encoding="utf-8") as f:
            f.write(sent)
        pg.goto(f"{base}?theme=light"); pg.wait_for_selector("#reopen")
        shot(pg, f"{OUT}/10-sent-card-390-light.png")
        pl = json.loads(sent)
        print(f"Отправлено боту: doc={pl['doc']}, ответов={len(pl['a'])}, размер={len(sent.encode())} байт")
        br.close()
    srv.shutdown()
    if errors:
        print("ОШИБКИ JS:", *errors, sep="\n  ")
        raise SystemExit(1)
    print("Mini App: путь, ошибки ввода, назад, изменение, черновик, блокировка, отправка — ok; скриншоты в screens/")


if __name__ == "__main__":
    main()
