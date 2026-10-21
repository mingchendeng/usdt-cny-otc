from otc_collector.models import Quote, as_int, as_percent, num, ratio_to_percent, valid_price
from otc_collector.payments import payment_names

URL = "https://www.bitget.com/v1/p2p/pub/adv/queryAdvList"
HEADERS = {
    "Origin": "https://www.bitget.com",
    "Referer": "https://www.bitget.com/zh-CN/p2p-trade",
    "language": "zh_CN",
    "locale": "zh-CN",
}

# certifiedMerchant 为 0 是未认证用户。1 和 2 都是平台认证商家，等级文案在 gradeName。
_GRADES = {
    "Advanced": "进阶商家",
    "Master": "顶级商家",
    "Ordinary": "认证商家",
    "Certified": "认证商家",
    "认证商家": "认证商家",
    "进阶商家": "进阶商家",
    "顶级商家": "顶级商家",
}


def parse_bitget_ad(item: dict) -> Quote | None:
    try:
        certified = int(item.get("certifiedMerchant"))
    except (TypeError, ValueError):
        return None
    if certified <= 0:
        return None
    ad_type = item.get("adType")
    if ad_type == 2:
        user_side = "buy"
    elif ad_type == 1:
        user_side = "sell"
    else:
        return None
    price = valid_price(item.get("price"))
    if price is None:
        return None
    grades = [
        str(grade.get("gradeName"))
        for grade in (item.get("merchantGradeRespList") or [])
        if grade.get("gradeName")
    ]
    tier = _GRADES.get(grades[0], grades[0] if grades else "认证商家")
    month_orders = as_int(item.get("thirtyTunoverNum"))
    order_window = "30天"
    if month_orders is None:
        month_orders = as_int(item.get("turnoverNum"))
        order_window = "累计"
    completion = ratio_to_percent(item.get("thirtyCompletionRate"))
    if completion is None:
        completion = ratio_to_percent(item.get("turnoverRate"))
    return Quote(
        exchange="bitget",
        exchange_name="Bitget",
        side=user_side,
        price=price,
        available_usdt=num(item.get("lastAmount") if item.get("lastAmount") not in (None, "") else item.get("amount")),
        min_cny=num(item.get("minAmount")),
        max_cny=num(item.get("maxAmount")),
        payments=payment_names(item.get("paymethodInfo")),
        merchant_name=str(item.get("nickName") or "未知商家"),
        merchant_id=str(item.get("encryptUserId") or ""),
        merchant_tier=tier,
        month_orders=month_orders,
        order_window=order_window,
        completion_rate=completion,
        positive_rate=as_percent(item.get("goodEvaluationRate")),
        ad_id=str(item.get("adNo") or ""),
        online=item.get("showOnline") if isinstance(item.get("showOnline"), bool) else None,
    )


class Bitget:
    code = "bitget"
    name = "Bitget"

    def fetch(self, client, pages: int) -> list[Quote]:
        quotes: list[Quote] = []
        seen: set[str] = set()
        # side 1 拉商家卖单（用户买 USDT），side 2 拉商家买单（用户卖 USDT）。
        for request_side, expected_type in ((1, 2), (2, 1)):
            for page in range(1, pages + 1):
                payload = {
                    "side": request_side,
                    "coinCode": "USDT",
                    "fiatCode": "CNY",
                    "pageNo": page,
                    "pageSize": 20,
                    "languageType": 1,
                }
                body = client.post_json(URL, payload, HEADERS)
                if str(body.get("code")) != "00000":
                    raise RuntimeError(f"Bitget 返回异常: {body.get('msg') or body.get('code')}")
                data = body.get("data") or {}
                rows = data.get("dataList") or []
                if not rows:
                    break
                for item in rows:
                    if item.get("adType") not in (None, expected_type):
                        continue
                    quote = parse_bitget_ad(item)
                    if quote is None or quote.ad_id in seen:
                        continue
                    seen.add(quote.ad_id)
                    quotes.append(quote)
                if not data.get("hasNextPage"):
                    break
        return quotes
