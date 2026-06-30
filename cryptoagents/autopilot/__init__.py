"""自动驾驶核心包 — AI驱动的全自动交易。

模块:
- context_manager: 滑动窗口对话上下文 + 极致压缩系统提示词
- safety_valve: 双保险熔断器 (连续亏损 + 回撤)
"""

from cryptoagents.autopilot.context_manager import AutopilotContext, create_context, SYSTEM_PROMPT_V2
from cryptoagents.autopilot.safety_valve import SafetyValve

__all__ = [
    "AutopilotContext",
    "create_context",
    "SafetyValve",
    "SYSTEM_PROMPT_V2",
]
