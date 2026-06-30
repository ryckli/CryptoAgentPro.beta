from __future__ import annotations

from typing import Any

from cryptoagents.strategy.base import MarketState, STRATEGY_MARKET_MAP

try:
    from langgraph.graph import StateGraph, END, START
    LANGGRAPH_AVAILABLE = True
except ImportError:
    LANGGRAPH_AVAILABLE = False


class AgentState(dict):
    market_data: Any = None
    indicators: dict = {}
    market_state: str = "RANGING"
    recommended_strategy: str = "S2"
    signal: dict = {}
    messages: list = []


class CryptoGraph:
    def __init__(self):
        if not LANGGRAPH_AVAILABLE:
            self.graph = None
            return
        workflow = StateGraph(AgentState)
        workflow.add_node("data_collect", self._data_collect)
        workflow.add_node("indicator_calc", self._indicator_calc)
        workflow.add_node("trend_analyze", self._trend_analyze)
        workflow.add_node("strategy_match", self._strategy_match)
        workflow.add_node("signal_generate", self._signal_generate)
        workflow.add_edge(START, "data_collect")
        workflow.add_edge("data_collect", "indicator_calc")
        workflow.add_edge("indicator_calc", "trend_analyze")
        workflow.add_edge("trend_analyze", "strategy_match")
        workflow.add_edge("strategy_match", "signal_generate")
        workflow.add_edge("signal_generate", END)
        self.graph = workflow.compile()

    def _data_collect(self, state: AgentState) -> AgentState:
        return state

    def _indicator_calc(self, state: AgentState) -> AgentState:
        return state

    def _trend_analyze(self, state: AgentState) -> AgentState:
        state["market_state"] = state.get("market_state", "RANGING")
        return state

    def _strategy_match(self, state: AgentState) -> AgentState:
        ms = state.get("market_state", "RANGING")
        try:
            mse = MarketState(ms)
            mapped = STRATEGY_MARKET_MAP.get(mse, STRATEGY_MARKET_MAP[MarketState.RANGING])
            state["recommended_strategy"] = mapped["primary"]
        except ValueError:
            state["recommended_strategy"] = "S2"
        return state

    def _signal_generate(self, state: AgentState) -> AgentState:
        state["signal"] = {"signal": "HOLD", "strategy": state.get("recommended_strategy", "S2")}
        return state

    async def run(self, state: dict[str, Any]) -> dict[str, Any]:
        if self.graph is None:
            return {"market_state": state.get("market_state", "RANGING"), "recommended_strategy": "S2", "signal": {"signal": "HOLD"}}
        initial = AgentState(**state)
        result = self.graph.invoke(initial)
        return dict(result)


crypto_graph = CryptoGraph()
