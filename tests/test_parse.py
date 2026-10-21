import unittest

from otc_collector.exchanges.binance import parse_binance_ad
from otc_collector.exchanges.bitget import parse_bitget_ad
from otc_collector.exchanges.htx import parse_htx_ad
from otc_collector.exchanges.okx import parse_okx_ad
from otc_collector.models import Quote
from otc_collector.payments import normalize_payment
from otc_collector.report import summarize


class ParseTests(unittest.TestCase):
    def test_binance_keeps_merchant_and_drops_user(self):
        merchant = parse_binance_ad(_binance("merchant", "MASS_MERCHANT"), "buy")
        self.assertIsNotNone(merchant)
        self.assertEqual(merchant.side, "buy")
        self.assertEqual(merchant.price, 6.65)
        self.assertEqual(merchant.merchant_tier, "认证商家")
        self.assertEqual(merchant.payments, ("银行卡",))
        self.assertEqual(merchant.completion_rate, 99)
        self.assertEqual(merchant.order_window, "30天")
        self.assertIsNone(parse_binance_ad(_binance("user", ""), "buy"))

    def test_binance_drops_wrong_direction(self):
        self.assertIsNone(parse_binance_ad(_binance("merchant", "MASS_MERCHANT"), "sell"))

    def test_okx_keeps_certified_and_diamond_only(self):
        certified = parse_okx_ad(_okx("certified", "认证商家"), "buy")
        diamond = parse_okx_ad(_okx("diamond", "钻石商家"), "sell")
        self.assertEqual(certified.merchant_tier, "认证商家")
        self.assertEqual(certified.payments, ("支付宝", "银行卡"))
        self.assertEqual(diamond.side, "sell")
        self.assertEqual(diamond.merchant_tier, "钻石商家")
        self.assertIsNone(parse_okx_ad(_okx("common", ""), "buy"))

    def test_htx_drops_regular_users(self):
        kept = parse_htx_ad(_htx(2), "buy")
        self.assertEqual(kept.merchant_tier, "认证商家")
        self.assertEqual(kept.payments, ("支付宝",))
        self.assertEqual(kept.completion_rate, 99)
        self.assertEqual(parse_htx_ad(_htx(3), "buy").merchant_tier, "超级商家")
        self.assertIsNone(parse_htx_ad(_htx(1), "buy"))
        self.assertIsNone(parse_htx_ad(_htx(0), "buy"))

    def test_bitget_drops_uncertified(self):
        kept = parse_bitget_ad(_bitget(1, 2))
        self.assertEqual(kept.side, "buy")
        self.assertEqual(kept.merchant_tier, "进阶商家")
        self.assertEqual(kept.payments, ("支付宝",))
        self.assertEqual(kept.available_usdt, 80)
        self.assertEqual(kept.order_window, "30天")
        self.assertEqual(parse_bitget_ad(_bitget(2, 1)).side, "sell")
        master = _bitget(1, 1)
        master["merchantGradeRespList"] = [{"gradeName": "Master"}]
        self.assertEqual(parse_bitget_ad(master).merchant_tier, "顶级商家")
        self.assertIsNone(parse_bitget_ad(_bitget(0, 2)))

    def test_payment_codes(self):
        self.assertEqual(normalize_payment("wxPay"), "微信")
        self.assertEqual(normalize_payment("WeChat"), "微信")
        self.assertEqual(normalize_payment("银行借记卡"), "银行卡")
        self.assertEqual(normalize_payment("QQ Wallet"), "QQ钱包")

    def test_summary_best_price_direction(self):
        quotes = [
            _quote("binance", "币安", "buy", 6.70, "贵"),
            _quote("binance", "币安", "buy", 6.60, "便宜"),
            _quote("binance", "币安", "sell", 6.80, "高价"),
            _quote("binance", "币安", "sell", 6.66, "低价"),
        ]
        rows = {row["side"]: row for row in summarize(quotes)}
        self.assertEqual(rows["buy"]["best"], 6.60)
        self.assertEqual(rows["buy"]["merchant"], "便宜")
        self.assertEqual(rows["sell"]["best"], 6.80)
        self.assertEqual(rows["sell"]["merchant"], "高价")


def _binance(user_type, identity):
    return {
        "adv": {
            "advNo": "1",
            "price": "6.65",
            "surplusAmount": "100",
            "tradableQuantity": "90",
            "minSingleTransAmount": "200",
            "maxSingleTransAmount": "5000",
            "tradeType": "SELL",
            "tradeMethods": [{"identifier": "BANK", "tradeMethodName": "银行借记卡"}],
        },
        "advertiser": {
            "nickName": "测试商家",
            "userType": user_type,
            "userNo": "u1",
            "userIdentity": identity,
            "monthOrderCount": 12,
            "monthFinishRate": 0.99,
            "positiveRate": 1,
        },
    }


def _okx(creator, badge):
    side = "buy" if creator == "diamond" else "sell"
    return {
        "id": "9",
        "price": "6.66",
        "side": side,
        "availableAmount": "10",
        "quoteMinAmountPerOrder": "100",
        "quoteMaxAmountPerOrder": "1000",
        "paymentMethods": ["aliPay", "bank"],
        "nickName": "欧易商家",
        "merchantId": "m1",
        "creatorType": creator,
        "badgeInfo": {"badgeList": [{"title": badge}] if badge else []},
        "completedRate": "0.995",
        "completedOrderQuantity": 100,
        "posReviewPercentage": "98",
    }


def _htx(level):
    return {
        "id": 7,
        "uid": 99,
        "userName": "火币商家",
        "price": "6.64",
        "merchantLevel": level,
        "tradeType": 1,
        "tradeCount": "50",
        "minTradeLimit": "500",
        "maxTradeLimit": "1000",
        "orderCompleteRate": "99",
        "tradeMonthTimes": 12,
        "payMethods": [{"name": "Alipay"}],
        "isOnline": True,
    }


def _bitget(certified, ad_type):
    return {
        "adNo": "a1",
        "price": "6.63",
        "adType": ad_type,
        "certifiedMerchant": certified,
        "nickName": "bg商家",
        "encryptUserId": "x",
        "amount": "100",
        "lastAmount": "80",
        "minAmount": "10",
        "maxAmount": "500",
        "paymethodInfo": [{"paymethodName": "Alipay"}],
        "merchantGradeRespList": [{"gradeName": "Advanced"}],
        "thirtyTunoverNum": "4",
        "thirtyCompletionRate": "0.9",
        "turnoverRate": "0.98",
        "goodEvaluationRate": "100",
        "showOnline": True,
    }


def _quote(exchange, name, side, price, merchant):
    return Quote(
        exchange=exchange,
        exchange_name=name,
        side=side,
        price=price,
        available_usdt=1,
        min_cny=1,
        max_cny=2,
        payments=("银行卡",),
        merchant_name=merchant,
        merchant_id="1",
        merchant_tier="认证商家",
        month_orders=1,
        order_window="30天",
        completion_rate=99,
        positive_rate=100,
        ad_id=merchant,
        online=True,
    )


if __name__ == "__main__":
    unittest.main()
