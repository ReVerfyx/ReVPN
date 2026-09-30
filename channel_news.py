"""Fetch dated RSS/Atom news, preserving attribution and suppressing repeats."""
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from html.parser import HTMLParser
import hashlib
import re
import time
import urllib.request
from urllib.parse import urlsplit, urljoin
import ipaddress
import xml.etree.ElementTree as ET

class Plain(HTMLParser):
    def __init__(self): super().__init__(); self.parts=[]; self.hidden=0
    def handle_starttag(self,tag,attrs):
        if tag in ('script','style'): self.hidden+=1
    def handle_endtag(self,tag):
        if tag in ('script','style'): self.hidden=max(0,self.hidden-1)
    def handle_data(self,data):
        if not self.hidden: self.parts.append(data)

def plain(value):
    p=Plain();p.feed(value or '')
    return re.sub(r'\s+',' ',unescape(' '.join(p.parts))).strip()

def public_image(value,base):
    url=urljoin(base,unescape(value or '').strip())
    p=urlsplit(url)
    if p.scheme!='https' or not p.hostname or p.username or p.password: return ''
    if p.hostname.lower()=='localhost' or p.hostname.lower().endswith(('.local','.localhost')): return ''
    try:
        if not ipaddress.ip_address(p.hostname).is_global: return ''
    except ValueError: pass
    if p.path.lower().endswith(('.svg','.gif','.webp')): return ''
    return url

class Images(HTMLParser):
    def __init__(self): super().__init__();self.urls=[]
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=='img':
            if a.get('width')=='1' or a.get('height')=='1': return
            self.urls.append(a.get('src') or a.get('data-src',''))

def feed_photo(item,markup,base):
    candidates=[]
    for node in item.iter():
        name=node.tag.rsplit('}',1)[-1]
        if name in ('enclosure','content','thumbnail'):
            kind=node.get('type','')
            if kind.startswith('image/') or node.get('medium')=='image' or name=='thumbnail':
                candidates.append(node.get('url',''))
    parser=Images();parser.feed(markup);candidates.extend(parser.urls)
    return next((url for candidate in candidates if (url:=public_image(candidate,base))), '')

def parse_feed(raw,now=None):
    now=now or time.time()
    if b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper(): raise ValueError('Unsupported XML declarations')
    root=ET.fromstring(raw)
    result=[]
    for item in root.iter():
        if item.tag.rsplit('}',1)[-1] not in ('item','entry'): continue
        fields={c.tag.rsplit('}',1)[-1]:c for c in item}
        def value(name):
            node=fields.get(name)
            return ''.join(node.itertext()).strip() if node is not None else ''
        link=value('link')
        for child in item:
            if child.tag.rsplit('}',1)[-1]=='link' and child.get('rel','alternate')=='alternate' and child.get('href'):
                link=child.get('href');break
        parsed=urlsplit(link)
        if parsed.scheme!='https' or not parsed.hostname or parsed.username: continue
        date=value('pubDate') or value('published') or value('updated')
        try:
            try: dt=parsedate_to_datetime(date)
            except (ValueError,TypeError): dt=datetime.fromisoformat(date.replace('Z','+00:00'))
            if dt.tzinfo is None: continue
            stamp=dt.timestamp()
        except (ValueError,TypeError,OverflowError): continue
        if not now-48*3600<=stamp<=now+300: continue
        title=plain(value('title'))[:250]
        markup=value('encoded') or value('content') or value('description') or value('summary')
        body=plain(markup)[:7000]
        photo=feed_photo(item,markup,link)
        if not title or len(body)<60: continue
        result.append({'title':title,'body':body,'photo':photo,'url':link,'published':stamp,
                       'key':hashlib.sha256(link.encode()).hexdigest()})
    return result

def fetch_news(feeds,seen=(),require_photo=False):
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    articles=[]
    for url in feeds:
        if urlsplit(url).scheme!='https': raise ValueError('RSS должен использовать HTTPS')
        try:
            req=urllib.request.Request(url,headers={'User-Agent':'ReVPN-News/1.0','Accept':'application/rss+xml, application/atom+xml, application/xml, text/xml'})
            with opener.open(req,timeout=20) as r: raw=r.read(2_000_001)
            if len(raw)>2_000_000: continue
            articles.extend(parse_feed(raw))
        except Exception: continue
    articles.sort(key=lambda a:a['published'],reverse=True)
    return next((a for a in articles if a['key'] not in seen and (a.get('photo') or not require_photo)),None)
