"""DeepSeek AI 聊天服务 — 支持上下文、新闻/K线分析、自然语言创建策略。

通过在 system prompt 中注入实时数据 + 让模型输出可选的结构化动作 (action) 实现工具化。
"""
from __future__ import annotations

import json
import re
from typing import Any

from app.core.config import settings
from app.core.logging_config import get_logger

logger = get_logger("ai_chat")

CHAT_SYSTEM_PROMPT = """你是 CryptoAgents Pro 的加密货币交易AI助手。你能：
1. 分析实时K线、技术指标和最新金融新闻，给出市场判断
2. 根据用户的自然语言描述，帮其创建交易策略

可用策略指标类型 (base_type)：
- ema_cross: EMA双均线金叉死叉, params: {fast, slow, stop_loss_pct, take_profit_pct}
- rsi: RSI超买超卖, params: {period, oversold, overbought, stop_loss_pct, take_profit_pct}
- macd: MACD金叉死叉, params: {stop_loss_pct, take_profit_pct}
- boll: 布林带突破回归, params: {period, stop_loss_pct, take_profit_pct}

当用户想要创建/添加策略时，在回复正文之后追加一行独立的 JSON 动作块（用 ```action 包裹）：
```action
{"type":"create_strategy","name":"策略名","base_type":"ema_cross","params":{"fast":9,"slow":26,"stop_loss_pct":1.5,"take_profit_pct":2.0}}
```
若用户只是闲聊或询问分析，则不要输出 action 块。
回复用中文，简洁专业。"""


def _web_search(query: str, max_results: int = 5) -> str:
    """联网搜索 — 尝试 Bing, 失败回退 DuckDuckGo HTML。"""
    import httpx, re
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0"}
    
    # 方法1: Bing
    try:
        with httpx.Client(timeout=8, follow_redirects=True) as client:
            r = client.get(f"https://www.bing.com/search?q={query}&setlang=zh-cn", headers=headers)
            if r.status_code == 200:
                html = r.text
                results = []
                blocks = re.findall(r'<li class="b_algo">(.*?)</li>', html, re.DOTALL)
                for block in blocks[:max_results]:
                    t = re.search(r'<h2><a[^>]*>(.*?)</a></h2>', block, re.DOTALL)
                    d = re.search(r'<p[^>]*>(.*?)</p>', block, re.DOTALL)
                    title = re.sub(r'<[^>]+>', '', t.group(1)).strip() if t else ''
                    desc = re.sub(r'<[^>]+>', '', d.group(1)).strip()[:200] if d else ''
                    if title:
                        results.append(f"- {title}: {desc}")
                if results:
                    return chr(10).join(results)
    except Exception:
        pass
    
    # 方法2: DuckDuckGo HTML (fallback)
    try:
        with httpx.Client(timeout=8, follow_redirects=True) as client:
            r = client.post("https://html.duckduckgo.com/html", data={"q": query}, headers=headers)
            if r.status_code == 200:
                html = r.text
                results = []
                links = re.findall(r'<a rel="nofollow" class="result__a"[^>]*>(.*?)</a>', html, re.DOTALL)
                snippets = re.findall(r'<a class="result__snippet"[^>]*>(.*?)</a>', html, re.DOTALL)
                for i in range(min(len(links), len(snippets), max_results)):
                    title = re.sub(r'<[^>]+>', '', links[i]).strip()
                    desc = re.sub(r'<[^>]+>', '', snippets[i]).strip()[:200]
                    results.append(f"- {title}: {desc}")
                if results:
                    return chr(10).join(results)
    except Exception:
        pass
    
    return '(搜索暂时不可用，请检查网络)' 
