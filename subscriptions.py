"""Private-token subscription endpoint; run behind an HTTPS reverse proxy."""
import argparse
import base64
from datetime import datetime, timezone
import html
from http.server import HTTPServer, BaseHTTPRequestHandler
import json
import re
import sqlite3
import time
from pathlib import Path
from urllib.parse import urlsplit
from events import EventService, EventError


def profile_title(name,expiry):
    date=datetime.fromtimestamp(expiry/1000,timezone.utc).strftime('%d.%m.%y')
    suffix='🥶ReVPN · '+date
    name=''.join(c for c in name if c.isprintable()).strip() or 'Друг'
    return name[:max(1,25-len(suffix))]+suffix


def subscription(db,token,now=None):
    now=time.time() if now is None else now
    db.row_factory=sqlite3.Row
    order=db.execute("SELECT * FROM orders WHERE sub_id=? AND status='active' AND product!='mtproto'",(token,)).fetchone()
    if order is None: return None
    rows=db.execute('SELECT * FROM allocations WHERE order_id=? ORDER BY node_id',(order['id'],)).fetchall()
    # Never expose a partially delivered bundle.
    if len(rows)!=len(json.loads(order['targets']) or ['regular']): return None
    title=profile_title(order['display_name'],order['expiry_ms'])
    links='\n'.join(r['link'] for r in rows) if order['expiry_ms']>now*1000 else ''
    headers={'profile-title':'base64:'+base64.b64encode(title.encode()).decode(),
             'profile-update-interval':'1',
             'subscription-userinfo':f"upload={sum(r['upload'] for r in rows)}; download={sum(r['download'] for r in rows)}; total={order['gb']*1024**3}; expire={order['expiry_ms']//1000}"}
    return base64.b64encode(links.encode()),headers,order



