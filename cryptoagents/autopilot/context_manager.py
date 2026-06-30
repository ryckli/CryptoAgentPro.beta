"""自动驾驶上下文管理器 — 滑动窗口对话历史 + 极致压缩系统提示词。

设计原则:
- Token 限制在 1500 以内 (系统提示词压缩至极致)
- 仅保留最近 5 轮交互 (滑动窗口)，防止 Token 爆炸
- 每轮附加权益摘要，让 AI 知悉持仓变化
- AI 输出标准化 JSON: {action, symbol, position_size_pct, stop_loss_pct, take_profit_pct, reasoning}
"""

from __future__ import annotations

import json
import os
from collections import deque
from typing import Any

# 极致压缩系统提示词 (~600 tokens)
SYSTEM_PROMPT_V2 = """ROLE: Crypto Quant Trader. Output strict JSON only. No markdown, no extra text.

RULES:
- Leverage: 3-10x. Max loss per trade ≤3% equity. Daily loss cap 15% → auto shutdown.
- Instruments: BTC/USDT, ETH/USDT, SOL/USDT. Perpetual swaps only.
- One position per symbol. If holding, do not open another.
- If market trending strong → use trend-following. If ranging → mean-reversion.
- If RSI < 25 → oversold bounce. If RSI > 75 → overbought reversal.
- Always set stop-loss. Never risk more than 3% of equity on one trade.

OUTPUT_JSON_SCHEMA:
{
  "action": "BUY" | "SELL" | "HOLD" | "CLOSE",
  "symbol": "BTC/USDT",
  "position_size_pct": 50,
  "stop_loss_pct": 1.5,
  "take_profit_pct": 3.0,
  "leverage": 5,
  "reasoning": "Max 15 words, key reason only"
}

STRATEGY_KNOWLEDGE (internal, do not output):
- S1 Trend: EMA9>26 + MACD rising + volume confirm → BUY trending market
- S2 Reversion: RSI<35 oversold → BUY / RSI>65 overbought → SELL (ranging)
- S3 MACD: MACD crossover + histogram expanding + volume surge → trend change entry
- S4 Bounce: RSI<25 + 5-bar drop>3% → BUY bounce (crash recovery)
- S5 Scalp: Price near BB mid + RSI neutral + close direction → small scalp
- S6 TD9: TD count ≥8 → extreme reversal signal
- SL: 1.5-4% | TP: 3-8% | Always TP > SL (min 1.5:1 ratio)
"""


class AutopilotContext:
    """滑动窗口上下文管理器。

    不保存全量历史，采用 滑动窗口（最近5轮）+ 状态摘要，
    防止 Token 爆炸导致 API 响应延迟和费用飙升。
    """

    def __init__(self, max_history: int = 5):
        self.max_history = max_history
        self.system_prompt = SYSTEM_PROMPT_V2
        self.history: deque[dict[str, str]] = deque(maxlen=max_history)
        self.summary = "No open positions. Equity 100%."

    def build_messages(self, snapshot: dict[str, Any]) -> list[dict[str, str]]:
        """构建发送给 DeepSeek 的消息列表。

        Args:
            snapshot: 来自 data snapshot 的实时数据，包含:
                - timestamp, equity, free, used_margin
                - positions: 持仓摘要字符串
                - market: 行情快照字符串 (F/S/L/H 格式)

        Returns:
            [system_msg, ...history_msgs, user_msg]
        """
        data_line = self._compress_snapshot(snapshot)
        user_content = f"DATA: {data_line} | STATUS: {self.summary}"

        messages: list[dict[str, str]] = [
            {"role": "system", "content": self.system_prompt},
        ]
        # 注入最近历史 (仅 action + reasoning，不包含完整数据)
        messages.extend(list(self.history))
        messages.append({"role": "user", "content": user_content})
        return messages

    def update(self, ai_response: dict[str, Any], execution_result: dict[str, Any]):
        """更新上下文摘要和历史。

        仅保存 AI 的 reasoning 和最终 action，不保存完整数据，
        确保滑动窗口内 Token 可控。

        Args:
            ai_response: AI 返回的 JSON (action, symbol, reasoning, ...)
            execution_result: 执行结果 (equity_after, pnl, ...)
        """
        action = ai_response.get("action", "HOLD")
        symbol = ai_response.get("symbol", "")
        reason = ai_response.get("reasoning", "")
        equity = execution_result.get("equity_after", "?")
        pnl = execution_result.get("pnl", 0)

        # 更新摘要
        pos_info = execution_result.get("open_positions", "none")
        self.summary = (
            f"Equity: {equity}. "
            f"Last: {action} {symbol} (reason: {reason}). "
            f"Positions: {pos_info}. "
            f"PnL: {pnl}"
        )

        # 仅保存精简历史
        self.history.append({
            "role": "assistant",
            "content": json.dumps({
                "action": action,
                "symbol": symbol,
                "reason": reason,
                "pnl": pnl,
            }, ensure_ascii=False),
        })

    def update_passive(self, summary: str):
        """被动更新 (无交易时) — 仅更新状态摘要，不追加历史。"""
        self.summary = summary

    def _compress_snapshot(self, snapshot: dict[str, Any]) -> str:
        """将 snapshot 压缩为极短字符串 (~200 chars)。

        格式: EQ:10000|FREE:8500|POS:BTC/USDT LONG 0.01@42000|MKT:BTC:42000,ETH:2500
        """
        parts = []
        equity = snapshot.get("equity", "?")
        free = snapshot.get("free", "?")
        parts.append(f"EQ:{equity}|FREE:{free}")

        positions = snapshot.get("positions", "none")
        parts.append(f"POS:{positions}")

        market = snapshot.get("market", "")
        parts.append(f"MKT:{market}")

        return "|".join(parts)


# 便捷工厂
def create_context(max_history: int = 5) -> AutopilotContext:
    return AutopilotContext(max_history=max_history)
