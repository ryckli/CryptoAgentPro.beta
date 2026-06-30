"""OKX MCP Client - via OKX Agent Trade Kit CLI."""
from __future__ import annotations
import json, subprocess, time
from typing import Any
import pandas as pd
from app.core.logging_config import get_logger
from cryptoagents.exchange.base import ExchangeBase
logger = get_logger("mcp_client")
_TF_MAP = {"1m":"1m","3m":"3m","5m":"5m","15m":"15m","30m":"30m","1h":"1H","2h":"2H","4h":"4H","1d":"1D","1w":"1W"}
_CTVAL = {"BTC":0.01,"ETH":0.1,"SOL":1.0}

def _run_okx(*args, timeout=15):
    cmd = "npx okx --json " + " ".join(str(a) for a in args)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, shell=True)
        if r.returncode != 0: return {}
        data = json.loads(r.stdout)
        # Handle arrays: unwrap single-element dict arrays, pass through multi-element arrays (candles)
        if isinstance(data, list):
            if len(data) == 1 and isinstance(data[0], dict):
                return data[0]
            return data  # candles, positions etc.
        return data if isinstance(data, dict) else {}
    except Exception as exc:
        logger.error(f"okx CLI: {exc}")
        return {}

class MCPExchange(ExchangeBase):
    name = "okx_mcp"
    base_url = "https://www.okx.com"
    def __init__(self, api_key="", secret="", passphrase="", testnet=False, with_keys=True):
        self.api_key, self.secret, self.passphrase = api_key, secret, passphrase
        self.testnet, self.with_keys = testnet, with_keys and bool(api_key)
        self._demo = "--demo" if testnet else ""
    @property
    def rate_limit_ms(self): return 200
    def _sym(self, s): return s.replace("/","-")
    def _ct(self, s, q):
        ct_val = _CTVAL.get(s.split("/")[0], 1.0)
        return str(max(1, round(q / ct_val)))
    def _args(self): return [self._demo] if self._demo else []

    def fetch_ticker(self, symbol):
        data = _run_okx("market","ticker", self._sym(symbol))
        return {"last": float(data.get("last",0) or 0), "bid": float(data.get("bidPx",0) or 0), "ask": float(data.get("askPx",0) or 0), "timestamp": int(data.get("ts",0) or 0)}

    def fetch_ohlcv(self, symbol, timeframe, limit=100, since=None):
        inst = self._sym(symbol); bar = _TF_MAP.get(timeframe,"15m")
        args = ["market","candles",inst,"--bar",bar,"--limit",str(min(limit,300))]
        if since: args.extend(["--after",str(since)])
        data = _run_okx(*args)
        if not data: return pd.DataFrame()
        if isinstance(data, dict): data = [data]
        # Handle both array-of-arrays (raw OKX) and array-of-objects (parsed)
        records = []
        for r in data:
            if isinstance(r, list) and len(r) >= 6:
                ts, o, h, l, c_, vol = int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])
            elif isinstance(r, dict):
                ts = int(r.get("ts",0) or 0); o = float(r.get("open",0) or 0); h = float(r.get("high",0) or 0)
                l = float(r.get("low",0) or 0); c_ = float(r.get("close",0) or 0); vol = float(r.get("vol",0) or 0)
            else:
                continue
            records.append({"timestamp": pd.to_datetime(ts,unit="ms"), "open": o, "high": h, "low": l, "close": c_, "volume": vol})
        # OKX returns reversed (new->old), reverse to chronological
        records.reverse()
        return pd.DataFrame(records).set_index("timestamp")

    def fetch_account_balance(self):
        if not self.with_keys: return {"total":0,"available":0}
        data = _run_okx(*self._args(), "account","balance")
        return {"total": float(data.get("totalEq",0) or 0), "available": float(data.get("availBal",0) or 0)}

    def fetch_positions(self, symbols=None):
        if not self.with_keys: return []
        data = _run_okx(*self._args(), "swap","get-positions")
        items = data if isinstance(data, list) else data.get("data",[]) if isinstance(data, dict) else []
        out = []
        for r in items:
            pos = float(r.get("pos",0) or r.get("posQty",0) or 0)
            if pos == 0: continue
            inst = r.get("instId",""); sym = inst.replace("-","/") if "-" in inst else inst
            side = "LONG" if (r.get("posSide","")=="long" or pos>0) else "SHORT"
            out.append({"symbol":sym,"direction":side,"qty":abs(pos),"entry_price":float(r.get("avgPx",0) or 0),"leverage":int(float(r.get("lever",1) or 1)),"contracts":abs(pos)})
        return out

    def set_leverage(self, symbol, leverage):
        if not self.with_keys: return
        _run_okx(*self._args(), "swap","set-leverage", self._sym(symbol), str(leverage))

    def place_market_order(self, symbol, side, qty, reduce_only=False, sl_price=0, tp_price=0, leverage=0):
        if not self.with_keys: return {"id":"","status":"error","message":"no API key"}
        inst = self._sym(symbol); okx_side = "buy" if side.lower() in ("buy","long") else "sell"
        pos_side = "long" if okx_side=="buy" else "short"; sz = self._ct(symbol, qty)
        args = [*self._args(), "swap","place-order", inst, okx_side, "market", sz, "--posSide", pos_side, "--tdMode", "cross"]
        if reduce_only: args.append("--reduceOnly")
        if sl_price: args.extend(["--slTriggerPx",str(sl_price),"--slOrdPx","-1"])
        if tp_price: args.extend(["--tpTriggerPx",str(tp_price),"--tpOrdPx","-1"])
        data = _run_okx(*args)
        if data.get("ordId"): return {"id":data["ordId"],"status":"ok","message":"MCP order placed"}
        return {"id":"","status":"error","message":data.get("sMsg",data.get("msg","order failed"))}

    def close_position_market(self, symbol):
        if not self.with_keys: return {"status":"error","message":"no API key"}
        _run_okx(*self._args(), "swap","close-position", self._sym(symbol))
        return {"status":"ok","message":f"{symbol} closed via MCP"}

    def load_markets(self): return {}
    @staticmethod
    def milliseconds(): return int(time.time() * 1000)
