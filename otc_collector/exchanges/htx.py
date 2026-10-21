from otc_collector.models import Quote, as_int, as_percent, num, valid_price
from otc_collector.payments import payment_names

URL = (
    "https://www.htx.com/-/x/otc/v1/data/trade-market"
    "?coinId=2&currency=172&tradeType={trade_type}&currPage={page}"
    "&payMethod=0&acceptOrder=-1&blockType=general&online=1&range=0"
    "&onlyTradable=false&isFollowed=false"
)
HEADERS = {"Referer": "https://www.htx.com/zh-cn/fiat-crypto/trade/buy-usdt-cny/"}

# HTX 公开盘口里 merchantLevel 2 是认证商家，3 是超级商家。0/1 是普通用户，丢掉。
_TIERS = {2: "认证商家", 3: "超级商家"}


def parse_htx_ad(item: dict, user_side: str) -> Quote | None:
    try:
        level = int(item.get("merchantLevel"))
    except (TypeError, ValueError):
        return None
    if level < 2:
        return None
    expected = 1 if user_side == "buy" else 0
    if item.get("tradeType") not in (None, expected):
        return None
    price = valid_price(item.get("price"))
    if price is None:
        return None
    return Quote(
        exchange="htx",
        exchange_name="HTX",
        side=user_side,
        price=price,
        available_usdt=num(item.get("tradeCount")),
        min_cny=num(item.get("minTradeLimit")),
        max_cny=num(item.get("maxTradeLimit")),
        payments=payment_names(item.get("payMethods")),
        merchant_name=str(item.get("userName") or "未知商家"),
        merchant_id=str(item.get("uid") or ""),
        merchant_tier=_TIERS.get(level, f"认证商家(Lv{level})"),
        month_orders=as_int(item.get("tradeMonthTimes")),
        order_window="30天",
        completion_rate=as_percent(item.get("orderCompleteRate")),
        positive_rate=None,
        ad_id=str(item.get("id") or ""),
        online=item.get("isOnline") if isinstance(item.get("isOnline"), bool) else None,
    )


class Htx:
    code = "htx"
    name = "HTX"

    def fetch(self, client, pages: int) -> list[Quote]:
        quotes: list[Quote] = []
        for user_side, trade_type in (("buy", "sell"), ("sell", "buy")):
            for page in range(1, pages + 1):
                body = client.get_json(URL.format(trade_type=trade_type, page=page), HEADERS)
                if body.get("code") != 200:
                    raise RuntimeError(f"HTX 返回异常: {body.get('message') or body.get('code')}")
                rows = body.get("data") or []
                if not rows:
                    break
                for item in rows:
                    quote = parse_htx_ad(item, user_side)
                    if quote is not None:
                        quotes.append(quote)
                total_page = body.get("totalPage") or 1
                if page >= total_page:
                    break
        return quotes