def public_page(path,cfg,support):
    from core import price,rubles
    from delivery import PRODUCTS
    from events import EVENT_CYCLE_SECONDS,event_clock,event_definition

    support_url='https://t.me/'+support.lstrip('@')
    bot=cfg.get('telegram',{}).get('bot_username') or 'ReversVPNbot'
    if not re.fullmatch(r'[A-Za-z0-9_]{5,32}',bot): bot='ReversVPNbot'

    def link(label,url,cls='button'):
        return '<a class="'+cls+'" href="'+html.escape(url,quote=True)+'">'+html.escape(label)+'</a>'

    def product_icon(key):
        icons={
            'regular': '<svg viewBox="0 0 64 64" aria-hidden="true"><path d="M32 5 52 12v15c0 15-8 25-20 32C20 52 12 42 12 27V12L32 5Z"/><path d="M24 31l6 6 11-13"/></svg>',
            'whitelist': '<svg viewBox="0 0 64 64" aria-hidden="true"><path d="M32 7v50M10 19l44 26M54 19 10 45"/><circle cx="32" cy="32" r="9"/></svg>',
            'bundle': '<svg viewBox="0 0 64 64" aria-hidden="true"><path d="m32 8 22 12-22 12L10 20 32 8Z"/><path d="m12 31 20 11 20-11M12 42l20 11 20-11"/></svg>',
            'mtproto': '<svg viewBox="0 0 64 64" aria-hidden="true"><path d="M8 29 55 9 45 55 30 40 21 49l2-15L8 29Z"/><path d="m23 34 22-15"/></svg>',
        }
        return icons.get(key,icons['regular'])

    def game_icon(game,cls='game-svg'):
        icons={
            'snow_catch': '<svg class="'+cls+'" viewBox="0 0 100 100" aria-hidden="true"><g fill="none" stroke="currentColor" stroke-width="5" stroke-linecap="round"><path d="M50 8v84M14 29l72 42M14 71l72-42"/><path d="m50 8-8 11m8-11 8 11M50 92l-8-11m8 11 8-11M14 29l14 1m-14-1 6 12M86 71l-14-1m14 1-6-12M14 71l14-1m-14 1 6-12M86 29l-14 1m14-1-6 12"/></g><circle cx="50" cy="50" r="7" fill="currentColor"/></svg>',
            'ice_break': '<svg class="'+cls+'" viewBox="0 0 100 100" aria-hidden="true"><defs><linearGradient id="iceg" x1="0" y1="0" x2="1" y2="1"><stop stop-color="#dff8ff"/><stop offset=".48" stop-color="#78cfff"/><stop offset="1" stop-color="#3a78d7"/></linearGradient></defs><path d="M50 5 85 25 78 76 50 96 22 76 15 25Z" fill="url(#iceg)" stroke="#dff7ff" stroke-width="3"/><path d="M50 5 39 41 15 25M50 5l12 36 23-16M39 41l11 55 12-55M22 76l17-35h23l16 35" fill="none" stroke="rgba(255,255,255,.62)" stroke-width="2"/></svg>',
            'reaction': '<svg class="'+cls+'" viewBox="0 0 100 100" aria-hidden="true"><circle cx="50" cy="50" r="34" fill="none" stroke="currentColor" stroke-width="5"/><circle cx="50" cy="50" r="12" fill="currentColor"/><path d="M50 3v15M50 82v15M3 50h15M82 50h15M17 17l11 11M72 72l11 11M83 17 72 28M28 72 17 83" stroke="currentColor" stroke-width="5" stroke-linecap="round"/></svg>',
            'tap_rush': '<svg class="'+cls+'" viewBox="0 0 100 100" aria-hidden="true"><path d="M57 7 25 53h24l-6 40 32-49H52Z" fill="currentColor"/><path d="M50 10a40 40 0 1 0 37 25" fill="none" stroke="currentColor" stroke-width="5" stroke-linecap="round"/></svg>',
        }
        return icons.get(game,icons['tap_rush'])

    privacy=path=='/privacy'
    title='Политика конфиденциальности' if privacy else 'ReVPN — подключайся проще'

    if privacy:
        content='<div class="brandbar"><span class="brandmark">R</span><strong>ReVPN</strong></div><section class="privacy-card"><span class="eyebrow">ReVPN · редакция от 30.09.2026</span><h1>Политика конфиденциальности</h1>\n<p>Эта страница описывает обработку данных в боте ReVPN, его Mini App и сервисе VPN/MTProto. По вопросам обработки данных отвечает команда ReVPN через поддержку ниже.</p>\n<h2>Какие данные обрабатываются</h2><p>Telegram ID, отображаемое имя, выбранный тариф и оператор, состояние диалога с ботом; параметры, суммы, статусы и идентификаторы заказов и счетов. Для предоставления доступа хранятся ключи VPN/прокси, ссылки подписок, срок действия, лимиты и счётчики переданного трафика.</p>\n<p>При создании управляемого бота хранятся ID владельца, ID и username бота, его токен для управления и информация о выдаче пробного доступа. Не передавай ссылки подписок и токены посторонним.</p>\n<h2>Зачем нужны данные</h2><p>Для выдачи и восстановления доступа, проверки оплаты, управления подписками и зеркалами, предотвращения повторной выдачи бонуса, обработки обращений и устранения сбоев.</p>\n<h2>Кому передаются данные</h2><p>Telegram обеспечивает сообщения и работу Mini App. Платёжный сервис Lolzteam Market получает данные для создания и проверки счёта, включая Telegram ID, сумму и идентификатор заказа. Панель VPN получает данные ключа, лимиты и срок действия. Инфраструктура хостинга обрабатывает соединения. У этих сторон есть собственные условия обработки данных. Бот не запрашивает реквизиты банковской карты.</p>\n<h2>Сайт и Mini App</h2><p>Mini App показывает каталог и ивенты. Для ивентов Telegram initData отправляется на наш сервер только для проверки подписи Telegram и привязки награды к аккаунту. Хранятся Telegram ID, счёт и прогресс мини-игр, накопленные/активированные секунды VPN, бонусный рублёвый баланс и технические счётчики защиты от автокликеров. Cookies, рекламная аналитика и локальное хранилище не используются. Подключается официальный скрипт Telegram. Веб-сервер и инфраструктура могут обрабатывать IP-адрес, время запроса, адрес страницы и сведения браузера в технических журналах.</p>\n<h2>Срок хранения и удаление</h2><p>Автоматический срок удаления заказов и аккаунтов в текущей версии не установлен: сведения сохраняются до обработки запроса на удаление или очистки оператором. Для запроса копии, исправления или удаления своих данных напиши в поддержку с того же Telegram-аккаунта. Поддержка уточнит объём удаления, последствия для действующей подписки и применимые ограничения. Резервные копии и журналы могут сохраняться отдельно.</p>\n<h2>Защита и ограничения</h2><p>Административные действия доступны ограниченному списку Telegram ID. Сайт работает через HTTPS при корректной настройке сервера. Мы не обещаем абсолютной анонимности или полного отсутствия технических журналов: их состав зависит от настроек VPN, прокси и хостинга.</p>\n<h2>Контакты и изменения</h2><p>Актуальная редакция публикуется на этой странице. Обращения по персональным данным:</p>'
        content+=link(support,support_url)+link('Вернуться в ReVPN','/app','plain')+'</section>'
    else:
        now_clock=event_clock()
        preview_times=(time.time(),now_clock['next_at']+1,now_clock['next_at']+EVENT_CYCLE_SECONDS+1)
        preview_html=[]
        for idx,ts in enumerate(preview_times):
            pc=event_clock(ts); pe=event_definition(pc['event_id'])
            status=('LIVE' if idx==0 and now_clock['active'] else ('СЛЕДУЮЩИЙ' if idx<=1 else 'СКОРО'))
            cls=' live' if idx==0 and now_clock['active'] else ''
            preview_html.append(
                '<div class="event-preview'+cls+'" data-event-preview="'+str(pc['event_id'])+'">'
                '<div class="preview-icon accent-'+str(pe['accent'])+'">'+game_icon(pe['game'],'preview-svg')+'</div>'
                '<div class="preview-copy"><span>'+status+' · '+html.escape(pe['reward']['label'])+'</span><strong>'+html.escape(pe['title'])+'</strong></div>'
                '</div>'
            )

        product_cards=[]
        for key,label in PRODUCTS.items():
            cost=rubles(price(cfg['pricing'],720,0,key)) if cfg.get('pricing') else '—'
            tag='Популярный' if key=='regular' else ('Telegram' if key=='mtproto' else 'VPN')
            product_cards.append(
                '<article class="plan-card plan-'+key+(' featured' if key=='regular' else '')+'">'
                '<div class="plan-top"><div class="plan-icon">'+product_icon(key)+'</div><span class="plan-tag">'+tag+'</span></div>'
                '<h3>'+html.escape(label)+'</h3>'
                '<div class="plan-price"><strong>'+cost+' ₽</strong><span>/ 30 дней</span></div>'
                '<p>'+('Отдельный ключ на срок подписки.' if key=='mtproto' else 'Срок и трафик выберешь перед оплатой в боте.')+'</p>'
                +link('Выбрать тариф','https://t.me/'+bot+'?start=app_'+key,'plan-action')+
                '</article>'
            )

        content='''<div id="app-loader" class="app-loader" aria-live="polite">
  <div class="loader-stage">
    <div class="loader-logo" aria-hidden="true">
      <span class="loader-cube cube-a"></span><span class="loader-cube cube-b"></span><span class="loader-cube cube-c"></span>
      <span class="loader-core">R</span>
    </div>
    <div class="loader-brand">ReVPN</div>
    <div class="loader-caption">Подготавливаем защищённое подключение</div>
    <div class="loader-track"><span id="loader-fill"></span><i></i></div>
  </div>
</div>
<header class="app-header">
  <a class="brand" href="/app"><span class="brandmark">R</span><span><strong>ReVPN</strong><small>VPN · Telegram</small></span></a>
  <a class="header-link" href="https://t.me/'''+bot+'''?start=app_account">Мои подписки</a>
</header>
<section class="hero">
  <span class="eyebrow">БЫСТРО · ПРОСТО · В ОДНОМ МЕСТЕ</span>
  <h1>Твоё подключение.<br><span>Без лишнего шума.</span></h1>
  <p>VPN, Telegram-прокси, бонусы и живые ивенты прямо внутри Mini App.</p>
  <div class="hero-pills"><span><i></i> HTTPS Mini App</span><span>⚡ Мгновенная выдача</span><span>🧊 ReVPN</span></div>
</section>
<section class="plans-section">
  <div class="section-head"><div><span class="eyebrow">ТАРИФЫ</span><h2>Выбери свой режим</h2></div><p>Итог подтвердим в боте перед оплатой.</p></div>
  <div class="plans-grid">'''+''.join(product_cards)+'''</div>
</section>
<section class="events-section">
  <div class="section-head"><div><span class="eyebrow">EVENT HUB</span><h2>Доступные ивенты</h2></div><p>Один ивент идёт 1 час, затем 10 минут перерыв.</p></div>
  <div class="event-previews">'''+''.join(preview_html)+'''</div>
  <div id="event-card" class="event-card accent-0">
    <div class="event-aurora aurora-a"></div><div class="event-aurora aurora-b"></div>
    <div class="event-card-top">
      <div id="event-live" class="live-pill"><i></i><span>LIVE ИВЕНТ</span></div>
      <div class="event-time"><span>до смены</span><strong id="event-timer">—</strong></div>
    </div>
    <div class="event-showcase">
      <div id="event-orb" class="event-orb" style="--progress:0deg">
        <div class="orb-ring ring-one"></div><div class="orb-ring ring-two"></div>
        <div class="orb-inner"><div id="event-art" class="event-art"></div></div>
      </div>
      <div class="event-copy">
        <span id="event-number" class="event-number">ИВЕНТ #—</span>
        <h3 id="event-title">Загрузка ивента…</h3>
        <p id="event-desc">Каждый засчитанный тап = +1 секунда VPN.</p>
      </div>
    </div>
    <div class="event-stats">
      <div><span>VPN-баланс</span><strong id="event-balance">0 сек</strong></div>
      <div><span>Бонусы</span><strong id="event-rubles">0 ₽</strong></div>
      <div><span>Счёт</span><strong id="event-taps">0</strong></div>
      <div><span>Награда</span><strong id="event-earned">0</strong></div>
    </div>
    <div class="arena-label"><span id="arena-title">МИНИ-ИГРА</span><small id="arena-hint">Загрузка игрового режима…</small></div>
    <div id="event-arena" class="event-arena">
      <span class="arena-grid"></span>
      <div id="snow-layer" class="snow-layer" aria-hidden="true"></div>
      <div id="reaction-signal" class="reaction-signal" hidden><i></i><span>ЖДИ</span></div>
      <button id="event-tap" class="tap-button" type="button" disabled><span class="tap-spark">✦</span><span id="tap-label">Загрузка…</span></button>
    </div>
    <div id="event-challenge" class="challenge" hidden></div>
    <div class="event-actions">
      <button id="event-claim" class="claim-button" type="button" disabled>Активировать секунды</button>
      <a id="event-connect" class="connect-button" href="#" hidden>Подключить бонусный VPN <span>→</span></a>
    </div>
    <p id="event-note" class="event-note">Открой Mini App из Telegram, чтобы участвовать.</p>
  </div>
</section>
<section class="quick-section">
  <div class="quick-card">
    <div class="quick-icon">↗</div><div><span>Уже подключён?</span><strong>Открой свои подписки</strong></div>
    <a href="https://t.me/'''+bot+'''?start=app_account">Открыть</a>
  </div>
  <div class="quick-card">
    <div class="quick-icon">TG</div><div><span>Telegram</span><strong>Бесплатный MTProto</strong></div>
    <a href="https://t.me/'''+bot+'''?start=app_free">Подключить</a>
  </div>
</section>
<footer><span>ReVPN — подключайся проще</span><div><a href="'''+support_url+'''">Поддержка</a><a href="/privacy">Политика конфиденциальности</a></div></footer>'''

    css=r"""
:root{--bg:#05070b;--bg2:#08111d;--card:#0d1725;--card2:#111f32;--line:rgba(255,255,255,.075);--text:#f6f9ff;--muted:#8899b2;--ice:#94d8ff;--ice2:#5ab6ff;--green:#57e89d;--danger:#ff6574}
*{box-sizing:border-box}
html{background:var(--bg);scroll-behavior:smooth}
body{margin:0;min-height:100vh;background:radial-gradient(900px 480px at 50% -220px,rgba(66,143,255,.22),transparent 68%),linear-gradient(180deg,#05070b 0%,#07101c 48%,#05070b 100%);color:var(--tg-theme-text-color,var(--text));font:16px/1.55 Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;overflow-x:hidden}
body:before{content:"";position:fixed;inset:0;pointer-events:none;background-image:linear-gradient(rgba(255,255,255,.012) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.012) 1px,transparent 1px);background-size:36px 36px;mask-image:linear-gradient(to bottom,black,transparent 75%);z-index:-1}
a{color:inherit}
main{width:min(100%,820px);margin:auto;padding:0 18px 54px}
.app-header{width:min(100%,820px);margin:auto;padding:18px;display:flex;align-items:center;justify-content:space-between;gap:16px}
.brand{display:flex;align-items:center;gap:11px;text-decoration:none}
.brandmark{width:39px;height:39px;border-radius:13px;display:grid;place-items:center;background:linear-gradient(145deg,#b9e7ff,#5daff0);color:#06101b;font-weight:950;box-shadow:0 8px 24px rgba(63,158,235,.24),inset 0 1px 0 rgba(255,255,255,.55)}
.brand>span:last-child{display:flex;flex-direction:column;line-height:1.05}
.brand strong{font-size:18px;letter-spacing:-.02em}
.brand small{margin-top:4px;font-size:9px;letter-spacing:.16em;color:var(--muted)}
.header-link{font-size:13px;font-weight:760;color:#c8dcf3;text-decoration:none;padding:10px 13px;border:1px solid var(--line);border-radius:13px;background:rgba(255,255,255,.025)}
.hero{padding:34px 0 28px}
.eyebrow{font-size:10px;letter-spacing:.2em;font-weight:850;color:#76c6ff}
.hero h1{font-size:clamp(38px,9vw,68px);line-height:.98;letter-spacing:-.055em;margin:13px 0 18px;max-width:720px}
.hero h1 span{color:#7bcaff}
.hero>p{max-width:590px;margin:0;color:var(--muted);font-size:clamp(16px,3.4vw,20px)}
.hero-pills{display:flex;gap:8px;flex-wrap:wrap;margin-top:23px}
.hero-pills span{font-size:12px;color:#b7c8db;background:rgba(255,255,255,.035);border:1px solid var(--line);padding:9px 11px;border-radius:999px}
.hero-pills i{display:inline-block;width:7px;height:7px;border-radius:50%;background:var(--green);margin-right:7px;box-shadow:0 0 12px rgba(87,232,157,.7)}
section{margin-top:18px}
.section-head{display:flex;justify-content:space-between;gap:18px;align-items:end;margin:0 2px 14px}
.section-head h2{font-size:27px;line-height:1.08;letter-spacing:-.035em;margin:6px 0 0}
.section-head>p{max-width:285px;text-align:right;color:var(--muted);font-size:13px;margin:0}
.plans-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}
.plan-card{position:relative;overflow:hidden;background:linear-gradient(150deg,rgba(18,28,43,.96),rgba(8,13,21,.97));border:1px solid var(--line);border-radius:25px;padding:18px;min-height:240px;box-shadow:0 15px 40px rgba(0,0,0,.18)}
.plan-card:before{content:"";position:absolute;width:150px;height:150px;border-radius:50%;right:-75px;top:-80px;background:radial-gradient(circle,rgba(89,178,255,.18),transparent 68%);pointer-events:none}
.plan-card.featured{border-color:rgba(104,197,255,.36);box-shadow:0 18px 50px rgba(25,116,190,.14)}
.plan-top{display:flex;justify-content:space-between;gap:10px;align-items:start}
.plan-icon{width:48px;height:48px;border-radius:16px;display:grid;place-items:center;background:linear-gradient(145deg,rgba(145,218,255,.18),rgba(62,139,215,.08));border:1px solid rgba(145,218,255,.17);animation:iconFloat 4.5s ease-in-out infinite}
.plan-icon svg{width:28px;height:28px;fill:none;stroke:#9bdbff;stroke-width:3.2;stroke-linecap:round;stroke-linejoin:round}
.plan-tag{font-size:9px;letter-spacing:.1em;font-weight:850;text-transform:uppercase;color:#8ed2ff;border:1px solid rgba(118,198,255,.16);background:rgba(75,154,220,.08);padding:6px 8px;border-radius:999px}
.plan-card h3{font-size:18px;margin:18px 0 8px;line-height:1.15}
.plan-price{display:flex;align-items:baseline;gap:7px}
.plan-price strong{font-size:27px;letter-spacing:-.04em}
.plan-price span{font-size:11px;color:var(--muted)}
.plan-card p{font-size:12px;color:var(--muted);min-height:38px;margin:9px 0 16px}
.plan-action{display:block;text-decoration:none;text-align:center;padding:11px;border-radius:14px;background:rgba(255,255,255,.065);border:1px solid rgba(255,255,255,.045);font-size:13px;font-weight:780;transition:.2s transform,.2s background}
.featured .plan-action{background:linear-gradient(135deg,#9adaff,#5cb8f8);color:#07111a}
.plan-action:active{transform:scale(.98)}
.event-previews{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:9px;overflow:auto;padding-bottom:3px;scrollbar-width:none}
.event-previews::-webkit-scrollbar{display:none}
.event-preview{min-width:0;padding:12px;border-radius:18px;background:rgba(255,255,255,.028);border:1px solid var(--line);display:flex;gap:10px;align-items:center}
.event-preview.live{border-color:rgba(98,202,255,.34);background:linear-gradient(135deg,rgba(80,173,246,.09),rgba(255,255,255,.025))}
.preview-icon{width:40px;height:40px;flex:0 0 40px;border-radius:14px;display:grid;place-items:center;font-size:19px;background:linear-gradient(145deg,rgba(122,202,255,.16),rgba(38,90,150,.11));animation:iconFloat 4s ease-in-out infinite}
.preview-copy{min-width:0;display:flex;flex-direction:column}
.preview-copy span{font-size:8px;letter-spacing:.12em;color:#74c7ff;font-weight:900}
.preview-copy strong{font-size:11px;line-height:1.2;margin-top:3px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.event-card{--accent:#67bfff;position:relative;overflow:hidden;margin-top:12px;background:linear-gradient(160deg,#101e31 0%,#0b1626 58%,#08111e 100%);border:1px solid rgba(123,199,255,.14);border-radius:30px;padding:20px;box-shadow:0 25px 70px rgba(0,0,0,.25)}
.event-card.accent-1{--accent:#7dd8ff}.event-card.accent-2{--accent:#9aa6ff}.event-card.accent-3{--accent:#64e0c6}.event-card.accent-4{--accent:#c68cff}.event-card.accent-5{--accent:#74a9ff}
.event-aurora{position:absolute;border-radius:50%;filter:blur(48px);opacity:.17;pointer-events:none}
.aurora-a{width:240px;height:240px;background:var(--accent);right:-110px;top:-90px;animation:auroraMove 8s ease-in-out infinite alternate}
.aurora-b{width:170px;height:170px;background:#315bff;left:-100px;bottom:-100px;animation:auroraMove 10s ease-in-out infinite alternate-reverse}
.event-card-top,.event-showcase,.event-stats,.arena-label{position:relative;z-index:2}
.event-card-top{display:flex;align-items:center;justify-content:space-between;gap:12px}
.live-pill{display:inline-flex;align-items:center;gap:8px;font-size:10px;letter-spacing:.13em;font-weight:900;color:#8ed7ff;background:rgba(83,178,247,.08);border:1px solid rgba(118,207,255,.16);padding:8px 10px;border-radius:999px}
.live-pill i{width:7px;height:7px;border-radius:50%;background:#6ad3ff;box-shadow:0 0 0 0 rgba(106,211,255,.55);animation:livePulse 1.8s infinite}
.live-pill.paused{color:#aab5c4;background:rgba(255,255,255,.04)}.live-pill.paused i{background:#8593a6;animation:none}
.event-time{display:flex;align-items:end;gap:8px}
.event-time span{font-size:9px;color:var(--muted);text-transform:uppercase;letter-spacing:.08em}
.event-time strong{font-size:20px;font-variant-numeric:tabular-nums;letter-spacing:-.03em}
.event-showcase{display:flex;align-items:center;gap:20px;margin:22px 0 18px}
.event-orb{--progress:0deg;position:relative;width:116px;height:116px;flex:0 0 116px;border-radius:50%;display:grid;place-items:center;background:conic-gradient(var(--accent) var(--progress),rgba(255,255,255,.06) 0);box-shadow:0 0 55px color-mix(in srgb,var(--accent) 20%,transparent);animation:orbFloat 4.2s ease-in-out infinite}
.event-orb:before{content:"";position:absolute;inset:5px;border-radius:50%;background:#0c1828}
.orb-inner{position:relative;z-index:3;width:78px;height:78px;border-radius:25px;display:grid;place-items:center;background:linear-gradient(145deg,color-mix(in srgb,var(--accent) 70%,#fff),color-mix(in srgb,var(--accent) 60%,#183452));color:#07111c;font-size:34px;box-shadow:inset 0 1px 0 rgba(255,255,255,.5),0 10px 35px color-mix(in srgb,var(--accent) 22%,transparent)}
.orb-ring{position:absolute;border:1px solid color-mix(in srgb,var(--accent) 24%,transparent);border-radius:50%;z-index:2}.ring-one{inset:-9px;animation:ringSpin 16s linear infinite}.ring-two{inset:-18px;border-style:dashed;animation:ringSpin 24s linear infinite reverse}
.event-copy{min-width:0}.event-number{font-size:9px;letter-spacing:.16em;color:var(--accent);font-weight:900}.event-copy h3{font-size:clamp(24px,5vw,34px);line-height:1.02;letter-spacing:-.045em;margin:7px 0 10px}.event-copy p{font-size:13px;color:#91a3bb;margin:0}
.event-stats{display:grid;grid-template-columns:repeat(3,1fr);gap:9px;margin:4px 0 18px}
.event-stats>div{padding:12px;border-radius:16px;background:rgba(255,255,255,.035);border:1px solid rgba(255,255,255,.04)}
.event-stats span{display:block;font-size:9px;color:var(--muted);text-transform:uppercase;letter-spacing:.08em}.event-stats strong{display:block;font-size:17px;margin-top:3px}
.arena-label{display:flex;justify-content:space-between;gap:10px;align-items:center;margin-bottom:8px}.arena-label span{font-size:9px;letter-spacing:.15em;font-weight:900;color:#9db3cb}.arena-label small{font-size:9px;color:#63758c}
.event-arena{position:relative;z-index:2;display:grid;grid-template-columns:repeat(3,1fr);grid-template-rows:repeat(3,68px);gap:7px;padding:10px;border-radius:21px;background:rgba(2,8,15,.34);border:1px solid rgba(255,255,255,.045);overflow:hidden}
.arena-grid{position:absolute;inset:0;background-image:linear-gradient(rgba(255,255,255,.025) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.025) 1px,transparent 1px);background-size:33.333% 33.333%;pointer-events:none}
.tap-button{position:relative;z-index:3;grid-column:2;grid-row:2;border:0;border-radius:18px;padding:8px;background:linear-gradient(145deg,color-mix(in srgb,var(--accent) 82%,#fff),color-mix(in srgb,var(--accent) 72%,#4778b2));color:#07111b;font:inherit;font-size:12px;font-weight:900;box-shadow:0 12px 30px color-mix(in srgb,var(--accent) 22%,transparent),inset 0 1px 0 rgba(255,255,255,.46);cursor:pointer;transition:.14s transform,.18s filter;overflow:hidden}
.tap-button:before{content:"";position:absolute;inset:-80% auto -80% -55%;width:38%;background:linear-gradient(90deg,transparent,rgba(255,255,255,.52),transparent);transform:rotate(20deg);animation:buttonShine 2.6s ease-in-out infinite}
.tap-button:active{transform:scale(.94)}.tap-button:disabled{opacity:.46;filter:grayscale(.25);cursor:default}
.tap-spark{display:block;font-size:17px;line-height:1}.tap-button span:last-child{display:block;max-width:100%;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.reward-pop{position:absolute;z-index:7;pointer-events:none;font-size:13px;font-weight:950;color:#a8e3ff;text-shadow:0 2px 12px #000;animation:rewardPop .75s ease-out forwards}
.challenge{position:relative;z-index:2;padding:14px;border-radius:17px;margin-top:10px;background:rgba(255,255,255,.045);border:1px solid rgba(255,255,255,.055)}.challenge p{font-size:12px;margin:0 0 10px;color:#b8c8da}.challenge-row{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}.challenge button{border:0;border-radius:13px;background:rgba(126,207,255,.12);color:#e9f7ff;font:inherit;font-size:20px;padding:10px}
.event-actions{position:relative;z-index:2;display:grid;grid-template-columns:1fr;gap:9px;margin-top:12px}
.claim-button,.connect-button{min-height:52px;border:0;border-radius:17px;font:inherit;font-size:13px;font-weight:850;display:flex;align-items:center;justify-content:center;text-decoration:none;cursor:pointer}
.claim-button{background:rgba(255,255,255,.07);color:#d5e3f2}.claim-button:not(:disabled){background:linear-gradient(135deg,#9bdcff,#65bcf8);color:#07111a;box-shadow:0 12px 30px rgba(72,165,235,.18)}.claim-button:disabled{opacity:.44}
.connect-button{background:linear-gradient(135deg,#76efba,#43d491);color:#06130d}.connect-button span{margin-left:8px;font-size:18px}
.event-note{position:relative;z-index:2;color:#6f8299;font-size:10px;text-align:center;margin:10px 0 0}
.quick-section{display:grid;grid-template-columns:1fr 1fr;gap:10px}.quick-card{display:grid;grid-template-columns:auto 1fr auto;align-items:center;gap:10px;padding:14px;border-radius:19px;border:1px solid var(--line);background:rgba(255,255,255,.026)}.quick-icon{width:38px;height:38px;border-radius:13px;display:grid;place-items:center;background:rgba(116,196,255,.1);color:#8dd5ff;font-weight:900;font-size:12px}.quick-card div:nth-child(2){display:flex;flex-direction:column;min-width:0}.quick-card span{font-size:9px;color:var(--muted)}.quick-card strong{font-size:11px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.quick-card a{font-size:10px;text-decoration:none;color:#8fd5ff;font-weight:800}
footer{display:flex;justify-content:space-between;gap:15px;align-items:center;padding:26px 3px 8px;color:#617289;font-size:10px}footer div{display:flex;gap:12px}footer a{text-decoration:none;color:#8799ae}
.privacy-card{margin-top:14px;background:rgba(255,255,255,.032);border:1px solid var(--line);border-radius:24px;padding:22px}.privacy-card h1{font-size:36px;line-height:1.05;letter-spacing:-.04em}.privacy-card h2{font-size:18px;margin-top:24px}.privacy-card p{color:#a4b2c4}.button{display:block;background:#94d8ff;color:#07111a;border-radius:14px;padding:13px;text-align:center;text-decoration:none;font-weight:800;margin-top:10px}.plain{display:block;padding:12px 0;color:#8fd5ff}
.app-loader{position:fixed;inset:0;z-index:9999;display:grid;place-items:center;background:radial-gradient(400px 260px at 50% 48%,rgba(64,154,229,.16),transparent 70%),#030508;transition:opacity .42s ease,visibility .42s ease}
.app-loader.hidden{opacity:0;visibility:hidden;pointer-events:none}
.loader-stage{width:min(78vw,340px);text-align:center}.loader-logo{position:relative;width:116px;height:116px;margin:0 auto 18px;display:grid;place-items:center}.loader-core{position:relative;z-index:4;width:60px;height:60px;border-radius:20px;display:grid;place-items:center;background:linear-gradient(145deg,#b5e5ff,#62b8f5);color:#07111a;font-size:29px;font-weight:950;box-shadow:0 18px 55px rgba(76,169,239,.25);animation:loaderCore 2.4s ease-in-out infinite}.loader-cube{position:absolute;width:28px;height:28px;border-radius:9px;background:linear-gradient(145deg,rgba(152,221,255,.9),rgba(64,143,214,.5));border:1px solid rgba(255,255,255,.25);box-shadow:0 8px 28px rgba(75,164,232,.2)}.cube-a{left:2px;top:18px;animation:cubeA 3.2s ease-in-out infinite}.cube-b{right:2px;top:14px;animation:cubeB 3s ease-in-out infinite}.cube-c{bottom:0;left:44px;animation:cubeC 3.4s ease-in-out infinite}.loader-brand{font-size:31px;font-weight:950;letter-spacing:-.05em}.loader-caption{font-size:11px;color:#71839a;margin:5px 0 19px}.loader-track{position:relative;height:7px;border-radius:999px;background:rgba(255,255,255,.07);overflow:hidden}.loader-track span{display:block;width:12%;height:100%;border-radius:inherit;background:linear-gradient(90deg,#55b5fb,#a6e1ff);box-shadow:0 0 18px rgba(84,182,251,.45);transition:width .3s ease}.loader-track i{position:absolute;inset:0;width:35%;background:linear-gradient(90deg,transparent,rgba(255,255,255,.32),transparent);animation:loadSweep 1.2s linear infinite}

.preview-svg{width:24px;height:24px;color:#a8ddff}.event-art{width:48px;height:48px;color:#06111d;display:grid;place-items:center}.event-art svg{width:46px;height:46px}
.event-stats{grid-template-columns:repeat(4,1fr)}
.event-stats>div:nth-child(2){background:linear-gradient(145deg,rgba(78,231,164,.08),rgba(255,255,255,.025));border-color:rgba(78,231,164,.11)}
.event-stats>div:nth-child(2) strong{color:#72efb1}
.event-arena{min-height:224px;grid-template-rows:repeat(3,68px)}
.snow-layer{position:absolute;inset:0;z-index:4;pointer-events:none;overflow:hidden}
.snowflake{--fall:1.25s;position:absolute;top:-58px;width:52px;height:52px;border:0;padding:0;background:transparent;color:#d9f6ff;filter:drop-shadow(0 6px 12px rgba(66,175,255,.38));pointer-events:auto;cursor:pointer;animation:snowFall var(--fall) linear forwards,snowSpin calc(var(--fall)*1.25) linear forwards}
.snowflake svg{width:100%;height:100%}.snowflake:after{content:"";position:absolute;inset:10px;border-radius:50%;background:rgba(176,231,255,.18);filter:blur(9px);z-index:-1}
.reaction-signal{position:absolute;z-index:5;inset:22px;display:grid;place-items:center;border-radius:28px;background:radial-gradient(circle at 50% 45%,rgba(68,151,235,.2),rgba(5,13,23,.75));border:1px solid rgba(124,203,255,.08)}
.reaction-signal[hidden]{display:none}.reaction-signal i{width:80px;height:80px;border-radius:50%;background:#24374b;box-shadow:0 0 0 14px rgba(255,255,255,.025),0 0 0 28px rgba(255,255,255,.015);transition:.16s}.reaction-signal span{position:absolute;margin-top:124px;font-size:10px;letter-spacing:.18em;color:#6f8299;font-weight:900}
.reaction-signal.ready i{background:#79e8b8;box-shadow:0 0 28px rgba(83,236,171,.72),0 0 0 14px rgba(83,236,171,.09),0 0 0 28px rgba(83,236,171,.045);animation:readyPulse .7s ease-in-out infinite alternate}
.reaction-signal.ready span{color:#85f0c0}.event-arena.mode-reaction .tap-button{position:absolute;inset:0;opacity:0;z-index:6;width:100%;height:100%}
.event-arena.mode-snow .tap-button{display:none}.event-arena.mode-snow{background:radial-gradient(250px 170px at 50% 0%,rgba(114,207,255,.11),transparent 75%),linear-gradient(180deg,rgba(9,22,38,.94),rgba(4,10,19,.98))}
.event-arena.mode-snow:after{content:"";position:absolute;inset:auto 0 0;height:34px;background:linear-gradient(to top,rgba(133,210,255,.13),transparent);pointer-events:none}
.event-arena.mode-ice .tap-button{grid-column:2;grid-row:2;background:transparent;box-shadow:none;overflow:visible}.event-arena.mode-ice .tap-button:before{display:none}.event-arena.mode-ice .tap-spark{display:none}.event-arena.mode-ice .tap-button span:last-child{font-size:0}
.event-arena.mode-ice .tap-button:after{content:"";position:absolute;width:74px;height:90px;left:50%;top:50%;transform:translate(-50%,-50%);clip-path:polygon(50% 0,88% 22%,78% 78%,50% 100%,22% 78%,12% 22%);background:linear-gradient(145deg,#e9fbff 0%,#8edbff 38%,#4a91e9 78%,#2b5ca5 100%);box-shadow:0 16px 34px rgba(55,143,225,.32),inset 0 0 0 2px rgba(255,255,255,.25)}
.event-arena.mode-ice.hit .tap-button:after{animation:crystalHit .18s ease}.event-arena.mode-ice:after{content:"";position:absolute;left:50%;top:50%;width:90px;height:105px;transform:translate(-50%,-50%);background:linear-gradient(62deg,transparent 49%,rgba(255,255,255,.65) 50%,transparent 51%),linear-gradient(-36deg,transparent 49%,rgba(255,255,255,.45) 50%,transparent 51%);opacity:calc(var(--cracks,0)*.16);pointer-events:none;z-index:4}
.reward-pop.ruble{color:#7ff2b9}.reward-pop.mixed{color:#d5c0ff}
@keyframes snowFall{0%{transform:translateY(0) scale(.8);opacity:0}10%{opacity:1}100%{transform:translateY(290px) scale(1.04);opacity:.94}}
@keyframes snowSpin{to{rotate:210deg}}@keyframes readyPulse{to{transform:scale(1.08)}}@keyframes crystalHit{50%{transform:translate(-50%,-50%) scale(.9) rotate(3deg)}}
@media(max-width:620px){.event-stats{grid-template-columns:repeat(2,1fr)}.event-arena{min-height:218px}}

@keyframes iconFloat{0%,100%{transform:translateY(0) rotate(0)}50%{transform:translateY(-4px) rotate(1deg)}}
@keyframes livePulse{0%{box-shadow:0 0 0 0 rgba(106,211,255,.55)}70%{box-shadow:0 0 0 8px rgba(106,211,255,0)}100%{box-shadow:0 0 0 0 rgba(106,211,255,0)}}
@keyframes orbFloat{0%,100%{transform:translateY(0)}50%{transform:translateY(-6px)}}
@keyframes ringSpin{to{transform:rotate(360deg)}}
@keyframes auroraMove{to{transform:translate(28px,24px) scale(1.12)}}
@keyframes buttonShine{0%,58%{left:-55%}100%{left:135%}}
@keyframes rewardPop{0%{opacity:0;transform:translate(-50%,8px) scale(.7)}20%{opacity:1}100%{opacity:0;transform:translate(-50%,-38px) scale(1.08)}}
@keyframes loaderCore{0%,100%{transform:translateY(0) scale(1)}50%{transform:translateY(-5px) scale(1.035)}}
@keyframes cubeA{0%,100%{transform:translate(0,0) rotate(0)}50%{transform:translate(-5px,12px) rotate(-14deg)}}
@keyframes cubeB{0%,100%{transform:translate(0,0) rotate(0)}50%{transform:translate(8px,10px) rotate(16deg)}}
@keyframes cubeC{0%,100%{transform:translate(0,0) rotate(0)}50%{transform:translate(0,8px) rotate(10deg)}}
@keyframes loadSweep{from{transform:translateX(-130%)}to{transform:translateX(390%)}}
@media(max-width:620px){main{padding-left:14px;padding-right:14px}.app-header{padding:14px}.hero{padding-top:22px}.plans-grid{gap:9px}.plan-card{padding:14px;border-radius:21px;min-height:224px}.plan-card h3{font-size:16px}.plan-price strong{font-size:23px}.event-previews{grid-template-columns:repeat(3,185px)}.event-showcase{gap:14px}.event-orb{width:94px;height:94px;flex-basis:94px}.orb-inner{width:64px;height:64px;border-radius:21px;font-size:28px}.event-stats strong{font-size:15px}.quick-section{grid-template-columns:1fr}.section-head{align-items:start}.section-head>p{display:none}}
@media(max-width:390px){.plans-grid{grid-template-columns:1fr}.plan-card{min-height:auto}.event-copy h3{font-size:23px}.event-showcase{align-items:flex-start}.event-stats{gap:6px}.event-stats>div{padding:10px 8px}.event-stats span{font-size:8px}}
@media(prefers-reduced-motion:reduce){*,*:before,*:after{animation-duration:.001ms!important;animation-iteration-count:1!important;scroll-behavior:auto!important}}
a:focus-visible,button:focus-visible{outline:3px solid #a8ddff;outline-offset:3px}
"""
    scripts='' if privacy else r"""<script src="https://telegram.org/js/telegram-web-app.js"></script><script>
const app=window.Telegram?.WebApp;
if(app){app.ready();app.expand();try{app.setHeaderColor('#05070b');app.setBackgroundColor('#05070b');}catch(_){}}
let evState=null,timerLeft=0,cooldownLeft=0,busy=false,loaderDone=false,snowTimer=null,reactionTimer=null;
const $=id=>document.getElementById(id);
const SVG={
 tap_rush:'<svg viewBox="0 0 100 100"><path d="M57 7 25 53h24l-6 40 32-49H52Z" fill="currentColor"/><path d="M50 10a40 40 0 1 0 37 25" fill="none" stroke="currentColor" stroke-width="5" stroke-linecap="round"/></svg>',
 snow_catch:'<svg viewBox="0 0 100 100"><g fill="none" stroke="currentColor" stroke-width="5" stroke-linecap="round"><path d="M50 8v84M14 29l72 42M14 71l72-42"/><path d="m50 8-8 11m8-11 8 11M50 92l-8-11m8 11 8-11M14 29l14 1m-14-1 6 12M86 71l-14-1m14 1-6-12M14 71l14-1m-14 1 6-12M86 29l-14 1m14-1-6 12"/></g><circle cx="50" cy="50" r="7" fill="currentColor"/></svg>',
 reaction:'<svg viewBox="0 0 100 100"><circle cx="50" cy="50" r="34" fill="none" stroke="currentColor" stroke-width="5"/><circle cx="50" cy="50" r="12" fill="currentColor"/><path d="M50 3v15M50 82v15M3 50h15M82 50h15M17 17l11 11M72 72l11 11M83 17 72 28M28 72 17 83" stroke="currentColor" stroke-width="5" stroke-linecap="round"/></svg>',
 ice_break:'<svg viewBox="0 0 100 100"><path d="M50 5 85 25 78 76 50 96 22 76 15 25Z" fill="currentColor" opacity=".92"/><path d="M50 5 39 41 15 25M50 5l12 36 23-16M39 41l11 55 12-55M22 76l17-35h23l16 35" fill="none" stroke="#fff" stroke-opacity=".58" stroke-width="2"/></svg>'
};
function fmt(sec){sec=Math.max(0,Math.floor(sec||0));const m=Math.floor(sec/60),s=sec%60;return m+':'+String(s).padStart(2,'0');}
function money(k){return (Number(k||0)/100).toFixed(2).replace(/\.00$/,'')+' ₽';}
function bootProgress(v){const el=$('loader-fill');if(el)el.style.width=Math.max(4,Math.min(100,v))+'%';}
function finishLoader(){if(loaderDone)return;loaderDone=true;bootProgress(100);setTimeout(()=>$('app-loader')?.classList.add('hidden'),260);}
async function api(path,extra={}){const r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({init_data:app?.initData||'',...extra})});let d={};try{d=await r.json();}catch(_){d={message:'Ошибка ответа сервера'};}if(!r.ok){const e=new Error(d.message||'Ошибка');e.data=d;throw e;}return d;}
function accent(v){const card=$('event-card');if(card)card.className=card.className.replace(/\baccent-\d\b/g,'').trim()+' accent-'+(Number(v||0)%6);}
function placeButton(slot){const b=$('event-tap');slot=Number(slot||0)%9;b.style.gridColumn=String(slot%3+1);b.style.gridRow=String(Math.floor(slot/3)+1);}
function renderChallenge(c,disabled=false){const box=$('event-challenge');box.innerHTML='';if(!c?.required){box.hidden=true;return;}box.hidden=false;const p=document.createElement('p');p.textContent=c.prompt;box.appendChild(p);const row=document.createElement('div');row.className='challenge-row';c.options.forEach(o=>{const b=document.createElement('button');b.type='button';b.textContent=o.label;b.disabled=disabled;b.onclick=()=>solveChallenge(o.id);row.appendChild(b);});box.appendChild(row);}
function rewardText(r){if(!r)return'';const bits=[];if(r.seconds)bits.push('+'+r.seconds+' сек');if(r.kopecks)bits.push('+'+money(r.kopecks));return bits.join(' · ');}
function rewardPop(r){const text=rewardText(r);if(!text)return;const arena=$('event-arena');const el=document.createElement('span');el.className='reward-pop '+(r.kopecks&&r.seconds?'mixed':r.kopecks?'ruble':'');el.textContent=text;el.style.left=(35+Math.random()*30)+'%';el.style.top=(38+Math.random()*20)+'%';arena.appendChild(el);setTimeout(()=>el.remove(),800);}
function snowSvg(variant){return '<svg viewBox="0 0 100 100" aria-hidden="true"><g fill="none" stroke="currentColor" stroke-width="'+(variant%2?4.2:5)+'" stroke-linecap="round"><path d="M50 7v86M13 28l74 44M13 72l74-44"/><path d="m50 7-9 13m9-13 9 13M50 93l-9-13m9 13 9-13M13 28l16 2m-16-2 7 13M87 72l-16-2m16 2-7-13M13 72l16-2m-16 2 7-13M87 28l-16 2m16-2-7 13"/></g><circle cx="50" cy="50" r="'+(variant%3+5)+'" fill="currentColor"/></svg>';}
function clearGame(){if(snowTimer){clearTimeout(snowTimer);snowTimer=null;}if(reactionTimer){clearTimeout(reactionTimer);reactionTimer=null;}$('snow-layer').innerHTML='';$('reaction-signal').hidden=true;$('reaction-signal').classList.remove('ready');}
function spawnSnow(){if(!evState||busy||evState.event.game!=='snow_catch'||!evState.clock.active||evState.user.challenge||evState.user.cooldown_ms>0)return;const layer=$('snow-layer');if(layer.querySelector('.snowflake'))return;const flake=document.createElement('button');flake.type='button';flake.className='snowflake';const seed=parseInt((evState.user.nonce||'0').slice(0,8),16)||1;const x=6+(seed%82);const ms=850+(seed%650);flake.style.left=x+'%';flake.style.setProperty('--fall',ms+'ms');flake.innerHTML=snowSvg(seed%5);flake.onclick=async e=>{e.stopPropagation();flake.remove();await playAction();};layer.appendChild(flake);snowTimer=setTimeout(()=>{flake.remove();snowTimer=null;spawnSnow();},ms+40);}
function setupReaction(){const box=$('reaction-signal');box.hidden=false;box.classList.remove('ready');box.querySelector('span').textContent='ЖДИ';const wait=Math.max(0,Number(evState?.user?.ready_in_ms||0));reactionTimer=setTimeout(()=>{reactionTimer=null;if(!evState||evState.event.game!=='reaction')return;box.classList.add('ready');box.querySelector('span').textContent='ЖМИ';$('event-tap').disabled=false;if(app?.HapticFeedback)app.HapticFeedback.impactOccurred('medium');},wait);}
function setupGame(){clearGame();const e=evState?.event,u=evState?.user,c=evState?.clock;if(!e)return;const arena=$('event-arena');arena.className='event-arena mode-'+(e.game==='snow_catch'?'snow':e.game==='reaction'?'reaction':e.game==='ice_break'?'ice':'tap');arena.style.setProperty('--cracks',String(Math.min(5,(u.event_taps||0)%6)));$('event-art').innerHTML=SVG[e.game]||SVG.tap_rush;const title={tap_rush:'ТАП-ГОНКА',snow_catch:'ПОЙМАЙ СНЕЖИНКУ',reaction:'РЕАКЦИЯ',ice_break:'РАЗБЕЙ КРИСТАЛЛ'}[e.game];const hint={tap_rush:'Лови движущуюся кнопку',snow_catch:'Снежинки падают быстро — нажимай прямо по ним',reaction:'Не нажимай раньше зелёной вспышки',ice_break:'Каждый точный удар раскалывает лёд'}[e.game];$('arena-title').textContent=title;$('arena-hint').textContent=hint;const tap=$('event-tap');tap.disabled=!c.active||u.cooldown_ms>0||!!u.challenge;$('tap-label').textContent=e.game==='reaction'?'ЖМИ ПО СИГНАЛУ':e.button;placeButton(u.slot);if(e.game==='snow_catch'){tap.disabled=true;spawnSnow();}else if(e.game==='reaction'){tap.disabled=true;setupReaction();}}
function render(d){evState=d;const c=d.clock,u=d.user,e=d.event;timerLeft=c.seconds_left||0;cooldownLeft=u.cooldown_ms||0;accent(e.accent);$('event-number').textContent='ИВЕНТ #'+String(c.event_no||'—').padStart(3,'0');$('event-title').textContent=c.active?e.title:'Перерыв между ивентами';$('event-desc').textContent=c.active?e.description:'Новый ивент уже готовится. Начнётся через '+fmt(timerLeft)+'.';$('event-balance').textContent=u.balance_seconds+' сек';$('event-rubles').textContent=money(u.bonus_kopecks);$('event-taps').textContent=u.event_taps;const earned=(u.event_reward_seconds?u.event_reward_seconds+' сек':'')+(u.event_reward_seconds&&u.event_reward_kopecks?' · ':'')+(u.event_reward_kopecks?money(u.event_reward_kopecks):'');$('event-earned').textContent=earned||'0';$('event-timer').textContent=fmt(timerLeft);const progress=c.active?(1-Math.min(3600,timerLeft)/3600):0;$('event-orb')?.style.setProperty('--progress',(progress*360)+'deg');const live=$('event-live');live.classList.toggle('paused',!c.active);live.querySelector('span').textContent=c.active?'LIVE · '+e.reward.label:'ПЕРЕРЫВ';const claim=$('event-claim');claim.disabled=u.balance_seconds<u.min_claim_seconds&&!(u.bonus?.syncing);claim.textContent=u.bonus?.syncing?'Повторить синхронизацию':('Активировать '+u.balance_seconds+' сек');const link=$('event-connect');if(u.bonus?.connect_url){link.href=u.bonus.connect_url;link.hidden=false;}else link.hidden=true;renderChallenge(u.challenge,cooldownLeft>0);$('event-note').textContent=u.cooldown_ms>0?'Защита от автокликера: пауза '+Math.ceil(u.cooldown_ms/1000)+' сек.':(u.bonus?.syncing?'Секунды сохранены, синхронизация VPN ещё выполняется.':'Бонусные ₽ автоматически уменьшают следующую оплату.');setupGame();}
async function loadEvent(){bootProgress(54);try{const d=await api('/api/events/state');bootProgress(82);render(d);finishLoader();}catch(e){$('event-title').textContent='Ивенты доступны в Telegram';$('event-desc').textContent=e.message||'Открой Mini App из Telegram, чтобы участвовать.';$('event-tap').disabled=true;$('event-note').textContent='Каталог доступен, награды привязываются только к Telegram-аккаунту.';finishLoader();}}
async function playAction(){if(busy||!evState)return;busy=true;$('event-tap').disabled=true;try{const d=await api('/api/events/play',{event_id:evState.clock.event_id,nonce:evState.user.nonce});if(d.accepted){rewardPop(d.reward);if(app?.HapticFeedback)app.HapticFeedback.impactOccurred('light');if(evState.event.game==='ice_break'){const a=$('event-arena');a.classList.remove('hit');void a.offsetWidth;a.classList.add('hit');}}render(d);}catch(e){$('event-note').textContent=e.message;if(e.data?.challenge){evState.user.challenge=e.data.challenge;renderChallenge(e.data.challenge);}else await loadEvent();}finally{busy=false;if(evState)setupGame();}}
$('event-tap')?.addEventListener('click',playAction);
async function solveChallenge(choice){if(!evState||busy)return;busy=true;try{render(await api('/api/events/challenge',{nonce:evState.user.nonce,choice}));if(app?.HapticFeedback)app.HapticFeedback.notificationOccurred('success');}catch(e){$('event-note').textContent=e.message;await loadEvent();}finally{busy=false;}}
$('event-claim')?.addEventListener('click',async()=>{if(busy)return;busy=true;$('event-claim').disabled=true;try{render(await api('/api/events/claim'));if(app?.HapticFeedback)app.HapticFeedback.notificationOccurred('success');}catch(e){$('event-note').textContent=e.message;await loadEvent();}finally{busy=false;}});
setInterval(()=>{if(timerLeft>0){timerLeft--;$('event-timer').textContent=fmt(timerLeft);}else if(evState)loadEvent();if(cooldownLeft>0){cooldownLeft=Math.max(0,cooldownLeft-1000);if(cooldownLeft===0&&evState)loadEvent();}},1000);
document.addEventListener('click',e=>{const a=e.target.closest('a');if(a&&a.href.startsWith('https://t.me/')&&app){e.preventDefault();app.openTelegramLink(a.href);setTimeout(()=>app.close(),120);}});
bootProgress(22);requestAnimationFrame(()=>bootProgress(38));loadEvent();
</script>"""
    return ('<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><meta name="theme-color" content="#05070b"><title>'+title+'</title><style>'+css+'</style></head><body><main>'+content+'</main>'+scripts+'</body></html>').encode()

