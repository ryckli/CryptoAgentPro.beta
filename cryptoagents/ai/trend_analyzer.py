from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from app.core.config import settings
from cryptoagents.data.indicator_calc import compute_all_indicators
from cryptoagents.data.kline_converter import KlineConverter

DEEPSEEK_SYSTEM_PROMPT = """你是加密货币技术分析师。根据F/S/L/H格式K线和技术指标判断市场状态。
状态: STRONG_BULL, STRONG_BEAR, WEAK_BULL, WEAK_BEAR, RANGING, CRASH_BOUNCE, PUMP_REVERSAL, TREND_CHANGE
策略: S1=强趋势 S2=震荡 S3=转折 S4=马丁 S5=刮头皮 S6=TD9
输出严格JSON: {"market_state":"...","confidence":0.5,"recommended_strategy":"S1","reasoning":"...","risk_level":"MEDIUM","suggested_leverage":5,"key_levels":{"support":0,"resistance":0}}"""

_converter = KlineConverter()


@dataclass
class TrendResult:
    market_state: str = "RANGING"
    confidence: float = 0.5
    recommended_strategy: str = "S2"
    reasoning: str = ""
    risk_level: str = "MEDIUM"
    suggested_leverage: int = 5
    key_levels: dict = field(default_factory=dict)
    position_action: str = "NONE"
    position_reason: str = ""
    error: bool = False

    def to_dict(self): return {k: v for k, v in self.__dict__.items()}


def analyze_trend(symbol: str, df_15m: pd.DataFrame, df_1h: pd.DataFrame | None = None,
                  position: dict | None = None) -> TrendResult:
    indicators = compute_all_indicators(df_15m)
    prompt = _build_prompt(symbol, df_15m, df_1h, indicators, position)
    raw = _call_deepseek(prompt)
    return _parse(raw)


def _build_prompt(symbol, df_15m, df_1h, indicators, position=None) -> str:
    k15 = "\n".join(k.to_standard_string() for k in _converter.convert_df_rows(df_15m, 20))
    k1h = ""
    if df_1h is not None and not df_1h.empty:
        k1h = "\n".join(k.to_standard_string() for k in _converter.convert_df_rows(df_1h, 10))
    pos_str = ""
    if position:
        pos_str = f"""
持仓: {position.get('direction','')} 入场={position.get('entry_price',0):.4f} 浮盈={position.get('pnl_pct',0):.2f}%
杠杆: {position.get('leverage',10)}x 止损={position.get('stop_loss',0):.4f} 止盈={position.get('take_profit',0):.4f}
已持~{position.get('held_cycles',0)*15}秒。应持有(HOLD)还是平仓(CLOSE)？理由<15字。
"""
    return f"""当前: {datetime.now(timezone.utc).isoformat()}
币种: {symbol}
{pos_str}
15分钟: {k15}
1小时: {k1h}
MACD: DIF={indicators['macd']['dif']:.6f} DEA={indicators['macd']['dea']:.6f} Hist={indicators['macd']['hist']:.6f}
RSI: {indicators['rsi']:.1f}
BOLL: U={indicators['boll']['upper']:.6f} M={indicators['boll']['mid']:.6f} L={indicators['boll']['lower']:.6f}
KDJ: K={indicators['kdj']['k']:.1f} D={indicators['kdj']['d']:.1f} J={indicators['kdj']['j']:.1f}"""


def _call_deepseek(prompt: str) -> str:
    key = settings.DEEPSEEK_API_KEY
    if not key:
        return json.dumps({"market_state": "RANGING", "confidence": 0.5, "recommended_strategy": "S2",
                           "reasoning": "AI未配置 (请在设置中填入 DeepSeek API Key)", "risk_level": "MEDIUM",
                           "suggested_leverage": 5, "key_levels": {}})
    try:
        import httpx
        with httpx.Client(timeout=30, verify=False) as c:
            r = c.post("https://api.deepseek.com/v1/chat/completions",
                       headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                       json={"model": settings.AI_MODEL, "messages": [
                           {"role": "system", "content": DEEPSEEK_SYSTEM_PROMPT},
                           {"role": "user", "content": prompt},
                       ], "max_tokens": settings.AI_MAX_TOKENS, "temperature": settings.AI_TEMPERATURE})
            data = r.json()
            if "choices" not in data:
                return json.dumps({"market_state": "RANGING", "confidence": 0.5, "recommended_strategy": "S2",
                                   "reasoning": f"API错误: {data.get('error', {}).get('message', str(data)[:120])}",
                                   "risk_level": "MEDIUM", "suggested_leverage": 5, "key_levels": {}})
            return data["choices"][0]["message"]["content"]
    except Exception as exc:
        return json.dumps({"market_state": "RANGING", "confidence": 0.5, "recommended_strategy": "S2",
                           "reasoning": f"API调用失败: {exc}", "risk_level": "MEDIUM",
                           "suggested_leverage": 5, "key_levels": {}})


def _parse(raw: str) -> TrendResult:
    try:
        c = raw.strip()
        for s in ("```json", "```"):
            if s in c:
                c = c.split(s)[1].split("```")[0]
        d = json.loads(c)
    except json.JSONDecodeError:
        d = {}
    is_err = any(w in d.get("reasoning", "") for w in ("API", "失败", "未配置"))
    return TrendResult(
        market_state=d.get("market_state", "RANGING"),
        confidence=float(d.get("confidence", 0.5)),
        recommended_strategy=d.get("recommended_strategy", "S2"),
        reasoning=d.get("reasoning", ""),
        risk_level=d.get("risk_level", "MEDIUM"),
        suggested_leverage=int(d.get("suggested_leverage", 5)),
        key_levels=d.get("key_levels", {}),
        position_action=d.get("position_action", "NONE"),
        position_reason=d.get("position_reason", ""),
        error=is_err,
    )
