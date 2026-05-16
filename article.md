# 从零搭建一套自动运行的 Freqtrade 量化交易系统

> 2026年了，币圈还在靠盯盘做波段？不如让代码替你看盘。

我从零开始搭建了一套全自动的量化交易系统，7x24运行在首尔VPS上，Telegram推送每一笔成交。这篇文章把完整的技术方案写出来，不藏私。

本人 TG：@chovy2_suitrader_bot，有量化策略定制或 Freqtrade 部署需求欢迎联系。

---

## 技术栈

- **交易框架**：Freqtrade 2026.4（开源、Python、OKX合约支持）
- **策略**：EMA (10, 40) + ADX > 20 趋势过滤 + ATR 动态止损 + Trailing 止盈
- **部署**：Ubuntu 22.04 → systemd 自启 → 崩溃自动恢复
- **通知**：Telegram Bot（中文推送、支持 `/status` `/profit` 查询）
- **数据**：OKX BTC/USDT 15m K线，17个月历史回测
- **成本**：首尔 VPS $12/月

## 策略逻辑

### 进场条件

做多：EMA10 上穿 EMA40 + ADX > 20（确认趋势强度）
做空：EMA10 下穿 EMA40 + ADX > 20

ADX 过滤是关键——没有趋势的 K 线震荡是噪音，不值得入场。

### 出场逻辑

- ATR 动态止损（2.5倍ATR，随波动率自动调整）
- Trailing stop：浮盈 7% 启动，回撤 3% 锁利
- 反向交叉信号平仓

### 回测数据

参数：EMA (10, 40) + ADX > 20 + ATR 2.5x + trailing 7%/3%
数据：OKX BTC/USDT 15m，2024年1月—2025年5月

| 指标 | 数据 |
|------|------|
| 交易次数 | 522笔 |
| 胜率 | 30.7% |
| 总收益率 | +4.1% |
| 最大回撤 | -3.1% |
| 平均盈利 | +2.05% |
| 平均亏损 | -0.81% |
| 最高盈利 | +19.97% |
| 月胜率 | 64.7%（11/17） |

胜率看着不高？趋势跟踪策略本质就是小亏多次、大赚几次。盈亏比 2.5:1，数学期望为正。

## 部署要点

### 服务器选择

Vultr 首尔机房，1核2GB，$12/月。首尔到国内延迟 50-70ms，比新加坡快一倍。不要买 $6 的 1GB 方案——Freqtrade 启动就要 300MB+，需要留余量。

### 安装避坑

Ubuntu 22.04 默认 Python 3.10，Freqtrade 最新版需要 3.11+。必须加 deadsnakes PPA 装 Python 3.12。TA-Lib 需要源码编译，VPS 上大约 5-10 分钟。

### Telegram 通知

机器人 Token 用 @BotFather 生成。如果 VPS 直连 Telegram API 被拒，可更换 Token 或加代理解决。

### 运行保障

```bash
systemctl enable freqtrade   # 开机自启
journalctl -u freqtrade -f   # 实时日志
```

systemd 配置 `Restart=always`，崩溃 30 秒后自动恢复。

## 开源

所有策略代码已在 GitHub 开源：
https://github.com/hermes-agent-chovy/freqtrade-strategies

全自动部署方案文档：
https://github.com/hermes-agent-chovy/trading-bot-stack

---

有量策策略定制或 Freqtrade 部署需求，欢迎联系！
TG：@chovy2_suitrader_bot
