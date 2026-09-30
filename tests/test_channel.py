import asyncio
import io
import json
import tempfile
import time
import unittest
from email.utils import formatdate
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock
from channel_news import parse_feed, fetch_news
from channel_agent import DEFAULT, generate, open_db, reserve, pending_post, channel_entity
try:
    from telethon.tl.types import Channel, ChatAdminRights
except ImportError:
    Channel=ChatAdminRights=None
from providers import Lolz, APIError

class ChannelTests(unittest.TestCase):
    def feed(self,date=None):
        return ('<rss><channel><item><title>Новость</title><link>https://example.org/story</link><pubDate>'+ (date or formatdate(time.time(),usegmt=True)) +'</pubDate><description><![CDATA[<p>Разработчики выпустили обновление приложения с новой полезной функцией для пользователей.</p>]]></description></item></channel></rss>').encode()
    def test_rss_fresh_only_and_html_removed(self):
        article=parse_feed(self.feed())[0]
        self.assertNotIn('<p>',article['body'])
        self.assertEqual(parse_feed(self.feed(formatdate(time.time()-3*86400,usegmt=True))),[])
        self.assertEqual(parse_feed(self.feed('bad date')),[])
    def test_no_fresh_news_when_seen(self):
        a=parse_feed(self.feed())[0]
        opener=MagicMock();opener.open.return_value.__enter__.return_value=io.BytesIO(self.feed())
        with patch('channel_news.urllib.request.build_opener',return_value=opener):
            self.assertIsNone(fetch_news(['https://example.org/rss'],{a['key']}))
    def test_outbox_keeps_same_id_on_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=open_db(Path(tmp));post=reserve(db,-100123,'Текст','source')
            rid=post['random_id'];db.close();db=open_db(Path(tmp))
            self.assertEqual(reserve(db,-100123,'Другой текст','other')['random_id'],rid)
            self.assertEqual(pending_post(db,-100123)['source_key'],'source');db.close()
    def test_generation_attribution_and_no_secrets_in_payload(self):
        article=parse_feed(self.feed())[0]
        opener=MagicMock();opener.open.return_value.__enter__.return_value=io.BytesIO(json.dumps({'done':True,'response':'Разработчики обновили приложение. Пользователям стала доступна новая функция.'}).encode())
        with patch('channel_agent.urllib.request.build_opener',return_value=opener):
            text=generate({**DEFAULT,'api_hash':'SECRET_DO_NOT_SEND'},article)
        self.assertIn('🔗 Источник: https://example.org/story',text)
        payload=json.loads(opener.open.call_args.args[0].data)
        self.assertNotIn('SECRET_DO_NOT_SEND',str(payload))
        self.assertFalse(payload['think']);self.assertFalse(payload['stream'])
    @unittest.skipIf(Channel is None,'Install requirements-channel.txt to test Telethon')
    def test_only_channel_with_post_rights(self):
        client=MagicMock();client.get_entity=AsyncMock(return_value=Channel(id=123,title='News',photo=None,date=None,broadcast=True,admin_rights=ChatAdminRights(post_messages=True)))
        asyncio.run(channel_entity(client,{'channel':'@news'}))
        client.get_entity.return_value.admin_rights=None
        with self.assertRaises(ValueError): asyncio.run(channel_entity(client,{'channel':'@news'}))
    def test_legacy_test_config_cannot_create_demo(self):
        p=Lolz({'token':'test','merchant_id':17,'test':True,'invoice_lifetime':3600},'TestBot')
        with patch.object(p,'get_invoice',side_effect=APIError('LZT',404)), patch.object(p,'call',return_value={}) as create:
            p.ensure_invoice({'id':'o','amount':5000,'hours':720,'gb':0,'user_id':1})
        self.assertIs(create.call_args.kwargs['data']['is_test'],False)
