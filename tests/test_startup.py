import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, MagicMock
import bot

class StartupTests(unittest.TestCase):
    def test_run_does_not_require_payment_or_panel_preflight(self):
        cfg=json.loads(Path('config.example.json').read_text())
        tg=MagicMock()
        tg.call.side_effect=[{'username':'TestBot'},{}]
        payment=MagicMock()
        payment.http.call.side_effect=AssertionError('Provider must not block startup')
        with tempfile.TemporaryDirectory() as data:
            with patch('sys.argv',['bot.py','--data',data]), patch.object(bot,'load_config',return_value=cfg), patch.object(bot,'Telegram',return_value=tg), patch.object(bot,'Lolz',return_value=payment), patch.object(bot,'Panel',side_effect=AssertionError('Panel preflight')), patch.object(bot.Bot,'loop') as loop:
                bot.main()
                loop.assert_called_once()
                payment.http.call.assert_not_called()
