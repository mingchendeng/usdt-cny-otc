from otc_collector.models import Quote, as_int, num, ratio_to_percent, valid_price
from otc_collector.payments import payment_names

URL = "https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search"
HEADERS = {
    "clienttype": "web",
    "lang": "zh-CN",
    "Origin": "https://p2p.binance.com",
    "Referer": "https://p2p.binance.com/",
}
ROWS = 20

# 币安 userType=merchant 才是通过平台审核、可以挂广告的认证商家。
_TIERS = {
    "MASS_MERCHANT": "认证商家",
    "BLOCK_MERCHANT": "大宗商家",
    "PRO_MERCHANT": "专业商家",
    "PROFESSION": "专业商家",
}


def parse_binance_ad(item: dict, user_side: str) -> Quote | None:
    advertiser = item.get("advertiser") or {}
    if advertiser.get("userType") != "merchant":
        return None
    adv = item.get("adv") or {}
    merchant_side = "SELL" if user_side == "buy" else "BUY"
    if adv.get("tradeType") not in (None, merchant_side):
        return None
    price = valid_price(adv.get("price"))
    if price is None:
        return None
    identity = str(advertiser.get("userIdentity") or "")
    tier = _TIERS.get(identity, "认证商家" if not identity else f"认证商家({identity})")
    return Quote(
        exchange="binance",
        exchange_name="币安",
        side=user_side,
        price=price,
        available_usdt=_num_or_fallback(adv.get("tradableQuantity"), adv.get("surplusAmount")),
        min_cny=_num_or_fallback(adv.get("minSingleTransAmount")),
        max_cny=_num_or_fallback(adv.get("dynamicMaxSingleTransAmount"), adv.get("maxSingleTransAmount")),
        payments=payment_names(adv.get("tradeMethods")),
        merchant_name=str(advertiser.get("nickName") or "未知商家"),
        merchant_id=str(advertiser.get("userNo") or ""),
        merchant_tier=tier,
        month_orders=as_int(advertiser.get("monthOrderCount")),
        order_window="30天",
        completion_rate=ratio_to_percent(advertiser.get("monthFinishRate")),
        positive_rate=ratio_to_percent(advertiser.get("positiveRate")),
        ad_id=str(adv.get("advNo") or ""),
        online=None,
    )


def _num_or_fallback(*values):
    for value in values:
        parsed = num(value)
        if parsed is not None:
            return parsed
    return None


class Binance:
    code = "binance"
    name = "币安"

    def fetch(self, client, pages: int) -> list[Quote]:
        quotes: list[Quote] = []
        for user_side, trade_type in (("buy", "BUY"), ("sell", "SELL")):
            for page in range(1, pages + 1):
                payload = {
                    "asset": "USDT",
                    "fiat": "CNY",
                    "merchantCheck": False,
                    "page": page,
                    "payTypes": [],
                    "publisherType": "merchant",
                    "rows": ROWS,
                    "tradeType": trade_type,
                }
                body = client.post_json(URL, payload, HEADERS)
                if str(body.get("code")) != "000000":
                    raise RuntimeError(f"币安返回异常: {body.get('message') or body.get('code')}")
                rows = body.get("data") or []
                if not rows:
                    break
                for item in rows:
                    quote = parse_binance_ad(item, user_side)
                    if quote is not None:
                        quotes.append(quote)
                total = body.get("total") or 0
                if page * ROWS >= total:
                    break
        return quotes
