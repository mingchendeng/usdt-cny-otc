from otc_collector.models import Quote, as_int, num, ratio_to_percent, valid_price
from otc_collector.payments import payment_names

URL = (
    "https://www.okx.com/v3/c2c/tradingOrders/books"
    "?quoteCurrency=cny&baseCurrency=usdt&side={side}"
    "&paymentMethod=all&userType=certified&showTrade=false"
    "&receivingAds=false&showFollow=false&showAlreadyTraded=false&isAbleFilter=false"
)
HEADERS = {
    "Referer": "https://www.okx.com/zh-hans/p2p-markets/cny/buy-usdt",
}

# creatorType 是欧易给挂单方的身份。certified / diamond 都是平台认证商家。
_CERTIFIED = {"certified", "diamond"}
_TIER_BY_TYPE = {"certified": "认证商家", "diamond": "钻石商家"}
_TIER_BY_BADGE = {
    "认证商家": "认证商家",
    "钻石商家": "钻石商家",
    "Super Merchant": "认证商家",
    "Diamond Merchant": "钻石商家",
}


def parse_okx_ad(item: dict, user_side: str) -> Quote | None:
    creator = str(item.get("creatorType") or "")
    badges = _badge_titles(item)
    if creator not in _CERTIFIED and not any(title in _TIER_BY_BADGE for title in badges):
        return None
    merchant_side = "sell" if user_side == "buy" else "buy"
    if item.get("side") not in (None, merchant_side):
        return None
    price = valid_price(item.get("price"))
    if price is None:
        return None
    tier = _TIER_BY_TYPE.get(creator)
    if tier is None:
        for title in badges:
            if title in _TIER_BY_BADGE:
                tier = _TIER_BY_BADGE[title]
                break
    positive = num(item.get("posReviewPercentage"))
    return Quote(
        exchange="okx",
        exchange_name="欧易",
        side=user_side,
        price=price,
        available_usdt=num(item.get("availableAmount")),
        min_cny=num(item.get("quoteMinAmountPerOrder")),
        max_cny=num(item.get("quoteMaxAmountPerOrder")),
        payments=payment_names(item.get("paymentMethods")),
        merchant_name=str(item.get("nickName") or "未知商家"),
        merchant_id=str(item.get("publicUserId") or item.get("merchantId") or ""),
        merchant_tier=tier or "认证商家",
        month_orders=as_int(item.get("completedOrderQuantity")),
        order_window="累计",
        completion_rate=ratio_to_percent(item.get("completedRate")),
        positive_rate=None if positive is None or positive < 0 else round(positive, 4),
        ad_id=str(item.get("id") or ""),
        online=_online(item),
    )


def _badge_titles(item: dict) -> list[str]:
    badge_info = item.get("badgeInfo") or {}
    titles = []
    for badge in badge_info.get("badgeList") or []:
        title = badge.get("title") or badge.get("hoverKey")
        if title:
            titles.append(str(title))
    return titles


def _online(item: dict) -> bool | None:
    status = item.get("userActiveStatusVo") or {}
    if "online" in status:
        return bool(status.get("online"))
    return None


class Okx:
    code = "okx"
    name = "欧易"

    def fetch(self, client, pages: int) -> list[Quote]:
        del pages  # 欧易这一接口一次返回当前公开盘口，没有分页参数。
        quotes: list[Quote] = []
        for user_side, ad_side, book_key in (
            ("buy", "sell", "sell"),
            ("sell", "buy", "buy"),
        ):
            body = client.get_json(URL.format(side=ad_side), HEADERS)
            if body.get("code") not in (0, "0"):
                raise RuntimeError(f"欧易返回异常: {body.get('msg') or body.get('code')}")
            rows = (body.get("data") or {}).get(book_key) or []
            for item in rows:
                quote = parse_okx_ad(item, user_side)
                if quote is not None:
                    quotes.append(quote)
        return quotes
