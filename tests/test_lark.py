import unittest

from otc_collector.lark import build_cards, sign
from otc_collector.models import Quote
from otc_collector.report import top_merchants_by_orders


class LarkCardTests(unittest.TestCase):
    def test_sign_matches_feishu_algorithm(self):
        self.assertEqual(sign("1599360473", "test-secret"), "wSds2BzzFIIGf/WrhUO+NI1q/9j+FRJd3JNHKAq0NZY=")

    def test_card_prices_spread_and_failure(self):
        quotes = [
            _quote("binance", "币安", "buy", 6.65, "便宜商家"),
            _quote("binance", "币安", "sell", 6.67, "高价商家"),
            _quote("okx", "欧易", "buy", 6.66, "欧易商家"),
            _quote("htx", "HTX", "buy", 6.64, "不该出现"),
        ]
        cards = build_cards(
            quotes,
            "2026-10-14T18:00:00+08:00",
            [{"exchange": "htx", "exchange_name": "HTX", "error": "HTTP 429"}],
        )
        self.assertEqual([card["header"]["title"]["content"] for card in cards], ["币安", "欧易", "HTX"])
        binance, okx, htx = cards
        self.assertEqual(binance["schema"], "2.0")
        self.assertEqual(binance["header"]["template"], "blue")
        self.assertEqual(binance["header"]["subtitle"]["content"], "2026-10-14T18:00:00+08:00")
        prices = binance["body"]["elements"][0]
        self.assertEqual(prices["tag"], "column_set")
        values = [column["elements"][1]["content"] for column in prices["columns"]]
        self.assertEqual(values, ["6.6500", "6.6700", "+0.0200"])
        okx_values = [column["elements"][1]["content"] for column in okx["body"]["elements"][0]["columns"]]
        self.assertEqual(okx_values[1], "—")
        self.assertEqual(okx_values[2], "—")
        self.assertEqual(htx["header"]["template"], "red")
        self.assertNotIn("不该出现", str(cards))
        self.assertNotIn("欧易商家", str(binance))
        text = "\n".join(element.get("content", "") for element in binance["body"]["elements"])
        self.assertIn("便宜商家", text)
        self.assertIn("成交单数靠前", text)
        htx_text = "\n".join(element.get("content", "") for element in htx["body"]["elements"])
        self.assertIn("HTTP 429", htx_text)

    def test_merchants_ranked_by_orders_within_exchange(self):
        quotes = [
            _quote("binance", "币安", "buy", 6.50, "小商家", orders=3),
            _quote("binance", "币安", "sell", 6.80, "大商家", orders=90),
            _quote("binance", "币安", "buy", 6.70, "大商家", orders=90),
            _quote("binance", "币安", "buy", 6.40, "中商家", orders=40),
        ]
        for index in range(4):
            quotes.append(_quote("binance", "币安", "buy", 7, f"凑数{index}", orders=index))
        ranked = top_merchants_by_orders(quotes, limit=2)[0]["merchants"]
        self.assertEqual([item["merchant_name"] for item in ranked], ["大商家", "中商家"])
        self.assertEqual(ranked[0]["orders"], 90)
        self.assertEqual(ranked[0]["buy"], 6.70)
        self.assertEqual(ranked[0]["sell"], 6.80)
        card = build_cards(quotes, "t")[0]
        text = "\n".join(element.get("content", "") for element in card["body"]["elements"])
        self.assertIn("1. 大商家", text)
        self.assertNotIn("凑数0", text)
        self.assertLess(text.find("1. 大商家"), text.find("2. 中商家"))

    def test_all_failed_card_is_red(self):
        cards = build_cards([], "t", [{"exchange": "binance", "exchange_name": "币安", "error": "超时"}])
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]["header"]["title"]["content"], "币安")
        self.assertEqual(cards[0]["header"]["template"], "red")
        self.assertIn("失败", cards[0]["config"]["summary"]["content"])

    def test_webhook_host_check_rejects_other_sites(self):
        from otc_collector.lark import _valid_webhook

        self.assertTrue(
            _valid_webhook("https://open.feishu.cn/open-apis/bot/v2/hook/abc-def")
        )
        self.assertTrue(
            _valid_webhook("https://open.larksuite.com/open-apis/bot/v2/hook/abc-def")
        )
        self.assertFalse(_valid_webhook("https://example.com/open-apis/bot/v2/hook/abc"))
        self.assertFalse(_valid_webhook("http://open.feishu.cn/open-apis/bot/v2/hook/abc"))
        self.assertFalse(_valid_webhook("https://open.feishu.cn/open-apis/bot/v2/hook/"))


def _quote(exchange, name, side, price, merchant, orders=1):
    return Quote(
        exchange=exchange,
        exchange_name=name,
        side=side,
        price=price,
        available_usdt=1,
        min_cny=100,
        max_cny=1000,
        payments=("银行卡",),
        merchant_name=merchant,
        merchant_id=merchant,
        merchant_tier="认证商家",
        month_orders=orders,
        order_window="30天",
        completion_rate=99,
        positive_rate=100,
        ad_id=f"{exchange}-{side}-{merchant}",
        online=True,
    )


if __name__ == "__main__":
    unittest.main()
