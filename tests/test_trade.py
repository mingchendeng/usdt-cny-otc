import unittest

from otc_collector.lark import build_cards
from otc_collector.models import Quote
from otc_collector.report import accepts_trade, summarize
from otc_collector.site import build_payload


class TradeFilterTests(unittest.TestCase):
    def test_amount_and_payment_decide_the_best_price(self):
        quotes = [
            _quote("buy", 6.50, "小额", max_cny=1000),
            _quote("buy", 6.40, "只收微信", payments=("微信",)),
            _quote("buy", 6.70, "门槛太高", min_cny=20000),
            _quote("buy", 6.66, "银行卡商家", payments=("银行卡",)),
            _quote("buy", 6.67, "支付宝商家", payments=("支付宝",)),
            _quote("sell", 6.80, "卖出商家"),
        ]
        self.assertFalse(accepts_trade(quotes[0]))
        self.assertFalse(accepts_trade(quotes[1]))
        self.assertFalse(accepts_trade(quotes[2]))
        self.assertTrue(accepts_trade(quotes[3]))
        rows = {row["side"]: row for row in summarize(quotes)}
        self.assertEqual(rows["buy"]["best"], 6.66)
        self.assertEqual(rows["buy"]["merchant"], "银行卡商家")
        self.assertEqual(rows["buy"]["count"], 2)
        self.assertEqual(rows["sell"]["best"], 6.80)

        card = build_cards(quotes, "t")[0]
        values = [column["elements"][1]["content"] for column in card["body"]["elements"][0]["columns"]]
        self.assertEqual(values, ["6.6600", "6.8000", "+0.1400"])
        text = "\n".join(element.get("content", "") for element in card["body"]["elements"])
        self.assertIn("1 万元 · 银行卡或支付宝", text)
        self.assertNotIn("小额", text)
        self.assertNotIn("只收微信", text)

        page = build_payload(quotes, "t", [])
        self.assertEqual(page["exchanges"][0]["buy"], 6.66)
        self.assertIn("1 万元", page["note"])

    def test_exchange_stays_visible_when_nothing_fits(self):
        quotes = [_quote("buy", 6.50, "小额", max_cny=500)]
        payload = build_payload(quotes, "t", [])
        row = payload["exchanges"][0]
        self.assertTrue(row["ok"])
        self.assertIsNone(row["buy"])
        self.assertIn("没有符合", row["notice"])
        card = build_cards(quotes, "t")[0]
        text = "\n".join(element.get("content", "") for element in card["body"]["elements"])
        self.assertIn("没有符合条件的广告", text)

    def test_boundary_amount_is_included(self):
        self.assertTrue(accepts_trade(_quote("buy", 6.6, "刚好", min_cny=10000, max_cny=10000)))
        self.assertFalse(accepts_trade(_quote("buy", 6.6, "未知限额", min_cny=None, max_cny=None)))


def _quote(side, price, merchant, min_cny=100, max_cny=50000, payments=("银行卡",)):
    return Quote(
        exchange="binance",
        exchange_name="币安",
        side=side,
        price=price,
        available_usdt=1000,
        min_cny=min_cny,
        max_cny=max_cny,
        payments=payments,
        merchant_name=merchant,
        merchant_id=merchant,
        merchant_tier="认证商家",
        month_orders=10,
        order_window="30天",
        completion_rate=99,
        positive_rate=99,
        ad_id=f"{side}-{merchant}",
        online=True,
    )
