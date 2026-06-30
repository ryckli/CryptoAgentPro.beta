from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from app.core.config import settings
from app.core.logging_config import get_logger
from cryptoagents.exchange.base import ExchangeBase

logger = get_logger("okx")

_TF_MAP = {"1m": "1m", "3m": "3m", "5m": "5m", "15m": "15m", "30m": "30m",
           "1h": "1H", "2h": "2H", "4h": "4H", "6h": "6H", "12h": "12H",
           "1d": "1D", "1w": "1W"}


class OKXExchange(ExchangeBase):
    name = "okx"
    base_url = "https://www.okx.com"

    def __init__(self, api_key: str = "", secret: str = "", passphrase: str = "",
                 testnet: bool = False, with_keys: bool = True):
        self.api_key = api_key
        self.secret = secret
        self.passphrase = passphrase
        self.testnet = testnet
        self.with_keys = with_keys and bool(api_key)

    def _symbol_to_okx(self, symbol: str) -> str:
        """BTC/USDT -> BTC-USDT-SWAP"""
        parts = symbol.replace("/", "-").split("-")
        if len(parts) == 2:
            return f"{parts[0]}-{parts[1]}-SWAP"
        return symbol.replace("/", "-")

    def _okx_to_symbol(self, inst_id: str) -> str:
        """BTC-USDT-SWAP -> BTC/USDT"""
        parts = inst_id.split("-")
        if len(parts) >= 2:
            return f"{parts[0]}/{parts[1]}"
        return inst_id

    def _sign(self, timestamp: str, method: str, path: str, body: str = "") -> str:
        msg = f"{timestamp}{method.upper()}{path}{body}"
        mac = hmac.new(self.secret.encode("utf-8"), msg.encode("utf-8"), hashlib.sha256)
        return base64.b64encode(mac.digest()).decode("utf-8")

    def _headers(self, method: str, path: str, body: str = "") -> dict[str, str]:
        now = datetime.now(timezone.utc)
        ts = now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"
        h = {"Content-Type": "application/json"}
        if self.with_keys:
            h["OK-ACCESS-KEY"] = self.api_key
            h["OK-ACCESS-SIGN"] = self._sign(ts, method, path, body)
            h["OK-ACCESS-TIMESTAMP"] = ts
            h["OK-ACCESS-PASSPHRASE"] = self.passphrase
        if self.testnet:
            h["x-simulated-trading"] = "1"
        return h

    def _request(self, method: str, path: str, params: dict | None = None,
                 body: dict | None = None, need_auth: bool = False) -> dict:
        import httpx
        # build full sign path (including query params)
        qs = ""
        if params:
            qs = "?" + "&".join(f"{k}={v}" for k, v in params.items())
        sign_path = path + qs
        body_str = json.dumps(body) if body else ""
        # sign
        headers = {"Content-Type": "application/json"}
        if need_auth and self.with_keys:
            headers = self._headers(method, sign_path, body_str)
        url = self.base_url + sign_path
        import ssl
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        try:
            with httpx.Client(timeout=15, verify=ctx) as c:
                if method == "GET":
                    r = c.get(url, headers=headers)
                else:
                    r = c.post(url, headers=headers, content=body_str)
            data = r.json()
            if data.get("code") != "0":
                logger.warning(f"OKX API error: {data.get('msg', '')} path={path}")
            return data
        except Exception as exc:
            logger.error(f"OKX request failed {path}: {exc}")
            return {"code": "-1", "msg": str(exc), "data": []}

    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int = 100,
                    since: int | None = None) -> pd.DataFrame:
        inst = self._symbol_to_okx(symbol)
        bar = _TF_MAP.get(timeframe, "15m")
        params = {"instId": inst, "bar": bar, "limit": str(min(limit, 300))}
        
        # >3天前的数据用history-candles, 最近数据用candles
        now_ms = self.milliseconds()
        use_history = since is not None and (now_ms - since) > 3 * 24 * 3600 * 1000
        endpoint = "/api/v5/market/history-candles" if use_history else "/api/v5/market/candles"
        
        if since:
            # Both endpoints use 'after' for forward pagination
            params["after"] = str(since)
        data = self._request("GET", endpoint, params)
        rows = data.get("data", [])
        if not rows:
            return pd.DataFrame()
        # OKX returns reversed (new -> old), reverse it
        rows.reverse()
        records = []
        for r in rows:
            records.append({
                "timestamp": pd.to_datetime(int(r[0]), unit="ms"),
                "open": float(r[1]), "high": float(r[2]),
                "low": float(r[3]), "close": float(r[4]),
                "volume": float(r[5] or 0),
            })
        df = pd.DataFrame(records).set_index("timestamp")
        return df

    def fetch_ticker(self, symbol: str) -> dict[str, Any]:
        inst = self._symbol_to_okx(symbol)
        data = self._request("GET", "/api/v5/market/ticker", {"instId": inst})
        rows = data.get("data", [])
        if not rows:
            return {"last": 0, "bid": 0, "ask": 0, "timestamp": 0}
        r = rows[0]
        return {"last": float(r.get("last", 0)), "bid": float(r.get("bidPx", 0)),
                "ask": float(r.get("askPx", 0)), "timestamp": int(r.get("ts", 0))}

    def fetch_positions(self, symbols: list[str] | None = None) -> list[dict[str, Any]]:
        if not self.with_keys:
            return []
        params = None
        if symbols:
            params = {"instId": self._symbol_to_okx(symbols[0])}
        data = self._request("GET", "/api/v5/account/positions", params, need_auth=True)
        out = []
        for r in data.get("data", []):
            pos = float(r.get("pos", 0))
            if pos == 0:
                continue
            side = "LONG" if (r.get("posSide") == "long" or pos > 0) else "SHORT"
            out.append({
                "symbol": self._okx_to_symbol(r.get("instId", "")),
                "direction": side, "qty": abs(pos),
                "entry_price": float(r.get("avgPx", 0) or 0),
                "leverage": int(float(r.get("lever", 1) or 1)),
                "contracts": abs(pos),
            })
        return out

    def set_leverage(self, symbol: str, leverage: int) -> None:
        if not self.with_keys:
            return
        inst = self._symbol_to_okx(symbol)
        for pos_side in ["long", "short"]:
            body = {"instId": inst, "lever": str(leverage), "mgnMode": "cross", "posSide": pos_side}
            self._request("POST", "/api/v5/account/set-leverage", body=body, need_auth=True)

    def _coin_qty_to_ct(self, symbol: str, coin_qty: float) -> str:
        """Convert coin quantity to OKX contract count (sz).
        BTC: 1ct=0.01BTC, ETH: 1ct=0.1ETH, SOL: 1ct=1SOL
        """
        base = symbol.split("/")[0].split("-")[0]
        ct_val = {"BTC": 0.01, "ETH": 0.1, "SOL": 1.0, "XAU": 0.01}.get(base, 1.0)
        ct = max(1, round(coin_qty / ct_val))
        return str(ct)

    def place_market_order(self, symbol: str, side: str, qty: float,
                           reduce_only: bool = False, sl_price: float = 0,
                           tp_price: float = 0, leverage: int = 0) -> dict[str, Any]:
        if not self.with_keys:
            return {"id": "", "status": "error", "message": "no API key"}
        inst = self._symbol_to_okx(symbol)
        okx_side = "buy" if side.lower() in ("buy", "long") else "sell"
        close_side = "sell" if okx_side == "buy" else "buy"
        sz = self._coin_qty_to_ct(symbol, qty)
        body: dict[str, Any] = {
            "instId": inst, "tdMode": "cross", "side": okx_side,
            "ordType": "market", "sz": sz,
        }
        if reduce_only:
            body["reduceOnly"] = True
        # SL/TP: combined into single attachAlgoOrds element per OKX spec
        if sl_price or tp_price:
            algo = {"instId": inst, "sz": sz, "side": close_side, "ordType": "conditional"}
            if sl_price:
                algo["slTriggerPx"] = str(sl_price)
                algo["slTriggerPxType"] = "last"
                algo["slOrdPx"] = "-1"
            if tp_price:
                algo["tpTriggerPx"] = str(tp_price)
                algo["tpTriggerPxType"] = "last"
                algo["tpOrdPx"] = "-1"
            body["attachAlgoOrds"] = [algo]
        data = self._request("POST", "/api/v5/trade/order", body=body, need_auth=True)
        if data.get("code") == "0" and data.get("data"):
            return {"id": data["data"][0].get("ordId", ""), "status": "ok",
                    "message": data["data"][0].get("sMsg", "")}
        return {"id": "", "status": "error", "message": data.get("msg", "order failed")}

    def close_position_market(self, symbol: str) -> dict[str, Any]:
        """市价全平指定币种持仓。使用 OKX 专用平仓接口。"""
        if not self.with_keys:
            return {"status": "error", "message": "no API key"}
        inst = self._symbol_to_okx(symbol)
        # Try long side first, then short
        for pos_side in ["long", "short"]:
            body = {"instId": inst, "mgnMode": "cross", "posSide": pos_side, "autoCxl": True}
            data = self._request("POST", "/api/v5/trade/close-position", body=body, need_auth=True)
            if data.get("code") == "0":
                logger.info(f"OKX close-position {symbol} {pos_side}: {data.get('data',[{}])[0].get('sMsg','')}")
            else:
                logger.debug(f"OKX close-position {symbol} {pos_side}: {data.get('msg','')}")
        return {"status": "ok", "message": f"{symbol} close-position sent"}

    def fetch_account_balance(self) -> dict[str, Any]:
        if not self.with_keys:
            return {"total": 0, "available": 0}
        data = self._request("GET", "/api/v5/account/balance", need_auth=True)
        for acc in data.get("data", []):
            def _f(v):
                try: return float(v) if v else 0.0
                except: return 0.0
            total = _f(acc.get("totalEq", 0))
            avail = _f(acc.get("availBal", 0) or acc.get("availEq", 0))
            return {"total": total, "available": avail}
        return {"total": 0, "available": 0}
