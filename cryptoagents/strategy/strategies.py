from __future__ import annotations

from .base import BaseStrategy, Signal, StrategyType

strategies = {}


def _make(cls, sid, stype):
    s = cls()
    s.strategy_type = stype
    s.params = dict(_DEFAULT_PARAMS_LOCAL.get(sid, {}))
    strategies[sid] = s
    return s


_DEFAULT_PARAMS_LOCAL = {
    "S1": {"fast": 6, "slow": 18, "sl_pct": 2.0, "tp_pct": 6.0, "sep": 0.03},
    "S2": {"period": 7, "oversold": 40, "overbought": 60, "sl_pct": 2.0, "tp_pct": 4.0},
    "S3": {"vol_mult": 1.1, "sl_pct": 2.0, "tp_pct": 5.0},
    "S4": {"rsi_thresh": 30, "drop_pct": 2.0, "sl_pct": 3.0, "tp_pct": 6.0},
    "S5": {"ema_period": 14, "sl_pct": 1.5, "tp_pct": 4.0},
    "S6": {"td_count": 7, "sl_pct": 1.5, "tp_pct": 4.0},
}

class S1EMATrend(BaseStrategy):
    """双EMA趋势追随: EMA快慢线金叉死叉 + MACD确认 + 趋势对齐 + 成交量过滤。"""
    def name(self): return "双EMA趋势追随"
    def strategy_id(self): return "S1"
    def timeframe(self): return "15m"

    def calculate(self, df) -> Signal:
        p = self.params
        fast_p = int(p.get("fast", 7)); slow_p = int(p.get("slow", 21))
        e1 = self._ema(df["close"], fast_p); e2 = self._ema(df["close"], slow_p)
        d, dea, h = self._macd(df)
        gc = (e1 > e2) & (e1.shift(1) <= e2.shift(1))
        dc = (e1 < e2) & (e1.shift(1) >= e2.shift(1))
        sp = abs(e1 - e2) / e2 * 100
        sep = float(p.get("sep", 0.05))
        sl = float(p.get("sl_pct", 1.5)); tp = float(p.get("tp_pct", 3.0))
        if gc.iloc[-1] and sp.iloc[-1] > sep:
            if not self._trend_filter(df, "LONG"): return Signal("HOLD", strategy="S1")
            if not self._vol_filter(df, 0.7): return Signal("HOLD", strategy="S1")
            return Signal("BUY", "STRONG", "S1", "LONG", stop_loss_pct=sl, take_profit_pct=tp)
        if dc.iloc[-1] and sp.iloc[-1] > sep:
            if not self._trend_filter(df, "SHORT"): return Signal("HOLD", strategy="S1")
            if not self._vol_filter(df, 0.7): return Signal("HOLD", strategy="S1")
            return Signal("SELL", "STRONG", "S1", "SHORT", stop_loss_pct=sl, take_profit_pct=tp)
        return Signal("HOLD", strategy="S1")


class S2RSIReversal(BaseStrategy):
    def name(self): return "RSI均值回归"
    def strategy_id(self): return "S2"
    def timeframe(self): return "15m"

    def calculate(self, df) -> Signal:
        p = self.params
        r = self._rsi(df, int(p.get("period", 7)))
        os_ = float(p.get("oversold", 30)); ob = float(p.get("overbought", 70))
        sl = float(p.get("sl_pct", 1.2)); tp = float(p.get("tp_pct", 2.4))
        # S2是均值回归, 不做趋势过滤
        if r.iloc[-1] < os_:
            return Signal("BUY", "STRONG", "S2", "LONG", stop_loss_pct=sl, take_profit_pct=tp)
        if r.iloc[-1] > ob:
            return Signal("SELL", "STRONG", "S2", "SHORT", stop_loss_pct=sl, take_profit_pct=tp)
        return Signal("HOLD", strategy="S2")


class S3MACDResonance(BaseStrategy):
    def name(self): return "MACD多维度共振"
    def strategy_id(self): return "S3"
    def timeframe(self): return "15m"

    def calculate(self, df) -> Signal:
        p = self.params
        d, dea, h = self._macd(df)
        sl = float(p.get("sl_pct", 1.5)); tp = float(p.get("tp_pct", 3.0))
        vm = float(p.get("vol_mult", 1.3))
        bull = d.iloc[-1] > dea.iloc[-1] and h.iloc[-1] > h.iloc[-2]
        bear = d.iloc[-1] < dea.iloc[-1] and h.iloc[-1] < h.iloc[-2]
        vs = df["volume"].iloc[-1] > df["volume"].rolling(20).mean().iloc[-1] * vm
        if bull and vs:
            if not self._trend_filter(df, "LONG"): return Signal("HOLD", strategy="S3")
            return Signal("BUY", "STRONG", "S3", "LONG", stop_loss_pct=sl, take_profit_pct=tp)
        if bear and vs:
            if not self._trend_filter(df, "SHORT"): return Signal("HOLD", strategy="S3")
            return Signal("SELL", "STRONG", "S3", "SHORT", stop_loss_pct=sl, take_profit_pct=tp)
        return Signal("HOLD", strategy="S3")


