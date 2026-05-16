# TrendMaestro — EMA金叉趋势跟踪 + ATR动态止损
# 快线穿越慢线进场 · 反向穿越平仓 · ATR移动止损
# BTC/USDT:USDT 15m

import numpy as np
from pandas import DataFrame

from freqtrade.strategy import IStrategy, IntParameter, DecimalParameter
import talib.abstract as ta


class TrendMaestroStrategy(IStrategy):
    INTERFACE_VERSION = 3
    can_short: bool = True

    timeframe = "15m"
    process_only_new_candles = True
    use_exit_signal = True
    exit_profit_only = False

    # 固定止损 30% 保底 + trailing锁利润
    stoploss = -0.30
    minimal_roi = {}
    trailing_stop = True
    trailing_stop_positive = 0.03
    trailing_stop_positive_offset = 0.07
    trailing_only_offset_is_reached = True

    startup_candle_count = 100

    # ── EMA 参数 ──
    ema_fast = IntParameter(7, 13, default=10, space="buy")
    ema_slow = IntParameter(25, 55, default=40, space="buy")

    # ── ATR 止损倍数 ──
    atr_period = IntParameter(10, 30, default=14, space="sell")
    atr_mult = DecimalParameter(1.5, 4.0, default=2.5, decimals=1, space="sell")

    # ── 信号 ──
    order_types = {
        "entry": "limit",
        "exit": "limit",
        "stoploss": "market",
        "stoploss_on_exchange": False,
    }

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # ═══ EMA ═══
        dataframe["ema_fast"] = ta.EMA(dataframe, timeperiod=self.ema_fast.value)
        dataframe["ema_slow"] = ta.EMA(dataframe, timeperiod=self.ema_slow.value)

        # ═══ ATR ═══
        dataframe["atr"] = ta.ATR(dataframe, timeperiod=self.atr_period.value)

        # ═══ 金叉/死叉 ═══
        fast, slow = dataframe["ema_fast"], dataframe["ema_slow"]
        prev_fast, prev_slow = fast.shift(1), slow.shift(1)

        dataframe["golden_cross"] = (prev_fast <= prev_slow) & (fast > slow)
        dataframe["dead_cross"] = (prev_fast >= prev_slow) & (fast < slow)

        # ═══ ADX 趋势强度 (可选过滤) ═══
        dataframe["adx"] = ta.ADX(dataframe, timeperiod=14)

        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # 金叉做多: EMA快线上穿慢线 + ADX>20 (有趋势)
        dataframe.loc[
            dataframe["golden_cross"]
            & (dataframe["adx"] > 20)
            & (dataframe["volume"] > 0),
            "enter_long",
        ] = 1

        # 死叉做空
        dataframe.loc[
            dataframe["dead_cross"]
            & (dataframe["adx"] > 20)
            & (dataframe["volume"] > 0),
            "enter_short",
        ] = 1

        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # 平多: 死叉 (快线下穿慢线)
        dataframe.loc[
            dataframe["dead_cross"] & (dataframe["volume"] > 0),
            "exit_long",
        ] = 1

        # 平空: 金叉
        dataframe.loc[
            dataframe["golden_cross"] & (dataframe["volume"] > 0),
            "exit_short",
        ] = 1

        return dataframe

    # ── ATR 移动止损 ──
    def custom_stoploss(
        self,
        pair: str,
        trade: "Trade",
        current_time: "datetime",
        current_rate: float,
        current_profit: float,
        after_fill: bool,
        **kwargs,
    ) -> float | None:
        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if dataframe is None or len(dataframe) == 0:
            return None

        last_candle = dataframe.iloc[-1]
        atr = last_candle.get("atr", 0)
        if atr is None or atr <= 0:
            return None

        atr_stop_dist = atr * self.atr_mult.value

        if trade.is_short:
            # 空单: 止损在 entry + ATR*n
            stop_price = trade.open_rate + atr_stop_dist
            sl = (stop_price / current_rate) - 1
            return min(sl, -0.001)  # 至少0.1%
        else:
            # 多单: 止损在 entry - ATR*n
            stop_price = trade.open_rate - atr_stop_dist
            sl = (stop_price / current_rate) - 1
            return min(sl, -0.001)
