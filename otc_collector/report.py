import statistics
from collections import defaultdict

from otc_collector.models import Quote

_SIDE_LABEL = {"buy": "买入USDT", "sell": "卖出USDT"}
_EXCHANGE_ORDER = {"binance": 0, "okx": 1, "htx": 2, "bitget": 3}
TOP_MERCHANTS = 5
TRADE_AMOUNT_CNY = 100_000
TRADE_PAYMENTS = ("银行卡", "支付宝")
TRADE_LABEL = "10 万元 · 银行卡或支付宝"


def display_width(text: str) -> int:
    return sum(2 if ord(char) > 127 else 1 for char in text)


def pad(text: str, width: int) -> str:
    return text + " " * max(0, width - display_width(text))


def accepts_trade(quote: Quote, amount: float = TRADE_AMOUNT_CNY, payments: tuple[str, ...] = TRADE_PAYMENTS) -> bool:
    """10 万元能下进去，并且支持银行卡或支付宝。限额未知的广告不参与比价。"""
    if quote.min_cny is None and quote.max_cny is None:
        return False
    if quote.min_cny is not None and quote.min_cny > amount:
        return False
    if quote.max_cny is not None and quote.max_cny < amount:
        return False
    allowed = set(payments)
    return any(name in allowed for name in quote.payments)


def summarize(quotes: list[Quote]) -> list[dict]:
    """每个交易所、每种支付方式各算一对买卖价。买入价必须高于卖出价。"""
    by_exchange: dict[str, list[Quote]] = defaultdict(list)
    for quote in quotes:
        by_exchange[quote.exchange].append(quote)
    rows = []
    for exchange in sorted(by_exchange, key=lambda code: _EXCHANGE_ORDER.get(code, 9)):
        for payment, buy, sell, buy_ads, sell_ads in _rails(by_exchange[exchange]):
            for side, quote, ads in (("buy", buy, buy_ads), ("sell", sell, sell_ads)):
                if quote is None:
                    continue
                ordered = sorted(ads, key=lambda item: item.price, reverse=(side == "sell"))
                top = ordered[:10]
                rows.append(
                    {
                        "exchange": exchange,
                        "exchange_name": quote.exchange_name,
                        "side": side,
                        "payment": payment,
                        "count": len(ads),
                        "best": quote.price,
                        "median10": statistics.median(item.price for item in top),
                        "merchant": quote.merchant_name,
                        "tier": quote.merchant_tier,
                        "payments": payment,
                    }
                )
    return rows


def _rails(quotes: list[Quote]) -> list[tuple[str, Quote | None, Quote | None, list[Quote], list[Quote]]]:
    books: dict[str, list[Quote]] = {payment: [] for payment in TRADE_PAYMENTS}
    for quote in quotes:
        if not accepts_trade(quote):
            continue
        for payment in TRADE_PAYMENTS:
            if payment in quote.payments:
                books[payment].append(quote)
    rails = []
    for payment in TRADE_PAYMENTS:
        ads = books[payment]
        buys = [quote for quote in ads if quote.side == "buy"]
        sells = [quote for quote in ads if quote.side == "sell"]
        buy, sell = _separated(buys, sells)
        if buy is None and sell is None:
            continue
        rails.append((payment, buy, sell, buys, sells))
    return rails


def _separated(buys: list[Quote], sells: list[Quote]) -> tuple[Quote | None, Quote | None]:
    """丢掉让买入价小于或等于卖出价的那一层，直到买入更贵，或某一边空了。"""
    buys = sorted(buys, key=lambda quote: (quote.price, quote.ad_id))
    sells = sorted(sells, key=lambda quote: (-quote.price, quote.ad_id))
    buy_index = sell_index = 0
    while (
        buy_index < len(buys)
        and sell_index < len(sells)
        and _cents(buys[buy_index].price) <= _cents(sells[sell_index].price)
    ):
        buy_level = _cents(buys[buy_index].price)
        sell_level = _cents(sells[sell_index].price)
        while buy_index < len(buys) and _cents(buys[buy_index].price) == buy_level:
            buy_index += 1
        while sell_index < len(sells) and _cents(sells[sell_index].price) == sell_level:
            sell_index += 1
    buy = buys[buy_index] if buy_index < len(buys) else None
    sell = sells[sell_index] if sell_index < len(sells) else None
    return buy, sell


def _cents(price: float) -> float:
    return round(price, 4)


def top_merchants_by_orders(quotes: list[Quote], limit: int = TOP_MERCHANTS) -> list[dict]:
    """每个交易所按成交单数取出认证商家。报价入库前已经滤掉未认证用户。"""
    grouped: dict[tuple[str, str], dict] = {}
    for quote in quotes:
        if not accepts_trade(quote):
            continue
        identity = quote.merchant_id or quote.merchant_name
        key = (quote.exchange, identity)
        bucket = grouped.get(key)
        if bucket is None:
            bucket = {
                "exchange": quote.exchange,
                "exchange_name": quote.exchange_name,
                "merchant_name": quote.merchant_name,
                "tier": quote.merchant_tier,
                "orders": quote.month_orders,
                "order_window": quote.order_window,
                "completion_rate": quote.completion_rate,
                "buy": None,
                "sell": None,
            }
            grouped[key] = bucket
        elif _rank_value(quote.month_orders) > _rank_value(bucket["orders"]):
            bucket["merchant_name"] = quote.merchant_name
            bucket["tier"] = quote.merchant_tier
            bucket["orders"] = quote.month_orders
            bucket["order_window"] = quote.order_window
            bucket["completion_rate"] = quote.completion_rate
        if quote.side == "buy" and (bucket["buy"] is None or quote.price < bucket["buy"]):
            bucket["buy"] = quote.price
        if quote.side == "sell" and (bucket["sell"] is None or quote.price > bucket["sell"]):
            bucket["sell"] = quote.price

    by_exchange: dict[str, list[dict]] = defaultdict(list)
    for bucket in grouped.values():
        by_exchange[bucket["exchange"]].append(bucket)
    groups = []
    for exchange in sorted(by_exchange, key=lambda code: _EXCHANGE_ORDER.get(code, 9)):
        ranked = sorted(
            by_exchange[exchange],
            key=lambda item: (
                item["orders"] is not None,
                item["orders"] or 0,
                item["completion_rate"] or 0,
            ),
            reverse=True,
        )
        groups.append(
            {
                "exchange": exchange,
                "exchange_name": ranked[0]["exchange_name"],
                "merchants": ranked[:limit],
            }
        )
    return groups