def _build_context(symbol: str | None, include_news: bool, include_kline: bool) -> str:
    parts = []
    if include_kline and symbol:
        try:
            from cryptoagents.data.ccxt_fetcher import CCXTFetcher
            from cryptoagents.data.kline_converter import KlineConverter
            from cryptoagents.data.indicator_calc import compute_all_indicators
            f = CCXTFetcher(with_keys=False, use_testnet=False)
            df = f.fetch_ohlcv(symbol, "15m", limit=60)
            if not df.empty:
                cv = KlineConverter()
                klines = "\n".join(k.to_standard_string() for k in cv.convert_df_rows(df, 15))
                ind = compute_all_indicators(df)
                price = float(df["close"].iloc[-1])
                parts.append(
                    f"【{symbol} 实时数据】当前价: {price}\n"
                    f"近15根K线(F/S/L/H):\n{klines}\n"
                    f"MACD: DIF={ind['macd']['dif']:.4f} Hist={ind['macd']['hist']:.4f} | "
                    f"RSI={ind['rsi']:.1f} | "
                    f"BOLL上={ind['boll']['upper']:.2f}/中={ind['boll']['mid']:.2f}/下={ind['boll']['lower']:.2f} | "
                    f"KDJ K={ind['kdj']['k']:.1f} D={ind['kdj']['d']:.1f}")
        except Exception as exc:
            logger.warning(f"K线上下文失败: {exc}")
    if include_news:
        try:
            from cryptoagents.ai.news_service import news_digest
            parts.append(f"【最新加密新闻】\n{news_digest(10)}")
        except Exception as exc:
            logger.warning(f"新闻上下文失败: {exc}")
    return "\n\n".join(parts)


def chat(messages: list[dict[str, str]], symbol: str | None = None,
         include_news: bool = True, include_kline: bool = True) -> dict[str, Any]:
    """messages: [{role, content}, ...] 用户对话历史。返回 {reply, action}。"""
    key = settings.DEEPSEEK_API_KEY
    if not key:
        return {"reply": "⚠ 未配置 DeepSeek API Key。请到「设置」页填入后再使用AI聊天。", "action": None}

    context = _build_context(symbol, include_news, include_kline)
    sys_content = CHAT_SYSTEM_PROMPT
    if context:
        sys_content += f"\n\n以下是当前可参考的实时数据：\n{context}"

    api_messages = [{"role": "system", "content": sys_content}] + messages[-12:]

    try:
        import httpx
        with httpx.Client(timeout=60, verify=False) as c:
            r = c.post("https://api.deepseek.com/v1/chat/completions",
                       headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                       json={"model": settings.AI_MODEL, "messages": api_messages,
                             "max_tokens": settings.AI_MAX_TOKENS, "temperature": settings.AI_TEMPERATURE})
            data = r.json()
        if "choices" not in data:
            err = data.get("error", {}).get("message", str(data)[:160])
            return {"reply": f"AI接口错误: {err}", "action": None}
        content = data["choices"][0]["message"]["content"]
    except Exception as exc:
        return {"reply": f"AI调用失败: {exc}", "action": None}

    action = _extract_action(content)
    reply = re.sub(r"```action.*?```", "", content, flags=re.DOTALL).strip()
    return {"reply": reply, "action": action}


def _extract_action(content: str) -> dict[str, Any] | None:
    m = re.search(r"```action\s*(\{.*?\})\s*```", content, flags=re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except Exception:
        return None


def apply_action(action: dict[str, Any]) -> dict[str, Any]:
    """执行 AI 返回的动作 (目前支持 create_strategy)。"""
    if not action or action.get("type") != "create_strategy":
        return {"applied": False, "message": "无可执行动作"}
    import time
    from cryptoagents.strategy.strategies import register_custom
    from app.models.strategy import CustomStrategy as CSModel
    from app.core.database import get_sqlite_session

    sid = f"AI{int(time.time())}"
    name = action.get("name", "AI策略")
    base_type = action.get("base_type", "ema_cross")
    params = action.get("params", {})
    try:
        s = get_sqlite_session()
        s.add(CSModel(id=sid, name=name, base_type=base_type,
                      params_json=json.dumps(params), enabled=1, created_at=int(time.time())))
        s.commit()
        s.close()
        register_custom(sid, name, base_type, params)
        return {"applied": True, "id": sid, "name": name, "base_type": base_type, "params": params,
                "message": f"已创建策略「{name}」({sid})"}
    except Exception as exc:
        return {"applied": False, "message": f"创建失败: {exc}"}
