import io
import json
import tempfile
import time
import unittest
from email.utils import formatdate
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock
from channel_news import parse_feed, fetch_news
from channel_agent import DEFAULT, generate, open_db, reserve, pending_post, Publisher, BotError, deliver, clean_summary, source_url
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
        self.assertNotIn('https://',text)
        self.assertNotIn('Источник:',text)
        payload=json.loads(opener.open.call_args.args[0].data)
        self.assertNotIn('SECRET_DO_NOT_SEND',str(payload))
        self.assertFalse(payload['think']);self.assertFalse(payload['stream'])
    def test_only_channel_with_post_rights(self):
        p=Publisher('123:test')
        with patch.object(p,'call',side_effect=[{'type':'channel','id':-100123},{'id':123,'username':'TestBot'},{'status':'administrator','can_post_messages':True}]) as calls:
            self.assertEqual(p.channel({'channel':'@news'})['id'],-100123)
            self.assertEqual([c.args[0] for c in calls.call_args_list],['getChat','getMe','getChatMember'])
        with patch.object(p,'call',side_effect=[{'type':'channel','id':-100123},{'id':123,'username':'TestBot'},{'status':'member'}]):
            with self.assertRaises(ValueError): p.channel({'channel':'@news'})
        with patch.object(p,'call',return_value={'type':'private'}):
            with self.assertRaises(ValueError): p.channel({'channel':'@news'})
    def test_timeout_does_not_requeue_ambiguous_post(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=open_db(Path(tmp));row=reserve(db,-100123,'Текст','source')
            client=MagicMock();client.send.side_effect=BotError()
            with self.assertRaises(BotError): deliver(db,client,row)
            self.assertIsNone(pending_post(db,-100123))
            self.assertEqual(db.execute('SELECT status FROM posts').fetchone()[0],'uncertain');db.close()
    def test_rate_limit_can_retry_and_success_completes(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=open_db(Path(tmp));row=reserve(db,-100123,'Текст','source')
            client=MagicMock();client.send.side_effect=BotError(429,30)
            with self.assertRaises(BotError): deliver(db,client,row)
            self.assertIsNotNone(pending_post(db,-100123))
            client.send.side_effect=None;client.send.return_value={'message_id':42}
            deliver(db,client,row)
            self.assertEqual(db.execute('SELECT status FROM posts').fetchone()[0],'sent');db.close()
    def test_legacy_test_config_cannot_create_demo(self):
        p=Lolz({'token':'test','merchant_id':17,'test':True,'invoice_lifetime':3600},'TestBot')
        with patch.object(p,'get_invoice',side_effect=APIError('LZT',404)), patch.object(p,'call',return_value={}) as create:
            p.ensure_invoice({'id':'o','amount':5000,'hours':720,'gb':0,'user_id':1})
        self.assertIs(create.call_args.kwargs['data']['is_test'],False)

class SummaryCleanupTests(unittest.TestCase):
    def test_source_and_editorial_notes_removed(self):
        article={'url':'https://habr.com/ru/news/123/?utm_source=rss'}
        raw='Разработчики выпустили обновление.\n\nСмайлики: 🌊🌊\n(600 символов)\nИсточник: https://habr.com/ru/news/123/'
        self.assertEqual(clean_summary(raw,article),'Разработчики выпустили обновление.')
        self.assertEqual(source_url(article['url']),'https://habr.com/ru/news/123/')
    def test_unknown_link_is_still_rejected(self):
        with self.assertRaisesRegex(ValueError,'постороннюю ссылку'):
            clean_summary('Новость https://other.example/test',{'url':'https://habr.com/ru/news/123/'})
    def test_non_russian_is_distinct_error(self):
        with self.assertRaisesRegex(ValueError,'не на русском'):
            clean_summary('A new application is released',{'url':'https://habr.com/ru/news/123/'})

class PhotoEditorialTests(unittest.TestCase):
    def test_migration_preserves_identity_and_custom_feeds(self):
        from channel_agent import migrate_config
        old={'channel_id':-100123,'model':'custom','style':'до 600 символов','feeds':['https://custom.example/rss']}
        new=migrate_config(old)
        self.assertEqual(new['channel_id'],-100123)
        self.assertEqual(new['model'],'custom')
        self.assertIn('https://custom.example/rss',new['feeds'])
        self.assertEqual(len(new['feeds']),5)
        self.assertNotIn('600',new['style'])
        self.assertFalse(new['show_source'])
        self.assertEqual(new['interval_hours'],1)
        self.assertEqual(migrate_config(new),new)
    def test_rss_images_and_private_urls(self):
        from channel_news import public_image
        raw=ChannelTests().feed().replace(b'<p>',b'<img src="https://images.example/photo.jpg"><p>')
        self.assertEqual(parse_feed(raw)[0]['photo'],'https://images.example/photo.jpg')
        self.assertEqual(public_image('https://127.0.0.1/image.jpg','https://example.org'),'')
        self.assertEqual(public_image('/photo.jpg','https://example.org/news'),'https://example.org/photo.jpg')
    def test_long_photo_retry_keeps_photo_checkpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=open_db(Path(tmp));row=reserve(db,-100123,'Заголовок 🥶\n\n'+('Подробности новости. '*100),'source','https://example.org/p.jpg')
            client=MagicMock();client.photo.return_value={'message_id':41};client.send.side_effect=BotError(429,30)
            with self.assertRaises(BotError): deliver(db,client,row)
            self.assertEqual(pending_post(db,-100123)['photo_message_id'],41)
            client.send.side_effect=None;client.send.return_value={'message_id':42}
            deliver(db,client,row)
            self.assertEqual(client.photo.call_count,1)
            self.assertEqual(db.execute('SELECT status FROM posts').fetchone()[0],'sent');db.close()
    def test_short_caption_single_message_and_utf16(self):
        from channel_agent import heading_entities,photo_parts
        self.assertEqual(heading_entities('🥶 Заголовок\nТекст')[0]['length'],12)
        self.assertEqual(photo_parts('🥶'*513),('','🥶'*513))
        with tempfile.TemporaryDirectory() as tmp:
            db=open_db(Path(tmp));row=reserve(db,-100123,'Заголовок\n\nТекст','s','https://example.org/p.jpg')
            client=MagicMock();client.photo.return_value={'message_id':1}
            deliver(db,client,row);client.send.assert_not_called();db.close()
    def test_photo_timeout_remains_uncertain(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=open_db(Path(tmp));row=reserve(db,-100123,'Текст','s','https://example.org/p.jpg')
            client=MagicMock();client.photo.side_effect=BotError()
            with self.assertRaises(BotError): deliver(db,client,row)
            self.assertEqual(db.execute('SELECT status FROM posts').fetchone()[0],'uncertain');db.close()
    def test_require_photo_skips_imageless(self):
        opener=MagicMock();opener.open.return_value.__enter__.return_value=io.BytesIO(ChannelTests().feed())
        with patch('channel_news.urllib.request.build_opener',return_value=opener):
            self.assertIsNone(fetch_news(['https://example.org/rss'],require_photo=True))

class CalendarTests(unittest.TestCase):
    def stamp(self,date):
        from datetime import datetime
        from zoneinfo import ZoneInfo
        return datetime.fromisoformat(date).replace(tzinfo=ZoneInfo('Europe/Moscow')).timestamp()
    def test_weekday_weekend_summer_holiday(self):
        from channel_agent import slots
        for day,count in [('2026-09-30',3),('2026-10-03',5),('2026-07-01',5),('2026-11-04',5)]:
            self.assertEqual(len(slots({},self.stamp(day+'T12:00:00'))),count)
    def test_no_catchup_and_persistent_slot(self):
        from channel_agent import due_slot
        with tempfile.TemporaryDirectory() as tmp:
            db=open_db(Path(tmp))
            self.assertIsNone(due_slot(db,1,{},self.stamp('2026-09-30T14:00:00')))
            stamp=self.stamp('2026-09-30T15:10:00')
            slot=due_slot(db,1,{},stamp);self.assertTrue(slot)
            db.execute('INSERT INTO agent_meta VALUES(?,?)',(slot,'1'));db.commit();db.close()
            db=open_db(Path(tmp));self.assertIsNone(due_slot(db,1,{},stamp));db.close()
    def test_breaking_requires_recent_second_source(self):
        from channel_agent import choose_breaking
        a={'key':'a','url':'https://one.test/a','title':'В городе Примерске произошел теракт на вокзале','body':'Сообщение','published':10000}
        b={**a,'key':'b','url':'https://two.test/b'}
        self.assertIsNone(choose_breaking([a],set(),10010))
        self.assertTrue(choose_breaking([a,b],set(),10010)['breaking'])
        self.assertIsNone(choose_breaking([a,b],{'b'},10010))
        self.assertIsNone(choose_breaking([a,b],set(),15000))
    def test_signature_uses_utf16_offset(self):
        p=Publisher('123:test');p.channel_url='https://t.me/ReversVPN'
        text='Новость 🥶\n\nReVPN. Новостной канал'
        entity=p.entities(text)[-1]
        self.assertEqual(entity['type'],'text_link')
        self.assertEqual(entity['offset'],12)
    def test_teaser_and_duplicate_removed(self):
        text='Заголовок\n\nТекст новости. Читать далее\n\nТекст новости.'
        cleaned=clean_summary(text,{'url':'https://example.org/a'})
        self.assertNotIn('Читать далее',cleaned)
        self.assertEqual(cleaned.count('Текст новости.'),1)


class BreakingAviationTests(unittest.TestCase):
    def test_possible_hijack_signal_is_an_urgent_report(self):
        from channel_agent import breaking_kind,choose_breaking
        title='Самолёт из Дубая в Тель-Авив подал сигнал о возможном захвате'
        self.assertEqual(breaking_kind(title),'aviation')
        a={'title':title,'body':'Причина уточняется.','key':'a','url':'https://one.test/news','published':10000}
        b={**a,'title':'Самолет из Дубая в Тель-Авив подал сигнал бедствия','key':'b','url':'https://two.test/news'}
        self.assertIsNotNone(choose_breaking([a,b],set(),10010))
        self.assertIsNone(choose_breaking([a],set(),10010))
    def test_routine_airline_story_not_urgent(self):
        from channel_agent import breaking_kind
        self.assertEqual(breaking_kind('Самолёт из Дубая в Тель-Авив открыл новый рейс'),'')
