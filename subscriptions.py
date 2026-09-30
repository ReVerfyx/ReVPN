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
import threading
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
        labels={'regular':'Обычный VPN','whitelist':'Белые списки','bundle':'VPN + белые списки','mtproto':'Telegram-прокси'}
        descriptions={'regular':'Для повседневных задач','whitelist':'5 профилей подключения','bundle':'Всё в одной подписке','mtproto':'Отдельный ключ MTProto'}
        for key,label in PRODUCTS.items():
            cost=rubles(price(cfg['pricing'],720,0,key)) if cfg.get('pricing') else '—'
            selected=False
            product_cards.append(
                '<button type="button" class="plan-card'+(' selected' if selected else '')+'" role="radio" aria-checked="'+str(selected).lower()+'" data-plan="'+key+'" data-label="'+html.escape(labels.get(key,label),quote=True)+'" data-url="https://t.me/'+bot+'?start=app_'+key+'">'
                '<span class="plan-top"><span class="plan-icon">'+product_icon(key)+'</span><span class="selection-dot"></span></span>'
                '<span class="plan-name">'+html.escape(labels.get(key,label))+'</span>'
                '<span class="plan-price"><strong>'+cost+' ₽</strong><span>/ 30 дней</span></span>'
                '<span class="plan-description">'+html.escape(descriptions.get(key,''))+'</span></button>'
            )

        content='''<div id="app-loader" class="app-loader hidden" aria-live="polite">
  <div class="loader-stage">
    <div class="loader-logo" aria-hidden="true">
      <span class="loader-cube cube-a"></span><span class="loader-cube cube-b"></span><span class="loader-cube cube-c"></span>
      <span class="loader-core">R</span>
    </div>
    <div class="loader-brand">ReVPN</div>
    <div class="loader-caption">Твой доступ к сети</div>
    <div class="loader-track"><span id="loader-fill"></span><i></i></div>
  </div>
</div>
<header class="app-header">
  <a class="brand" href="/app" aria-label="ReVPN — главная"><span class="brandmark">R</span><strong>Re<span>VPN</span></strong></a>
  <button class="header-link" type="button" id="app-close">Закрыть <span aria-hidden="true">↗</span></button>
</header>
<section id="screen-plans" class="app-screen" aria-labelledby="plans-heading">
  <div class="screen-heading"><span class="eyebrow">ТВОЙ ДОСТУП К СЕТИ</span><h1 id="plans-heading">Выбери тариф</h1><p>Первичная настройка · выбери подходящий вариант</p></div>
  <div class="hero-note"><span class="hero-note-icon">✦</span><div><strong>Один шаг до подключения</strong><p>Срок, трафик и итоговую цену выберешь в боте перед оплатой.</p></div></div>
  <div class="plans-grid" role="radiogroup" aria-label="Тарифы">'''+''.join(product_cards)+'''</div>
  <a id="plan-continue" class="primary-action" aria-disabled="true" href="#">Продолжить <span aria-hidden="true">→</span></a>
  <p id="plan-selection" class="selection-note" aria-live="polite">Выбери тариф или продолжи без него</p>
  <button type="button" class="bonus-teaser" id="skip-setup"><span class="gift-icon">✧</span><span><strong>Продолжить без тарифа</strong><small>Сразу перейти к мини-играм</small></span><span aria-hidden="true">→</span></button>
</section>
<section id="screen-events" class="events-section app-screen" hidden aria-labelledby="events-heading">
  <div class="screen-heading"><span class="eyebrow">БОНУСЫ ЗА ИГРУ</span><h1 id="events-heading">Ивенты</h1><p>Час игры · 10 минут на перерыв</p></div>
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
      <div id="snow-layer" class="snow-layer"></div>
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
<section id="screen-account" class="app-screen" hidden aria-labelledby="account-heading"><div class="screen-heading"><span class="eyebrow">ВСЁ ПОД РУКОЙ</span><h1 id="account-heading">Подключение</h1><p>Твои подписки и помощь с настройкой.</p></div><div id="usage-panel" class="usage-panel"><h2>Трафик VPN</h2><p id="usage-status" role="status">Загрузка статистики…</p><div id="usage-list"></div><button id="usage-refresh" type="button" class="header-link">Обновить</button></div><div class="quick-section">
  <div class="quick-card">
    <div class="quick-icon">↗</div><div><span>Уже подключён?</span><strong>Открой свои подписки</strong></div>
    <a href="https://t.me/'''+bot+'''?start=app_account">Открыть</a>
  </div>
  <div class="quick-card">
    <div class="quick-icon">TG</div><div><span>Telegram</span><strong>Бесплатный MTProto</strong></div>
    <a href="https://t.me/'''+bot+'''?start=app_free">Подключить</a>
  </div>
</div>
<footer><span>ReVPN</span><div><a href="'''+support_url+'''">Поддержка</a><a href="/privacy">Политика конфиденциальности</a></div></footer></section>
<nav class="bottom-nav" hidden aria-label="Разделы приложения">
<button type="button" data-screen="plans" aria-current="page"><span aria-hidden="true">◇</span>Тарифы</button>
<button type="button" data-screen="events"><span aria-hidden="true">✧</span>Ивенты</button>
<button type="button" data-screen="account"><span aria-hidden="true">◎</span>Подключение</button>
</nav>'''

    css=r"""
:root{color-scheme:dark;--bg:#080b10;--text:#f4f7fc;--muted:#9aa5b7;--line:#252d38;--accent:#8bcfff}
*{box-sizing:border-box}html{background:var(--bg)}body{margin:0;background:radial-gradient(ellipse at 50% 0,#102031 0,transparent 430px),var(--bg);color:var(--text);font:15px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif}button,a{-webkit-tap-highlight-color:transparent}button{font:inherit;cursor:pointer}a{color:inherit;text-decoration:none}button{color:var(--text)}[hidden]{display:none!important}main{max-width:520px;margin:auto;padding:0 18px calc(100px + env(safe-area-inset-bottom,0px))}h1,h2,h3,strong{color:var(--text)}
.app-header{height:64px;display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid #ffffff0d}.brand{display:flex;gap:9px;align-items:center}.brand strong{font-size:25px;letter-spacing:-1px;font-style:italic}.brand strong span{color:#8bcfff}.brandmark{display:grid;place-items:center;width:31px;height:35px;background:linear-gradient(145deg,#ceefff,#64b8f4);clip-path:polygon(50% 0,95% 24%,95% 76%,50% 100%,5% 76%,5% 24%);color:#102235;font-weight:900}.header-link{background:none;border:0;color:#a8b3c3;padding:12px 0 12px 12px;font-size:13px}.header-link span{margin-left:5px}.screen-heading{text-align:center;margin:28px 0 22px}.eyebrow{font-size:9px;letter-spacing:.19em;font-weight:700;color:#88b5d7}.screen-heading h1{font-size:29px;letter-spacing:-1px;line-height:1.2;margin:7px 0 8px}.screen-heading p{font-size:13px;color:var(--muted);margin:0}.hero-note{display:flex;gap:12px;align-items:center;padding:14px;border:1px solid #35526a;border-radius:16px;background:linear-gradient(110deg,#122334,#101820);margin-bottom:20px}.hero-note-icon{color:#9cdbff;font-size:28px}.hero-note strong{font-size:13px}.hero-note p{color:#b0bac9;font-size:12px;margin:3px 0 0;line-height:1.5}
#screen-plans .screen-heading{margin:24px 0 18px}#screen-plans .screen-heading .eyebrow,#screen-plans .screen-heading p{display:none}.primary-action[aria-disabled="true"]{background:#253243;color:#a7b6c8;box-shadow:none;cursor:default}.usage-panel{margin:0 0 20px}.usage-panel h2{font-size:20px}.usage-panel p{color:#acb9ca;font-size:12px}.usage-card{padding:16px;background:#132131;border:1px solid #33485e;border-radius:16px;margin:12px 0}.usage-card h3{font-size:15px;margin:0 0 14px}.usage-stats{display:grid;grid-template-columns:1fr 1fr;gap:12px}.usage-stats span{display:block;color:#aebdd0;font-size:11px}.usage-stats strong{display:block;font-size:22px;margin-top:4px}.plans-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.plan-card{display:flex;flex-direction:column;align-items:stretch;text-align:left;min-width:0;border:1px solid #2b3039;background:linear-gradient(135deg,#191e27,#10141b);border-radius:17px;padding:14px;transition:border-color .18s,background .18s}.plan-card.selected{border-color:#8bcfff;background:linear-gradient(135deg,#182c40,#101d2b);box-shadow:0 0 0 1px #8bcfff22}.plan-top{display:flex;justify-content:space-between;align-items:center;margin-bottom:8px}.plan-icon{width:25px;height:25px}.plan-icon svg{width:25px;height:25px;fill:none;stroke:#9dd8ff;stroke-width:3;stroke-linecap:round;stroke-linejoin:round}.selection-dot{width:16px;height:16px;border:1px solid #525b68;border-radius:50%}.selected .selection-dot{border:4px solid #91d4ff;background:#16283a}.plan-name{font-size:13px;font-weight:650;min-height:32px;line-height:1.35}.plan-price{display:flex;gap:5px;align-items:baseline;flex-wrap:wrap;margin-top:5px}.plan-price strong{font-size:26px;letter-spacing:-.8px;line-height:1.2}.plan-price>span{font-size:10px;color:#adb7c7;white-space:nowrap}.plan-description{margin-top:9px;border-top:1px solid #ffffff0d;padding-top:8px;font-size:11px;color:#aeb8c7;line-height:1.4}.primary-action{display:flex;align-items:center;justify-content:center;gap:16px;background:linear-gradient(100deg,#b1e3ff,#70bef6);color:#092033;border:0;border-radius:14px;min-height:52px;font-weight:750;font-size:16px;margin-top:18px;box-shadow:0 7px 22px #63b9ff16}.primary-action span{font-size:23px;line-height:1}.selection-note{font-size:11px;text-align:center;color:var(--muted);margin:9px 0 18px}.bonus-teaser{width:100%;display:flex;text-align:left;gap:12px;align-items:center;border:1px solid #254937;border-radius:15px;background:linear-gradient(110deg,#112a20,#111b19);padding:14px;color:#b1f0ce}.gift-icon{font-size:32px;line-height:1}.bonus-teaser strong{color:#c4f6da;font-size:13px}.bonus-teaser small{display:block;font-size:11px;color:#94b9a6;margin-top:2px}.bonus-teaser>span:last-child{margin-left:auto;font-size:20px}
.bottom-nav{position:fixed;z-index:20;bottom:0;left:50%;transform:translateX(-50%);width:min(100%,520px);display:grid;grid-template-columns:repeat(3,1fr);border-top:1px solid #29313c;background:#0d121bf5;backdrop-filter:blur(20px);padding:8px 12px calc(8px + env(safe-area-inset-bottom,0px))}.bottom-nav button{border:0;background:transparent;color:#9ca8bb;font-size:11px;min-height:48px;border-radius:12px;display:flex;flex-direction:column;align-items:center;gap:2px}.bottom-nav button span{font-size:24px;line-height:25px}.bottom-nav [aria-current]{color:#a2dcff;background:#8bcfff0d}
.event-previews{display:flex;gap:8px;overflow:auto;scrollbar-width:none;margin-bottom:16px}.event-preview{display:flex;align-items:center;gap:8px;flex:0 0 190px;min-width:0;border:1px solid var(--line);border-radius:12px;padding:10px;background:#111720}.event-preview.live{border-color:#496a84}.preview-icon{display:flex;color:#a8ddff}.preview-svg{width:24px;height:24px}.preview-copy{min-width:0}.preview-copy span{display:block;font-size:8px;color:#a0c9e8;font-weight:700}.preview-copy strong{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:11px;margin-top:3px}.event-card{--accent:#8bcfff;border:1px solid #303e50;background:linear-gradient(145deg,#142233,#0d141f);border-radius:20px;padding:16px;position:relative;overflow:hidden}.event-card.accent-1{--accent:#7dd8ff}.event-card.accent-2{--accent:#acb6ff}.event-card.accent-3{--accent:#79e1c6}.event-card.accent-4{--accent:#d4a8ff}.event-card.accent-5{--accent:#91b8ff}.event-aurora,.orb-ring{display:none}.event-card-top{display:flex;align-items:center;justify-content:space-between;gap:8px}.live-pill{display:flex;align-items:center;gap:6px;border-radius:7px;background:#8bcfff0b;padding:6px;color:#b2dfff;font-size:9px;font-weight:700}.live-pill i{width:5px;height:5px;background:#8bd5ff;border-radius:50%}.live-pill.paused{color:#a7b3c3}.event-time{display:flex;align-items:center;gap:5px}.event-time span{font-size:9px;color:var(--muted)}.event-time strong{font-size:17px;font-variant-numeric:tabular-nums}.event-showcase{display:flex;align-items:center;gap:14px;margin:19px 0}.event-orb{width:58px;height:58px;flex:0 0 58px;padding:3px;background:conic-gradient(var(--accent) var(--progress),#ffffff12 0);border-radius:18px}.orb-inner{height:100%;display:grid;place-items:center;background:#162436;border-radius:15px}.event-art,.event-art svg{height:33px;width:33px;color:var(--accent)}.event-number{font-size:9px;letter-spacing:.09em;color:var(--accent)}.event-copy{min-width:0}.event-copy h3{font-size:18px;line-height:1.2;margin:5px 0 6px;letter-spacing:-.4px}.event-copy p{font-size:11px;color:#acb8c9;line-height:1.45;margin:0}.event-stats{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:5px;margin-bottom:16px}.event-stats>div{border:1px solid #ffffff09;border-radius:10px;padding:9px 6px;background:#ffffff03;min-width:0}.event-stats span{display:block;font-size:8px;color:#a5b1c3}.event-stats strong{font-size:12px;display:block;margin-top:3px;overflow-wrap:anywhere}.event-stats>div:nth-child(2) strong{color:#91eac0}.arena-label{display:flex;align-items:center;justify-content:space-between;gap:8px;margin:8px 0}.arena-label>span{font-size:9px;letter-spacing:.06em;color:#b6c3d5;font-weight:650}.arena-label small{font-size:9px;color:#a0aec1;max-width:65%;text-align:right}.event-arena{position:relative;display:grid;grid-template-columns:repeat(3,minmax(0,1fr));grid-template-rows:repeat(3,65px);gap:8px;padding:10px;border:1px solid #ffffff0c;border-radius:15px;overflow:hidden;background:#09121d}.arena-grid{position:absolute;inset:0;background-image:linear-gradient(#ffffff03 1px,transparent 1px),linear-gradient(90deg,#ffffff03 1px,transparent 1px);background-size:33.33% 33.33%;pointer-events:none}.tap-button{position:relative;z-index:3;border:0;border-radius:14px;background:linear-gradient(135deg,#badeff,var(--accent));color:#0b2037;font-size:10px;font-weight:750;padding:5px;min-width:0;overflow-wrap:anywhere;touch-action:manipulation}.tap-spark{display:block;font-size:22px}.tap-button:active{transform:scale(.94)}.tap-button:disabled{opacity:.5}.event-actions{display:grid;gap:8px;margin-top:12px}.claim-button,.connect-button{min-height:46px;border:0;border-radius:12px;display:flex;align-items:center;justify-content:center;padding:10px;text-align:center;font:700 13px system-ui}.claim-button{background:#9ed9ff;color:#0a2539}.claim-button:disabled{background:#253245;color:#a0b0c5;cursor:default}.connect-button{background:#9ae6c1;color:#112d20}.event-note{font-size:11px;color:#a5b2c3;line-height:1.5;text-align:center;margin:12px 0 0}.challenge{padding:12px;border:1px solid #42617c;border-radius:12px;margin-top:12px}.challenge p{font-size:12px;color:#c0d1e4;margin:0 0 10px}.challenge-row{display:flex;gap:8px}.challenge button{flex:1;border:1px solid #465871;background:#263448;border-radius:9px;min-height:44px;color:#fff;font-size:20px}.reward-pop{position:absolute;z-index:7;pointer-events:none;color:#c4edff;font-weight:800;font-size:17px;animation:rewardPop .75s ease-out forwards}.quick-section{display:grid;gap:12px}.quick-card{display:grid;grid-template-columns:auto 1fr;gap:5px 12px;align-items:center;padding:18px;border:1px solid var(--line);border-radius:16px;background:#121923}.quick-icon{grid-row:span 2;width:36px;height:36px;background:#203348;color:#a8dbff;border-radius:11px;display:grid;place-items:center;font-size:14px}.quick-card span{display:block;font-size:11px;color:var(--muted)}.quick-card strong{font-size:14px}.quick-card a{color:#9dd8ff;font-size:13px;padding-top:6px;grid-column:2;min-height:32px}footer{margin-top:26px;text-align:center;color:#9ba9bc;font-size:12px}footer>span{display:none}footer div{display:grid;gap:16px}footer a{padding:5px}.privacy-card{margin-top:25px}.privacy-card h1{font-size:28px;overflow-wrap:anywhere;line-height:1.25}.privacy-card h2{font-size:19px;margin-top:28px}.privacy-card p{color:#b2becf;font-size:14px}.brandbar{display:flex;gap:10px;align-items:center;margin-top:25px}.button{display:block;background:#9bd8ff;color:#102b3c;padding:12px;border-radius:10px;text-align:center}.plain{display:block;padding:15px 0;color:#9bd8ff}.app-loader{position:fixed;inset:0;z-index:100;background:#080b10;display:grid;place-items:center;transition:opacity .25s,visibility .25s}.app-loader.hidden{opacity:0;visibility:hidden;pointer-events:none}.loader-stage{width:210px;text-align:center}.loader-logo{display:none}.loader-brand{font-size:44px;font-style:italic;letter-spacing:-2px;font-weight:800;color:#abdeff}.loader-caption{color:#a1b2c5;font-size:12px;margin:8px 0 28px}.loader-track{height:4px;background:#253344;border-radius:5px;overflow:hidden}.loader-track span{display:block;height:100%;width:0;background:#8bcfff;transition:width .25s}.loader-track i{display:none}
@keyframes rewardPop{to{transform:translateY(-55px);opacity:0}}@media(max-width:350px){main{padding-left:12px;padding-right:12px}.plan-card{padding:12px}.plan-price strong{font-size:23px}.plan-name{font-size:12px}.event-card{padding:12px}.event-time span{display:none}}@media(prefers-reduced-motion:reduce){*,*:before,*:after{animation-duration:.001ms!important;animation-iteration-count:1!important;transition:none!important;scroll-behavior:auto!important}.snowflake{animation:snowFall var(--fall) linear forwards!important}}a:focus-visible,button:focus-visible{outline:3px solid #c4eaff;outline-offset:3px}

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



"""
    scripts='' if privacy else r"""<script src="https://telegram.org/js/telegram-web-app.js"></script><script>
document.getElementById('app-loader')?.classList.remove('hidden');
const app=window.Telegram?.WebApp;
if(app){app.ready();app.expand();try{app.setHeaderColor('#080b10');app.setBackgroundColor('#080b10');}catch(_){}}
const launchAt=performance.now();
let setupComplete=false,selectedPlan=null,usageBusy=false;
let currentScreen='plans',loadingEvent=false;
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
function finishLoader(){if(loaderDone)return;const left=5000-(performance.now()-launchAt);if(left>0){setTimeout(finishLoader,left);return;}loaderDone=true;bootProgress(100);$('app-loader')?.classList.add('hidden');}
async function api(path,extra={}){const controller=new AbortController();const timeout=setTimeout(()=>controller.abort(),12000);let r;try{r=await fetch(path,{signal:controller.signal,method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({init_data:app?.initData||'',...extra})});}finally{clearTimeout(timeout);}let d={};try{d=await r.json();}catch(_){d={message:'Ошибка ответа сервера'};}if(!r.ok){const e=new Error(d.message||'Ошибка');e.data=d;throw e;}return d;}
function accent(v){const card=$('event-card');if(card)card.className=card.className.replace(/\baccent-\d\b/g,'').trim()+' accent-'+(Number(v||0)%6);}
function placeButton(slot){const b=$('event-tap');slot=Number(slot||0)%9;b.style.gridColumn=String(slot%3+1);b.style.gridRow=String(Math.floor(slot/3)+1);}
function renderChallenge(c,disabled=false){const box=$('event-challenge');box.innerHTML='';if(!c?.required){box.hidden=true;return;}box.hidden=false;const p=document.createElement('p');p.textContent=c.prompt;box.appendChild(p);const row=document.createElement('div');row.className='challenge-row';c.options.forEach(o=>{const b=document.createElement('button');b.type='button';b.textContent=o.label;b.disabled=disabled;b.onclick=()=>solveChallenge(o.id);row.appendChild(b);});box.appendChild(row);}
function rewardText(r){if(!r)return'';const bits=[];if(r.seconds)bits.push('+'+r.seconds+' сек');if(r.kopecks)bits.push('+'+money(r.kopecks));return bits.join(' · ');}
function rewardPop(r){const text=rewardText(r);if(!text)return;const arena=$('event-arena');const el=document.createElement('span');el.className='reward-pop '+(r.kopecks&&r.seconds?'mixed':r.kopecks?'ruble':'');el.textContent=text;el.style.left=(35+Math.random()*30)+'%';el.style.top=(38+Math.random()*20)+'%';arena.appendChild(el);setTimeout(()=>el.remove(),800);}
function snowSvg(variant){return '<svg viewBox="0 0 100 100" aria-hidden="true"><g fill="none" stroke="currentColor" stroke-width="'+(variant%2?4.2:5)+'" stroke-linecap="round"><path d="M50 7v86M13 28l74 44M13 72l74-44"/><path d="m50 7-9 13m9-13 9 13M50 93l-9-13m9 13 9-13M13 28l16 2m-16-2 7 13M87 72l-16-2m16 2-7-13M13 72l16-2m-16 2 7-13M87 28l-16 2m16-2-7 13"/></g><circle cx="50" cy="50" r="'+(variant%3+5)+'" fill="currentColor"/></svg>';}
function clearGame(){if(snowTimer){clearTimeout(snowTimer);snowTimer=null;}if(reactionTimer){clearTimeout(reactionTimer);reactionTimer=null;}$('snow-layer').innerHTML='';$('reaction-signal').hidden=true;$('reaction-signal').classList.remove('ready');}
function spawnSnow(){if(currentScreen!=='events'||document.hidden||!evState||busy||evState.event.game!=='snow_catch'||!evState.clock.active||evState.user.challenge||evState.user.cooldown_ms>0)return;const layer=$('snow-layer');if(layer.querySelector('.snowflake'))return;const flake=document.createElement('button');flake.type='button';flake.setAttribute('aria-label','Поймать снежинку');flake.className='snowflake';const seed=parseInt((evState.user.nonce||'0').slice(0,8),16)||1;const x=6+(seed%82);const ms=850+(seed%650);flake.style.left=x+'%';flake.style.setProperty('--fall',ms+'ms');flake.innerHTML=snowSvg(seed%5);flake.onclick=async e=>{e.stopPropagation();flake.remove();await playAction();};layer.appendChild(flake);snowTimer=setTimeout(()=>{flake.remove();snowTimer=null;spawnSnow();},ms+40);}
function setupReaction(){const box=$('reaction-signal');box.hidden=false;box.classList.remove('ready');box.querySelector('span').textContent='ЖДИ';const wait=Math.max(0,Number(evState?.user?.ready_in_ms||0));reactionTimer=setTimeout(()=>{reactionTimer=null;if(!evState||evState.event.game!=='reaction')return;box.classList.add('ready');box.querySelector('span').textContent='ЖМИ';$('event-tap').disabled=false;if(app?.HapticFeedback)app.HapticFeedback.impactOccurred('medium');},wait);}
function setupGame(){clearGame();if(currentScreen!=='events'||document.hidden)return;const e=evState?.event,u=evState?.user,c=evState?.clock;if(!e)return;const arena=$('event-arena');arena.className='event-arena mode-'+(e.game==='snow_catch'?'snow':e.game==='reaction'?'reaction':e.game==='ice_break'?'ice':'tap');arena.style.setProperty('--cracks',String(Math.min(5,(u.event_taps||0)%6)));$('event-art').innerHTML=SVG[e.game]||SVG.tap_rush;const title={tap_rush:'ТАП-ГОНКА',snow_catch:'ПОЙМАЙ СНЕЖИНКУ',reaction:'РЕАКЦИЯ',ice_break:'РАЗБЕЙ КРИСТАЛЛ'}[e.game];const hint={tap_rush:'Лови движущуюся кнопку',snow_catch:'Снежинки падают быстро — нажимай прямо по ним',reaction:'Не нажимай раньше зелёной вспышки',ice_break:'Каждый точный удар раскалывает лёд'}[e.game];$('arena-title').textContent=title;$('arena-hint').textContent=hint;const tap=$('event-tap');tap.disabled=!c.active||u.cooldown_ms>0||!!u.challenge;$('tap-label').textContent=e.game==='reaction'?'ЖМИ ПО СИГНАЛУ':e.button;placeButton(u.slot);if(e.game==='snow_catch'){tap.disabled=true;spawnSnow();}else if(e.game==='reaction'){tap.disabled=true;setupReaction();}}
function render(d){evState=d;const c=d.clock,u=d.user,e=d.event;timerLeft=c.seconds_left||0;cooldownLeft=u.cooldown_ms||0;accent(e.accent);$('event-number').textContent='ИВЕНТ #'+String(c.event_no||'—').padStart(3,'0');$('event-title').textContent=c.active?e.title:'Перерыв между ивентами';$('event-desc').textContent=c.active?e.description:'Новый ивент уже готовится. Начнётся через '+fmt(timerLeft)+'.';$('event-balance').textContent=u.balance_seconds+' сек';$('event-rubles').textContent=money(u.bonus_kopecks);$('event-taps').textContent=u.event_taps;const earned=(u.event_reward_seconds?u.event_reward_seconds+' сек':'')+(u.event_reward_seconds&&u.event_reward_kopecks?' · ':'')+(u.event_reward_kopecks?money(u.event_reward_kopecks):'');$('event-earned').textContent=earned||'0';$('event-timer').textContent=fmt(timerLeft);const progress=c.active?(1-Math.min(3600,timerLeft)/3600):0;$('event-orb')?.style.setProperty('--progress',(progress*360)+'deg');const live=$('event-live');live.classList.toggle('paused',!c.active);live.querySelector('span').textContent=c.active?'LIVE · '+e.reward.label:'ПЕРЕРЫВ';const claim=$('event-claim');claim.disabled=u.balance_seconds<u.min_claim_seconds&&!(u.bonus?.syncing);claim.textContent=u.bonus?.syncing?'Повторить синхронизацию':('Активировать '+u.balance_seconds+' сек');const link=$('event-connect');if(u.bonus?.connect_url){link.href=u.bonus.connect_url;link.hidden=false;}else link.hidden=true;renderChallenge(u.challenge,cooldownLeft>0);$('event-note').textContent=u.cooldown_ms>0?'Защита от автокликера: пауза '+Math.ceil(u.cooldown_ms/1000)+' сек.':(u.bonus?.syncing?'Секунды сохранены, синхронизация VPN ещё выполняется.':'Бонусные ₽ автоматически уменьшают следующую оплату.');setupGame();}
async function loadEvent(){if(loadingEvent)return;loadingEvent=true;try{const d=await api('/api/events/state');bootProgress(82);render(d);finishLoader();}catch(e){$('event-title').textContent='Ивенты доступны в Telegram';$('event-desc').textContent=e.message||'Открой Mini App из Telegram, чтобы участвовать.';$('event-tap').disabled=true;$('event-note').textContent='Каталог доступен, награды привязываются только к Telegram-аккаунту.';finishLoader();}finally{loadingEvent=false;}}
async function playAction(){if(currentScreen!=='events'||document.hidden||busy||!evState)return;busy=true;$('event-tap').disabled=true;try{const d=await api('/api/events/play',{event_id:evState.clock.event_id,nonce:evState.user.nonce});if(d.accepted){rewardPop(d.reward);if(app?.HapticFeedback)app.HapticFeedback.impactOccurred('light');if(evState.event.game==='ice_break'){const a=$('event-arena');a.classList.remove('hit');void a.offsetWidth;a.classList.add('hit');}}render(d);}catch(e){$('event-note').textContent=e.message;if(e.data?.challenge){evState.user.challenge=e.data.challenge;renderChallenge(e.data.challenge);}else await loadEvent();}finally{busy=false;if(evState)setupGame();}}
$('event-tap')?.addEventListener('click',playAction);
async function solveChallenge(choice){if(!evState||busy)return;busy=true;try{render(await api('/api/events/challenge',{nonce:evState.user.nonce,choice}));if(app?.HapticFeedback)app.HapticFeedback.notificationOccurred('success');}catch(e){$('event-note').textContent=e.message;await loadEvent();}finally{busy=false;}}
$('event-claim')?.addEventListener('click',async()=>{if(busy)return;busy=true;$('event-claim').disabled=true;try{render(await api('/api/events/claim'));if(app?.HapticFeedback)app.HapticFeedback.notificationOccurred('success');}catch(e){$('event-note').textContent=e.message;await loadEvent();}finally{busy=false;}});
setInterval(()=>{if(timerLeft>0){timerLeft--;$('event-timer').textContent=fmt(timerLeft);}else if(evState&&currentScreen==='events'&&!document.hidden&&!busy)loadEvent();if(cooldownLeft>0){cooldownLeft=Math.max(0,cooldownLeft-1000);if(cooldownLeft===0&&evState&&currentScreen==='events'&&!busy)loadEvent();}},1000);
document.addEventListener('click',e=>{const a=e.target.closest('a');if(a&&a.href.startsWith('https://t.me/')&&app){e.preventDefault();app.openTelegramLink(a.href);setTimeout(()=>app.close(),120);}});
function showScreen(name){
 if(!setupComplete&&name!=='plans')return;
 if(!['plans','events','account'].includes(name))return;
 currentScreen=name;
 document.querySelectorAll('.app-screen').forEach(el=>el.hidden=el.id!=='screen-'+name);
 document.querySelectorAll('.bottom-nav button').forEach(el=>{if(el.dataset.screen===name)el.setAttribute('aria-current','page');else el.removeAttribute('aria-current');});
 clearGame();window.scrollTo(0,0);
 if(name==='events')loadEvent();
 if(name==='account')loadUsage();
 if(app?.BackButton){if(name==='plans')app.BackButton.hide();else app.BackButton.show();}
}
document.querySelectorAll('[data-screen]').forEach(el=>el.addEventListener('click',()=>showScreen(el.dataset.screen)));
app?.BackButton?.onClick(()=>showScreen('plans'));
$('app-close').onclick=()=>{if(app?.initData)app.close();else history.back();};
const plans=[...document.querySelectorAll('[data-plan]')];
function selectPlan(el){selectedPlan=el;$('plan-continue').removeAttribute('aria-disabled');plans.forEach(p=>{const selected=p===el;p.classList.toggle('selected',selected);p.setAttribute('aria-checked',String(selected));p.tabIndex=selected?0:-1;});$('plan-continue').href=el.dataset.url;$('plan-selection').textContent='Выбран: '+el.dataset.label;}
plans.forEach((el,i)=>{el.tabIndex=i===0?0:-1;el.onclick=()=>selectPlan(el);el.onkeydown=e=>{const delta={ArrowRight:1,ArrowDown:1,ArrowLeft:-1,ArrowUp:-1}[e.key];if(delta){e.preventDefault();const next=plans[(i+delta+plans.length)%plans.length];selectPlan(next);next.focus();}};});
document.addEventListener('visibilitychange',()=>{if(document.hidden)clearGame();else if(currentScreen==='events')loadEvent();});
function completeSetup(){setupComplete=true;document.querySelector('.bottom-nav').hidden=false;}
$('skip-setup').onclick=()=>{plans.forEach(p=>{p.classList.remove('selected');p.setAttribute('aria-checked','false');});selectedPlan=null;$('plan-continue').href='#';$('plan-continue').setAttribute('aria-disabled','true');$('plan-selection').textContent='Тариф не выбран';completeSetup();showScreen('events');};
$('plan-continue').addEventListener('click',e=>{if(!selectedPlan){e.preventDefault();e.stopPropagation();return;}completeSetup();});
function bytes(value){if(value===null)return 'Нет данных';return (value/1073741824).toLocaleString('ru-RU',{maximumFractionDigits:2})+' ГБ';}
async function loadUsage(){
 if(usageBusy)return;usageBusy=true;$('usage-refresh').disabled=true;$('usage-status').textContent='Обновляем статистику…';
 try{const data=await api('/api/account/usage');$('usage-list').replaceChildren();
 for(const sub of data.subscriptions){const card=document.createElement('article');card.className='usage-card';
 const title=document.createElement('h3');title.textContent=sub.label;card.appendChild(title);
 const stats=document.createElement('div');stats.className='usage-stats';
 for(const [label,value] of [['Израсходовано',bytes(sub.used_bytes)],['Осталось',sub.unlimited?'Безлимит':bytes(sub.remaining_bytes)]]){const box=document.createElement('div'),small=document.createElement('span'),strong=document.createElement('strong');small.textContent=label;strong.textContent=value;box.append(small,strong);stats.appendChild(box);}card.appendChild(stats);
 const info=document.createElement('p');info.textContent='Действует до '+new Date(sub.expires_at*1000).toLocaleDateString('ru-RU');card.appendChild(info);
 const updated=document.createElement('p');updated.textContent=sub.updated_at?(sub.stale?'Данные устарели. ':'')+'Обновлено: '+new Date(sub.updated_at*1000).toLocaleString('ru-RU'):'Счётчики ещё не получены от VPN-сервера.';card.appendChild(updated);$('usage-list').appendChild(card);}
 $('usage-status').textContent=data.subscriptions.length?'Счётчики обновляются примерно раз в минуту.':'Действующих VPN-подписок пока нет. Трафик MTProto здесь не учитывается.';
 }catch(e){$('usage-status').textContent=app?.initData?'Не удалось загрузить статистику. Попробуй обновить.':'Открой Mini App из Telegram, чтобы увидеть свой трафик.';}finally{usageBusy=false;$('usage-refresh').disabled=false;}
}
$('usage-refresh').onclick=loadUsage;
const launchProgress=setInterval(()=>{bootProgress(Math.min(99,(performance.now()-launchAt)/50));if(loaderDone)clearInterval(launchProgress);},50);
finishLoader();

</script>"""
    return ('<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><meta name="theme-color" content="#080b10"><title>'+title+'</title><style>'+css+'</style></head><body><main>'+content+'</main>'+scripts+'</body></html>').encode()