class S4Martingale(BaseStrategy):
    def name(self): return "马丁逆势反弹"
    def strategy_id(self): return "S4"
    def timeframe(self): return "15m"

    def calculate(self, df) -> Signal:
        p = self.params
        r = self._rsi(df, 7)
        pr = float(df["close"].iloc[-1])
        ps = float(df["close"].shift(5).iloc[-1])
        dp = (pr - ps) / ps * 100
        rt = float(p.get("rsi_thresh", 28)); dpt = float(p.get("drop_pct", 2.5))
        sl = float(p.get("sl_pct", 3.0)); tp = float(p.get("tp_pct", 5.0))
        if r.iloc[-1] < rt and dp < -dpt:
            return Signal("BUY", "STRONG", "S4", "LONG", stop_loss_pct=sl, take_profit_pct=tp)
        if r.iloc[-1] > (100-rt) and dp > dpt:
            return Signal("SELL", "STRONG", "S4", "SHORT", stop_loss_pct=sl, take_profit_pct=tp)
        return Signal("HOLD", strategy="S4")


class S5EMAScalping(BaseStrategy):
    def name(self): return "EMA刮头皮"
    def strategy_id(self): return "S5"
    def timeframe(self): return "15m"

    def calculate(self, df) -> Signal:
        p = self.params
        sl = float(p.get("sl_pct", 2.0)); tp = float(p.get("tp_pct", 5.0))
        up, mid, low = self._boll(df, 20)
        r = self._rsi(df, 7)
        price = float(df["close"].iloc[-1])
        prev = float(df["close"].shift(1).iloc[-1])
        # 布林带下轨附近 + RSI不极端 + 收盘上涨 = 反弹买入
        if price <= mid.iloc[-1] and r.iloc[-1] < 50 and price > prev:
            if not self._vol_filter(df, 0.6): return Signal("HOLD", strategy="S5")
            # 动态止损: 使用布林带下轨作为止损参考
            dyn_sl = max(sl, abs(price - low.iloc[-1]) / price * 100)
            return Signal("BUY", "MEDIUM", "S5", "LONG", stop_loss_pct=min(dyn_sl, sl * 1.5), take_profit_pct=tp)
        # 布林带上轨附近 + RSI不极端 + 收盘下跌 = 回调卖出
        if price >= mid.iloc[-1] and r.iloc[-1] > 50 and price < prev:
            if not self._vol_filter(df, 0.6): return Signal("HOLD", strategy="S5")
            dyn_sl = max(sl, abs(up.iloc[-1] - price) / price * 100)
            return Signal("SELL", "MEDIUM", "S5", "SHORT", stop_loss_pct=min(dyn_sl, sl * 1.5), take_profit_pct=tp)
        return Signal("HOLD", strategy="S5")


class S6TD9(BaseStrategy):
    def name(self): return "TD9超买超卖"
    def strategy_id(self): return "S6"
    def timeframe(self): return "15m"

    def calculate(self, df) -> Signal:
        p = self.params
        tc = int(p.get("td_count", 8))
        sl = float(p.get("sl_pct", 1.2)); tp = float(p.get("tp_pct", 3.0))
        b = self._td(df, "buy"); s_ = self._td(df, "sell")
        if b >= tc:
            if not self._trend_filter(df, "LONG"): return Signal("HOLD", strategy="S6")
            return Signal("BUY", "STRONG", "S6", "LONG", stop_loss_pct=sl, take_profit_pct=tp)
        if s_ >= tc:
            if not self._trend_filter(df, "SHORT"): return Signal("HOLD", strategy="S6")
            return Signal("SELL", "STRONG", "S6", "SHORT", stop_loss_pct=sl, take_profit_pct=tp)
        return Signal("HOLD", strategy="S6")

    def _td(self, df, direction):  # noqa: A003
        c = 0; n = len(df)
        for i in range(max(4, n - 13), n):
            ci, c4 = df["close"].iloc[i], df["close"].iloc[i - 4]
            if direction == "buy" and ci < c4: c += 1
            elif direction == "sell" and ci > c4: c += 1
            else: c = 0
        return c