def handler(db_path,public_base,support,cfg=None):
    cfg=cfg or {}
    event_service=None
    if cfg.get('telegram',{}).get('token'):
        try: event_service=EventService(db_path,cfg,Path(db_path).parent)
        except Exception: event_service=None
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args): pass # URLs are credentials; never log subscription tokens.
        def do_POST(self):
            path=urlsplit(self.path).path
            routes={'/api/events/state','/api/events/tap','/api/events/play','/api/events/challenge','/api/events/claim'}
            if path not in routes: return self.reply(404,b'Not found')
            if event_service is None: return self.json_reply(503,{'ok':False,'message':'Ивенты пока недоступны.'})
            try:
                length=int(self.headers.get('Content-Length','0'))
                if length<=0 or length>32768: return self.json_reply(413,{'ok':False,'message':'Слишком большой запрос.'})
                body=json.loads(self.rfile.read(length))
                init_data=body.get('init_data','')
                if path=='/api/events/state': data=event_service.state(init_data)
                elif path in ('/api/events/tap','/api/events/play'): data=event_service.play(init_data,body.get('event_id'),body.get('nonce',''))
                elif path=='/api/events/challenge': data=event_service.challenge(init_data,body.get('nonce',''),body.get('choice'))
                else: data=event_service.claim(init_data)
                return self.json_reply(200,data)
            except EventError as exc:
                return self.json_reply(exc.status,{'ok':False,'message':str(exc),**exc.payload})
            except (ValueError,TypeError,json.JSONDecodeError):
                return self.json_reply(400,{'ok':False,'message':'Некорректный запрос.'})
            except Exception:
                return self.json_reply(500,{'ok':False,'message':'Временная ошибка ивента.'})

        def json_reply(self,status,data):
            body=json.dumps(data,ensure_ascii=False,separators=(',',':')).encode()
            self.reply(status,body,{'Content-Type':'application/json; charset=utf-8',
                                    'Content-Security-Policy':"default-src 'none'; frame-ancestors 'none'; base-uri 'none'"})

        def do_GET(self):
            path=urlsplit(self.path).path
            if path in ('/','/app','/privacy'):
                headers={'Content-Type':'text/html; charset=utf-8'}
                if path!='/privacy':
                    headers['Content-Security-Policy']="default-src 'none'; script-src https://telegram.org 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; frame-ancestors https://web.telegram.org https://*.telegram.org; base-uri 'none'; form-action 'none'"
                return self.reply(200,public_page(path,cfg or {},support),headers)
            match=re.fullmatch(r'/(sub|connect)/([a-f0-9]{32})',path)
            if not match: return self.reply(404,b'Not found')
            try:
                with sqlite3.connect('file:'+str(db_path)+'?mode=ro',uri=True,timeout=5) as db:
                    result=subscription(db,match[2])
            except sqlite3.Error: return self.reply(503,b'Try later')
            if not result: return self.reply(404,b'Not found')
            body,headers,order=result
            if match[1]=='sub':
                headers['support-url']='https://t.me/'+support.lstrip('@')
                return self.reply(200,body,headers)
            url=public_base.rstrip('/')+'/sub/'+match[2]
            title=html.escape(profile_title(order['display_name'],order['expiry_ms']))
            body=f'''<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>ReVPN</title><style>body{{background:#081526;color:#eefaff;font:18px system-ui;max-width:520px;margin:12vh auto;padding:24px}}a{{display:block;background:#8ce8ff;color:#081526;padding:18px;border-radius:16px;text-align:center;text-decoration:none;font-weight:bold}}input{{width:100%;box-sizing:border-box;padding:14px;margin-top:16px;background:#142a41;color:white;border:0;border-radius:12px}}p{{line-height:1.6}}</style><h1>Очень холодно 🥶</h1><p>{title}</p><a href="{html.escape('happ://add/'+url,quote=True)}">Добавить подписку в Happ</a><p>Если Happ не открылся, скопируй ссылку ниже и добавь её через «+» → «Из буфера обмена».</p><input readonly aria-label="Ссылка подписки" value="{html.escape(url,quote=True)}"><p>Подписка добавляет все оплаченные профили.</p></html>'''.encode()
            self.reply(200,body,{'Content-Type':'text/html; charset=utf-8'})
        def reply(self,status,body,headers=None):
            self.send_response(status)
            fields={'Content-Type':'text/plain; charset=utf-8','Content-Length':str(len(body)),'Cache-Control':'no-store','Referrer-Policy':'no-referrer','X-Content-Type-Options':'nosniff','Content-Security-Policy':"default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'"}
            fields.update(headers or {})
            for k,v in fields.items(): self.send_header(k,v)
            self.end_headers(); self.wfile.write(body)
    return Handler

if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('--config',default='/etc/revpn-shop/config.json'); p.add_argument('--data',default='/var/lib/revpn-shop'); a=p.parse_args()
    cfg=json.loads(Path(a.config).read_text()); sub=cfg['subscription']
    server=HTTPServer(('127.0.0.1',sub.get('local_port',8090)),handler(Path(a.data)/'shop.sqlite3',sub['public_base'],cfg['telegram']['support'],cfg))
    server.serve_forever()
