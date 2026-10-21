import tempfile
import unittest
from pathlib import Path

from otc_collector.models import Quote
from otc_collector.site import build_payload, render_page, write_site


class SiteTests(unittest.TestCase):
    def test_page_shows_prices_and_escapes_names(self):
        quotes = [
            _quote("binance", "币安", "buy", 6.65, "<script>便宜</script>", orders=10),
            _quote("binance", "币安", "sell", 6.67, "高价商家", orders=80),
        ]
        payload = build_payload(
            quotes,
            "2026-10-21T09:05:00+08:00",
            [{"exchange": "htx", "exchange_name": "HTX", "error": "HTTP 429"}],
        )
        page = render_page(payload)
        self.assertIn("2026-10-21T09:05:00+08:00", page)
        self.assertIn("6.6500", page)
        self.assertIn("6.6700", page)
        self.assertIn("+0.0200", page)
        self.assertIn("&lt;script&gt;便宜&lt;/script&gt;", page)
        self.assertNotIn("<script>便宜</script>", page)
        self.assertIn("HTTP 429", page)
        self.assertIn("高价商家", page)
        binance = payload["exchanges"][0]
        self.assertEqual(binance["exchange"], "binance")
        self.assertEqual(binance["spread"], 0.02)
        self.assertEqual(payload["exchanges"][1]["ok"], False)

    def test_write_site_creates_html_and_json(self):
        quotes = [_quote("okx", "欧易", "buy", 6.66, "欧易商家")]
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            write_site(directory, quotes, "t", [])
            html_text = (directory / "index.html").read_text(encoding="utf-8")
            data = (directory / "quotes.json").read_text(encoding="utf-8")
        self.assertIn("欧易商家", html_text)
        self.assertIn("欧易", data)
        self.assertIn('"buy": 6.66', data)


def _quote(exchange, name, side, price, merchant, orders=1):
    return Quote(
        exchange=exchange,
        exchange_name=name,
        side=side,
        price=price,
        available_usdt=1000,
        min_cny=500,
        max_cny=50000,
        payments=("银行卡",),
        merchant_name=merchant,
        merchant_id=merchant,
        merchant_tier="认证商家",
        month_orders=orders,
        order_window="近30天",
        completion_rate=99,
        positive_rate=99,
        ad_id=f"{exchange}-{side}-{merchant}",
        online=True,
    )