class CustomStrategy(BaseStrategy):
    def __init__(self, sid: str, name: str, base_type: str, params: dict):
        self._id = sid; self._name = name
        self.base_type = base_type; self.params = params or {}

    def name(self): return self._name
    def strategy_id(self): return self._id
    def timeframe(self): return self.params.get("timeframe", "15m")

    def calculate(self, df) -> Signal:
        p = self.params
        sl = float(p.get("sl_pct", 1.5)); tp = float(p.get("tp_pct", 2.5))
        bt = self.base_type

        if bt == "ema_cross":
            fast = self._ema(df["close"], int(p.get("fast", 7)))
            slow = self._ema(df["close"], int(p.get("slow", 21)))
            gc = (fast > slow) & (fast.shift(1) <= slow.shift(1))
            dc = (fast < slow) & (fast.shift(1) >= slow.shift(1))
            if gc.iloc[-1] and self._trend_filter(df, "LONG"):
                return Signal("BUY", "STRONG", self._id, "LONG", stop_loss_pct=sl, take_profit_pct=tp)
            if dc.iloc[-1] and self._trend_filter(df, "SHORT"):
                return Signal("SELL", "STRONG", self._id, "SHORT", stop_loss_pct=sl, take_profit_pct=tp)

        elif bt == "rsi":
            r = self._rsi(df, int(p.get("period", 14)))
            osv = float(p.get("oversold", 30)); ob = float(p.get("overbought", 70))
            if r.iloc[-1] < osv and self._trend_filter(df, "LONG"):
                return Signal("BUY", "STRONG", self._id, "LONG", stop_loss_pct=sl, take_profit_pct=tp)
            if r.iloc[-1] > ob and self._trend_filter(df, "SHORT"):
                return Signal("SELL", "STRONG", self._id, "SHORT", stop_loss_pct=sl, take_profit_pct=tp)

        elif bt == "macd":
            d, dea, h = self._macd(df)
            gc = d.iloc[-1] > dea.iloc[-1] and d.iloc[-2] <= dea.iloc[-2]
            dc = d.iloc[-1] < dea.iloc[-1] and d.iloc[-2] >= dea.iloc[-2]
            if gc and self._trend_filter(df, "LONG"):
                return Signal("BUY", "STRONG", self._id, "LONG", stop_loss_pct=sl, take_profit_pct=tp)
            if dc and self._trend_filter(df, "SHORT"):
                return Signal("SELL", "STRONG", self._id, "SHORT", stop_loss_pct=sl, take_profit_pct=tp)

        elif bt == "boll":
            up, mid, low = self._boll(df, int(p.get("period", 20)))
            price = float(df["close"].iloc[-1])
            if price <= low.iloc[-1] and self._trend_filter(df, "LONG"):
                return Signal("BUY", "MEDIUM", self._id, "LONG", stop_loss_pct=sl, take_profit_pct=tp)
            if price >= up.iloc[-1] and self._trend_filter(df, "SHORT"):
                return Signal("SELL", "MEDIUM", self._id, "SHORT", stop_loss_pct=sl, take_profit_pct=tp)

        return Signal("HOLD", strategy=self._id)


def _register():
    _make(S1EMATrend, "S1", StrategyType.S1_EMA_TREND)
    _make(S2RSIReversal, "S2", StrategyType.S2_RSI_REVERSAL)
    _make(S3MACDResonance, "S3", StrategyType.S3_MACD_RESONANCE)
    _make(S4Martingale, "S4", StrategyType.S4_MARTINGALE)
    _make(S5EMAScalping, "S5", StrategyType.S5_EMA_SCALPING)
    _make(S6TD9, "S6", StrategyType.S6_TD9_EXTREME)

_register()

_DESCRIPTIONS = {
    "S1": "强趋势 · EMA金叉+趋势对齐+量能",
    "S2": "震荡 · RSI回归+趋势过滤",
    "S3": "转折 · MACD共振+放量+趋势",
    "S4": "急跌反弹 · RSI极端+趋势+带止损",
    "S5": "温和趋势 · EMA触碰+趋势+量能",
    "S6": "极端行情 · TD序列+趋势过滤",
}

_custom: dict[str, CustomStrategy] = {}

def register_custom(sid, name, base_type, params):
    cs = CustomStrategy(sid, name, base_type, params)
    _custom[sid] = cs; strategies[sid] = cs; return cs

def unregister_custom(sid):
    _custom.pop(sid, None); strategies.pop(sid, None)

def get_strategy(sid):
    if sid not in strategies: raise ValueError(f"未知策略: {sid}")
    return strategies[sid]

def list_strategies():
    out = []
    for s in strategies.values():
        sid = s.strategy_id()
        out.append({"id": sid, "name": s.name(), "timeframe": s.timeframe(),
                     "desc": _DESCRIPTIONS.get(sid, "自定义策略"), "custom": sid in _custom})
    return out