def format_top_merchants(quotes: list[Quote], limit: int = TOP_MERCHANTS) -> str:
    blocks = []
    for group in top_merchants_by_orders(quotes, limit):
        merchants = group["merchants"]
        window = merchants[0]["order_window"] if _same_window(merchants) else ""
        title = f"{group['exchange_name']} 成交单数 Top {len(merchants)}"
        if window:
            title += f"（{window}）"
        lines = [title]
        for index, merchant in enumerate(merchants, start=1):
            orders = "单数未知" if merchant["orders"] is None else f"{merchant['orders']}单"
            if merchant["order_window"] and not window:
                orders += f"({merchant['order_window']})"
            rate = "—" if merchant["completion_rate"] is None else f"{merchant['completion_rate']:.2f}%"
            lines.append(
                f"{index}. {merchant['merchant_name']}  {merchant['tier']}  {orders}"
                f"  完成率 {rate}  买 {_price_text(merchant['buy'])} / 卖 {_price_text(merchant['sell'])}"
            )
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def format_summary(quotes: list[Quote], collected_at: str) -> str:
    rows = summarize(quotes)
    if not rows:
        if quotes:
            return f"{collected_at} 没有符合{TRADE_LABEL}的广告。"
        return f"{collected_at} 没有采到认证商家广告。"
    header = ("交易所", "方向", "最优价", "前10中位", "广告数", "最优商家", "等级")
    body = [
        (
            f"{row['exchange_name']} · {row['payment']}",
            _SIDE_LABEL[row["side"]],
            f"{row['best']:.4f}",
            f"{row['median10']:.4f}",
            str(row["count"]),
            row["merchant"],
            row["tier"],
        )
        for row in rows
    ]
    widths = [
        max(display_width(header[index]), *(display_width(line[index]) for line in body))
        for index in range(len(header))
    ]
    lines = [
        f"USDT/CNY 认证商家  {collected_at}",
        "买入USDT = 你付人民币、商家卖币，价格越低越好。卖出USDT = 你卖币收人民币，价格越高越好。",
        f"最优价只看能交易 {TRADE_LABEL} 的广告，买卖分开支付方式，买入价必须高于卖出价。",
        "  ".join(pad(title, widths[index]) for index, title in enumerate(header)),
    ]
    lines.extend("  ".join(pad(line[index], widths[index]) for index in range(len(header))) for line in body)
    merchants = format_top_merchants(quotes)
    if merchants:
        lines.extend(["", merchants])
    return "\n".join(lines)


def format_details(quotes: list[Quote], limit: int) -> str:
    grouped: dict[tuple[str, str, str], list[Quote]] = defaultdict(list)
    for quote in quotes:
        grouped[(quote.exchange, quote.exchange_name, quote.side)].append(quote)
    blocks = []
    ordered_groups = sorted(grouped.items(), key=lambda item: (_EXCHANGE_ORDER.get(item[0][0], 9), item[0][2]))
    for (_code, name, side), items in ordered_groups:
        ordered = sorted(items, key=lambda quote: quote.price, reverse=(side == "sell"))[:limit]
        blocks.append(f"\n{name} {_SIDE_LABEL[side]} 前 {len(ordered)} 条")
        for index, quote in enumerate(ordered, start=1):
            limits = _limits(quote)
            rate = "-" if quote.completion_rate is None else f"{quote.completion_rate:.2f}%"
            orders = "-" if quote.month_orders is None else f"{quote.month_orders}({quote.order_window})"
            blocks.append(
                f"{index:>2}. {quote.price:.4f}  {quote.merchant_tier} {quote.merchant_name}"
                f"  限额 {limits}  支付 {'、'.join(quote.payments) or '-'}  完成率 {rate}  单数 {orders}"
            )
    return "\n".join(blocks)


def _rank_value(orders: int | None) -> int:
    return -1 if orders is None else orders


def _same_window(merchants: list[dict]) -> bool:
    windows = {merchant["order_window"] for merchant in merchants}
    return len(windows) == 1 and bool(next(iter(windows)))


def _price_text(price: float | None) -> str:
    if price is None:
        return "—"
    return f"{price:.4f}"


def _limits(quote: Quote) -> str:
    if quote.min_cny is None and quote.max_cny is None:
        return "-"
    left = "-" if quote.min_cny is None else f"{quote.min_cny:.0f}"
    right = "-" if quote.max_cny is None else f"{quote.max_cny:.0f}"
    return f"{left}-{right} CNY"
