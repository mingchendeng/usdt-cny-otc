# USDT/CNY OTC 认证商家采集

采集币安、欧易、HTX、Bitget 上 **USDT 兑人民币** 的 OTC 广告，只保留平台认证商家。数据来自各家网站正在使用的公开盘口，不需要 API Key，也不下单。

采到的是广告报价，不是已经成交的价格。摘要里的最优价只按单价排序，不看限额和完成率。

## 交易所和筛选规则

| 交易所 | 保留 | 丢掉 |
| --- | --- | --- |
| 币安 | `userType = merchant` 的认证商家 | 普通用户 |
| 欧易 | 认证商家、钻石商家 | 未认证挂单 |
| HTX | 商家等级 2（认证商家）、3（超级商家） | 等级 0、1 |
| Bitget | `certifiedMerchant` 为 1 或 2 | 未认证（0） |

方向按用户来记：

- `buy` / 买入USDT：你付人民币，看的是商家卖单，价格越低越好。
- `sell` / 卖出USDT：你卖 USDT 收人民币，看的是商家买单，价格越高越好。

Bybit、KuCoin 的公开接口目前没有人民币盘。Gate 的市场广告列表需要商家 API Key，没有稳定的未登录接口，所以这三家没有接入。

## 运行

需要 Python 3.11 或更新版本，只用标准库。在项目目录执行：

```bash
python -m otc_collector collect
python -m otc_collector show
python -m otc_collector show --detail 5
python -m otc_collector export data/latest.csv
```

常用参数：

```bash
python -m otc_collector collect --exchanges 币安,欧易 --pages 2
python -m otc_collector collect --pages 0 --max-pages 40
python -m otc_collector collect --loop 120
```

`--pages` 是每个方向最多翻几页，默认 3 页。欧易这个接口没有分页，一次返回当前公开盘口。`--loop` 最少 30 秒。报价写在 `data/otc.sqlite`。

成交单数的口径不一样，CSV 里的「单数口径」会标明：

- 币安、HTX、Bitget：近 30 天（Bitget 没有 30 天字段时用累计）
- 欧易：累计完成单

请把请求间隔留在默认的 0.6 秒或更长。这些是网页盘口接口，打太快会被限流。

## 推送到飞书卡片

采集结束后可以把摘要发到飞书群或 Lark 群。用群里的自定义机器人 Webhook，不需要企业应用。

1. 打开群设置，添加「自定义机器人」，复制 Webhook。
2. 国际版 Lark 的地址是 `open.larksuite.com`，国内飞书是 `open.feishu.cn`，两种都能用。
3. 如果开启了签名校验，把密钥也存下来。没开启就不用填。

本地：

```bash
cp .env.example .env
# 编辑 .env，填入 LARK_WEBHOOK_URL
python -m otc_collector collect --lark
python -m otc_collector notify
```

`notify` 不重新采集，只把最近一轮已入库的结果再发一次。每个交易所单独一张卡片：上方是买入价、卖出价和价差，下面是该交易所成交单数最高的 5 个认证商家。某一家失败时，那一张卡片是红色，并写上原因。

Webhook 只从环境变量或 `.env` 读取，不要写进代码或提交到仓库。

本地也可以把最近一轮写成静态页，看 `site/index.html`：

```bash
python -m otc_collector site
```

## 放在 GitHub 上

代码放在公开仓库里，用 GitHub Free 托管。静态页用 GitHub Pages。GitHub Free 的 Pages 只覆盖公开仓库，所以这个仓库保持公开。

采集、飞书推送和页面发布都在 GitHub Actions 里完成。`.github/workflows/collect.yml` 每小时采集一轮，写成 `index.html` 和 `quotes.json`，再发布到 Pages。生成的页面不进 Git。公开仓库的 Actions 分钟数不计入私有仓库的免费额度。

推送代码之后：

1. 仓库 Settings → Pages，Source 选 GitHub Actions。
2. Settings → Secrets and variables → Actions，新建 `LARK_WEBHOOK_URL`。开了签名校验再新建 `LARK_WEBHOOK_SECRET`。不发飞书就可以不填，页面照样发布。
3. 推到 `main` 会自动跑一轮。也可以到 Actions 页手动跑 `collect-otc`。完成后页面在 `https://<用户名>.github.io/usdt-cny-otc/`。

定时任务是每小时第 5 分钟。GitHub 可能会晚几分钟到几十分钟。交易所有时会拦数据中心 IP，第一次要看日志里四家是否都成功。
