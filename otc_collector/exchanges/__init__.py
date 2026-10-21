from otc_collector.exchanges.binance import Binance
from otc_collector.exchanges.bitget import Bitget
from otc_collector.exchanges.htx import Htx
from otc_collector.exchanges.okx import Okx

EXCHANGES = {
    "binance": Binance(),
    "okx": Okx(),
    "htx": Htx(),
    "bitget": Bitget(),
}

ALIASES = {
    "binance": "binance",
    "币安": "binance",
    "okx": "okx",
    "欧易": "okx",
    "htx": "htx",
    "huobi": "htx",
    "火币": "htx",
    "bitget": "bitget",
}


def resolve_exchanges(names: list[str] | None):
    if not names:
        return list(EXCHANGES.values())
    selected = []
    unknown = []
    for name in names:
        code = ALIASES.get(name.strip().lower()) or ALIASES.get(name.strip())
        if code is None or code not in EXCHANGES:
            unknown.append(name)
            continue
        exchange = EXCHANGES[code]
        if exchange not in selected:
            selected.append(exchange)
    if unknown:
        known = "、".join(ALIASES)
        raise SystemExit(f"不认识的交易所: {', '.join(unknown)}。可选: {known}")
    return selected
