# RMI Trend Sniper — 完整移植 Pine Script v5
# 状态机: 信号触发→进入等待区→价格回踩动态线→开仓
# 动态线 = RWMA(20) ± Band(ATR/clamp)

import numpy as np
from pandas import DataFrame, Series
from datetime import datetime

from freqtrade.strategy import IStrategy, IntParameter, DecimalParameter
import talib.abstract as ta


class RmiTrendSniperStrategy(IStrategy):
    INTERFACE_VERSION = 3
    can_short: bool = True

    timeframe = "15m"
    process_only_new_candles = True
    use_exit_signal = True
    exit_profit_only = False

    stoploss = -0.15
    minimal_roi = {}
    use_custom_stoploss = False

    startup_candle_count = 150

    # ── RMI 参数 ──
    rmi_length = IntParameter(10, 20, default=14, space="buy")
    rmi_long_threshold = IntParameter(40, 75, default=55, space="buy")
    rmi_short_threshold = IntParameter(20, 50, default=30, space="buy")
    # ATR止损倍数
    atr_stop_mult = DecimalParameter(1.0, 3.0, default=2.0, decimals=1, space="sell")

    order_types = {
        "entry": "limit",
        "exit": "limit",
        "stoploss": "market",
        "stoploss_on_exchange": False,
    }

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        rmi_len = self.rmi_length.value
        rmi_thresh = self.rmi_long_threshold.value
        rmi_short = self.rmi_short_threshold.value

        # ═══ RMI + MFI (Pine Script 原版) ═══
        change = dataframe["close"].diff()
        up = self._rma(change.clip(lower=0), rmi_len)
        down = self._rma((-change).clip(lower=0), rmi_len)
        rsi = np.where(down == 0, 100, np.where(up == 0, 0, 100 - 100 / (1 + up / down)))
        mf = ta.MFI(dataframe, timeperiod=rmi_len)
        dataframe["rsi_mfi"] = (rsi + mf) / 2

        # ═══ EMA5 ═══
        dataframe["ema5"] = ta.EMA(dataframe, timeperiod=5)
        dataframe["ema5_rising"] = dataframe["ema5"] > dataframe["ema5"].shift(1)

        # ═══ 动量信号 (Pine Script p_mom / n_mom) ═══
        dataframe["p_mom"] = (
            (dataframe["rsi_mfi"].shift(1) < rmi_thresh)
            & (dataframe["rsi_mfi"] >= rmi_thresh)
            & (dataframe["rsi_mfi"] > rmi_short)
            & (dataframe["ema5_rising"])
        )
        dataframe["n_mom"] = (
            (dataframe["rsi_mfi"] < rmi_short)
            & (~dataframe["ema5_rising"])
        )

        # ═══ 状态机: positive / negative (Pine Script 原版逻辑) ═══
        # positive 一旦置 true，持续为 true 直到 n_mom 触发
        # negative 一旦置 true，持续为 true 直到 p_mom 触发
        positive = np.zeros(len(dataframe), dtype=bool)
        negative = np.zeros(len(dataframe), dtype=bool)
        pos_state = False
        neg_state = False
        for i in range(len(dataframe)):
            if dataframe["p_mom"].iloc[i]:
                pos_state = True
                neg_state = False
            if dataframe["n_mom"].iloc[i]:
                pos_state = False
                neg_state = True
            positive[i] = pos_state
            negative[i] = neg_state
        dataframe["positive"] = positive
        dataframe["negative"] = negative

        # ═══ 动态线 RWMA ± Band (Pine Script 原版) ═══
        bar_range = dataframe["high"] - dataframe["low"]

        # RWMA: 以 bar_range 为权重的 WMA
        weight = bar_range / bar_range.rolling(20).sum()
        dataframe["rwma"] = (dataframe["close"] * weight).rolling(20).sum() / weight.rolling(20).sum()

        # Band: min(ATR(30)*0.3, close*0.3%) [20] / 2 * 8
        atr30 = ta.ATR(dataframe, timeperiod=30)
        dataframe["atr"] = ta.ATR(dataframe, timeperiod=14)
        band_raw = np.minimum(atr30 * 0.3, dataframe["close"] * 0.003)
        dataframe["band"] = band_raw.shift(20) / 2 * 8

        # 动态支撑/压力线
        dataframe["dynamic_line"] = np.where(
            positive,
            dataframe["rwma"] - dataframe["band"],   # 做多时: 支撑线
            np.where(negative,
                dataframe["rwma"] + dataframe["band"], # 做空时: 压力线
                np.nan
            )
        )

        # ═══ 进场: 信号激活 + 价格回踩动态线 ═══
        dataframe["sig_long"] = (
            dataframe["positive"]
            & (dataframe["close"] <= dataframe["dynamic_line"])
            & (dataframe["volume"] > 0)
        )
        dataframe["sig_short"] = (
            dataframe["negative"]
            & (dataframe["close"] >= dataframe["dynamic_line"])
            & (dataframe["volume"] > 0)
        )

        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[dataframe["sig_long"], "enter_long"] = 1
        dataframe.loc[dataframe["sig_short"], "enter_short"] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # 平多: n_mom触发(动量翻空) 或 价格跌破ema5
        exit_long = dataframe["n_mom"] | (dataframe["close"] < dataframe["ema5"])
        dataframe.loc[exit_long & (dataframe["volume"] > 0), "exit_long"] = 1

        # 平空: p_mom触发(动量翻多) 或 价格突破ema5
        exit_short = dataframe["p_mom"] | (dataframe["close"] > dataframe["ema5"])
        dataframe.loc[exit_short & (dataframe["volume"] > 0), "exit_short"] = 1

        return dataframe

    def custom_stoploss(self, pair, trade, current_time, current_rate, current_profit, after_fill, **kwargs):
        """ATR动态止损: 从开仓价算 ATR * 倍数"""
        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if dataframe is None or len(dataframe) == 0:
            return self.stoploss

        last_candle = dataframe.iloc[-1]
        atr = last_candle.get("atr", 0)
        if atr is None or atr <= 0 or current_rate <= 0:
            return self.stoploss

        atr_pct = atr / current_rate
        sl = -atr_pct * self.atr_stop_mult.value
        # 不低于固定止损, 不高于 -0.5% (防噪音)
        return max(min(sl, -0.005), self.stoploss)

    # ── 工具函数 ──
    def _rma(self, series: Series, period: int) -> Series:
        """Wilder's RMA (与 Pine Script ta.rma 一致)"""
        alpha = 1.0 / period
        result = series.copy()
        result.iloc[:period] = np.nan
        result.iloc[period] = series.iloc[:period + 1].mean()
        for i in range(period + 1, len(series)):
            result.iloc[i] = alpha * series.iloc[i] + (1 - alpha) * result.iloc[i - 1]
        return result
