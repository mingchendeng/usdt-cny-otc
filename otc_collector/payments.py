"""把各交易所的支付方式编码收成同一组中文名称。"""

_CANONICAL = {
    "bank": "银行卡",
    "banktransfer": "银行卡",
    "bankcard": "银行卡",
    "银行借记卡": "银行卡",
    "银行卡": "银行卡",
    "alipay": "支付宝",
    "支付宝": "支付宝",
    "wechat": "微信",
    "wechatpay": "微信",
    "wxpay": "微信",
    "微信": "微信",
    "qqwallet": "QQ钱包",
    "qq钱包": "QQ钱包",
}


def normalize_payment(raw: str) -> str:
    text = (raw or "").strip()
    if not text:
        return ""
    if text in _CANONICAL:
        return _CANONICAL[text]
    key = text.lower().replace("_", "").replace(" ", "").replace("-", "")
    return _CANONICAL.get(key, text)


def payment_names(value) -> tuple[str, ...]:
    raw_names: list[str] = []
    if isinstance(value, str):
        raw_names.append(value)
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, str):
                raw_names.append(item)
            elif isinstance(item, dict):
                raw_names.append(
                    str(
                        item.get("tradeMethodName")
                        or item.get("paymethodName")
                        or item.get("paymentMethodName")
                        or item.get("name")
                        or item.get("identifier")
                        or item.get("paymentMethod")
                        or ""
                    )
                )
    seen: list[str] = []
    for name in raw_names:
        canonical = normalize_payment(name)
        if canonical and canonical not in seen:
            seen.append(canonical)
    return tuple(seen)