def sync_traffic(delivery, now=None):
    """Refresh stored counters once per node; never replace unavailable data with zero."""
    now=int(time.time() if now is None else now)
    rows=delivery.s.db.execute("""SELECT a.order_id,a.node_id,o.email FROM allocations a
        JOIN orders o ON o.id=a.order_id WHERE o.status='active' AND o.expiry_ms>?""",(now*1000,)).fetchall()
    by_node={}
    for row in rows: by_node.setdefault(row['node_id'],[]).append(row)
    for node, allocated in by_node.items():
        try:
            stats=delivery.panels[node].inbound().get('clientStats')
            if not isinstance(stats,list): continue
            counters={r.get('email'):r for r in stats if isinstance(r,dict)}
            for row in allocated:
                stat=counters.get(row['email']+'-'+node)
                if not stat: continue
                up,down=stat.get('up'),stat.get('down')
                if type(up) is not int or type(down) is not int or min(up,down)<0: continue
                delivery.s.db.execute('UPDATE allocations SET upload=?,download=?,updated=? WHERE order_id=? AND node_id=?',
                                     (up,down,now,row['order_id'],node))
        except Exception:
            # Keep the last known snapshot; the API labels it stale.
            continue


def traffic_worker(db_path,cfg):
    from core import Store
    from delivery import Delivery
    store=Store(str(db_path))
    delivery=Delivery(cfg,store,Path(db_path).parent)
    while True:
        try: sync_traffic(delivery)
        except Exception: pass
        time.sleep(60)


