from __future__ import annotations

import hashlib
import hmac
import time
from typing import Any
from urllib.parse import urlencode

import pandas as pd

from app.core.config import settings
from app.core.logging_config import get_logger
from cryptoagents.exchange.base import ExchangeBase

logger = get_logger("binance")


class BinanceExchange(ExchangeBase):
    name = "binance"
    base_url = "https://fapi.binance.com"

    def __init__(self, api_key: str = "", secret: str = "", passphrase: str = "",
                 testnet: bool = False, with_keys: bool = True):
        self.api_key = api_key
        self.secret = secret
        self.testnet = testnet
        self.with_keys = with_keys and bool(api_key)
        if testnet:
            self.base_url = "https://testnet.binancefuture.com"

    def _symbol_to_binance(self, symbol: str) -> str:
        """BTC/USDT -> BTCUSDT"""
        return symbol.replace("/", "").replace("-", "")

    def _sign(self, params: dict) -> str:
        qs = urlencode(params)
        return hmac.new(self.secret.encode(), qs.encode(), hashlib.sha256).hexdigest()

    def _headers(self) -> dict[str, str]:
        h = {}
        if self.with_keys:
            h["X-MBX-APIKEY"] = self.api_key
        return h

    def _request(self, method: str, path: str, params: dict | None = None,
                 signed: bool = False) -> dict:
        import httpx
        params = dict(params or {})
        if signed and self.with_keys:
            params["timestamp"] = str(int(time.time() * 1000))
            params["signature"] = self._sign(params)
        qs = urlencode(params)
        url = f"{self.base_url}{path}?{qs}"
        import ssl
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        try:
            with httpx.Client(timeout=15, verify=ctx) as c:
                if method == "GET":
                    r = c.get(url, headers=self._headers())
                else:
                    r = c.post(url, headers=self._headers())
            if r.status_code != 200:
                logger.warning(f"Binance API {r.status_code}: {r.text[:200]}")
                return {"error": r.text[:500]}
            return r.json()
        except Exception as exc:
            logger.error(f"Binance request failed {path}: {exc}")
            return {"error": str(exc)}

    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int = 100,
                    since: int | None = None) -> pd.DataFrame:
        sym = self._symbol_to_binance(symbol)
        params: dict[str, Any] = {"symbol": sym, "interval": timeframe, "limit": str(min(limit, 1500))}
        if since:
            params["startTime"] = str(since)
        data = self._request("GET", "/fapi/v1/klines", params)
        if not isinstance(data, list):
            return pd.DataFrame()
        records = []
        for r in data:
            records.append({
                "timestamp": pd.to_datetime(int(r[0]), unit="ms"),
                "open": float(r[1]), "high": float(r[2]),
                "low": float(r[3]), "close": float(r[4]),
                "volume": float(r[5]),
            })
        df = pd.DataFrame(records).set_index("timestamp")
        return df

    def fetch_ticker(self, symbol: str) -> dict[str, Any]:
        sym = self._symbol_to_binance(symbol)
        data = self._request("GET", "/fapi/v1/ticker/price", {"symbol": sym})
        if "price" not in data:
            return {"last": 0, "bid": 0, "ask": 0, "timestamp": 0}
        return {"last": float(data["price"]), "bid": float(data["price"]),
                "ask": float(data["price"]), "timestamp": int(time.time() * 1000)}

    def fetch_positions(self, symbols: list[str] | None = None) -> list[dict[str, Any]]:
        if not self.with_keys:
            return []
        data = self._request("GET", "/fapi/v2/positionRisk", signed=True)
        if not isinstance(data, list):
            return []
        out = []
        for r in data:
            amt = float(r.get("positionAmt", 0))
            if amt == 0:
                continue
            sym = r.get("symbol", "")
            # BTCUSDT -> BTC/USDT
            if sym.endswith("USDT"):
                base = sym[:-4]
                symbol = f"{base}/USDT"
            else:
                symbol = sym
            if symbols and symbol not in symbols and sym not in symbols:
                continue
            out.append({
                "symbol": symbol, "direction": "LONG" if amt > 0 else "SHORT",
                "qty": abs(amt), "entry_price": float(r.get("entryPrice", 0)),
                "leverage": int(float(r.get("leverage", 1))),
                "contracts": abs(amt),
            })
        return out

    def set_leverage(self, symbol: str, leverage: int) -> None:
        if not self.with_keys:
            return
        sym = self._symbol_to_binance(symbol)
        self._request("POST", "/fapi/v1/leverage",
                      {"symbol": sym, "leverage": str(leverage)}, signed=True)

    def place_market_order(self, symbol: str, side: str, qty: float,
                           reduce_only: bool = False, sl_price: float = 0,
                           tp_price: float = 0, leverage: int = 0) -> dict[str, Any]:
        if not self.with_keys:
            return {"id": "", "status": "error", "message": "no API key"}
        sym = self._symbol_to_binance(symbol)
        bn_side = "BUY" if side.lower() in ("buy", "long") else "SELL"
        params: dict[str, Any] = {
            "symbol": sym, "side": bn_side, "type": "MARKET",
            "quantity": str(qty),
        }
        if reduce_only:
            params["reduceOnly"] = "true"
        data = self._request("POST", "/fapi/v1/order", params, signed=True)
        if "orderId" in data:
            # SL/TP: closePosition=true handles direction automatically
            if sl_price:
                self._request("POST", "/fapi/v1/order", {
                    "symbol": sym, "side": "SELL" if bn_side == "BUY" else "BUY",
                    "type": "STOP_MARKET", "stopPrice": str(sl_price),
                    "closePosition": "true",
                }, signed=True)
            if tp_price:
                self._request("POST", "/fapi/v1/order", {
                    "symbol": sym, "side": "SELL" if bn_side == "BUY" else "BUY",
                    "type": "TAKE_PROFIT_MARKET", "stopPrice": str(tp_price),
                    "closePosition": "true",
                }, signed=True)
            return {"id": str(data["orderId"]), "status": "ok", "message": "order placed"}
        return {"id": "", "status": "error", "message": str(data.get("error", data))[:200]}

    def fetch_account_balance(self) -> dict[str, Any]:
        if not self.with_keys:
            return {"total": 0, "available": 0}
        data = self._request("GET", "/fapi/v2/balance", signed=True)
        if not isinstance(data, list):
            return {"total": 0, "available": 0}
        for b in data:
            if b.get("asset") == "USDT":
                return {"total": float(b.get("balance", 0)),
                        "available": float(b.get("availableBalance", 0))}
        return {"total": 0, "available": 0}
