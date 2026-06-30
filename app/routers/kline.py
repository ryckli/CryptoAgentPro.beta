from __future__ import annotations

from fastapi import APIRouter, HTTPException

from cryptoagents.data.ccxt_fetcher import CCXTFetcher
from cryptoagents.data.kline_converter import KlineConverter
from app.core.config import settings

router = APIRouter(prefix="/kline", tags=["K线数据"])
_converter = KlineConverter()


@router.get("/symbols")
def list_symbols():
    return {"symbols": settings.SYMBOLS_WATCHLIST, "timeframes": settings.SYMBOLS_TIMEFRAMES}


@router.get("/{symbol:path}/{timeframe}")
def get_klines(symbol: str, timeframe: str, limit: int = 100):
    fetcher = CCXTFetcher(with_keys=False, use_testnet=False)
    df = fetcher.fetch_ohlcv(symbol, timeframe, limit=limit)
    if df.empty:
        raise HTTPException(404, "无数据")
    converted = _converter.convert_df_rows(df)
    return {
        "symbol": symbol, "timeframe": timeframe, "count": len(converted),
        "data": [{"F": k.F, "S": k.S, "L": k.L, "H": k.H, "direction": k.direction, "timestamp": k.timestamp} for k in converted],
        "raw": [k.to_standard_string() for k in converted],
    }