def account_usage(service, init_data, now=None):
    from delivery import PRODUCTS
    now=int(time.time() if now is None else now)
    uid=service._auth(init_data,now)
    orders=service.db.execute("SELECT * FROM orders WHERE user_id=? AND status='active' AND expiry_ms>? AND product!='mtproto' ORDER BY expiry_ms DESC",(uid,now*1000)).fetchall()
    result=[]
    for order in orders:
        rows=service.db.execute('SELECT quota,upload,download,updated FROM allocations WHERE order_id=?',(order['id'],)).fetchall()
        expected=len(json.loads(order['targets']) or ['regular'])
        known=len(rows)==expected and all(r['updated']>0 for r in rows)
        used=sum(r['upload']+r['download'] for r in rows) if known else None
        unlimited=order['gb']==0
        remaining=None if unlimited or not known else sum(max(0,r['quota']-r['upload']-r['download']) for r in rows)
        updated=min((r['updated'] for r in rows),default=0) if known else None
        result.append({'label':PRODUCTS.get(order['product'],'VPN'),'expires_at':order['expiry_ms']//1000,
                       'used_bytes':used,'remaining_bytes':remaining,'unlimited':unlimited,
                       'limit_bytes':order['gb']*1024**3,'updated_at':updated,
                       'stale':not known or now-updated>180})
    return {'subscriptions':result}


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
            routes={'/api/account/usage','/api/events/state','/api/events/tap','/api/events/play','/api/events/challenge','/api/events/claim'}
            if path not in routes: return self.reply(404,b'Not found')
            if event_service is None: return self.json_reply(503,{'ok':False,'message':'Ивенты пока недоступны.'})
            try:
                length=int(self.headers.get('Content-Length','0'))
                if length<=0 or length>32768: return self.json_reply(413,{'ok':False,'message':'Слишком большой запрос.'})
                body=json.loads(self.rfile.read(length))
                init_data=body.get('init_data','')
                if path=='/api/account/usage': data=account_usage(event_service,init_data)
                elif path=='/api/events/state': data=event_service.state(init_data)
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
    threading.Thread(target=traffic_worker,args=(Path(a.data)/'shop.sqlite3',cfg),daemon=True).start()
    server.serve_forever()
