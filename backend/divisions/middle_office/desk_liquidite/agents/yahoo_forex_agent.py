"""Agent 5 — Yahoo Finance Forex: EUR/USD, USD/JPY, GBP/USD, DXY — liquidité FX."""
import asyncio
from datetime import datetime
from typing import Any

from desk_liquidite.config import YAHOO_FOREX


class YahooForexAgent:
    name = "Yahoo_Forex"

    async def _fetch_pair(self, symbol: str) -> dict[str, Any]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._get_fx_data, symbol)

    def _get_fx_data(self, symbol: str) -> dict[str, Any]:
        import yfinance as yf
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period="10d")
        if hist.empty:
            return {"error": f"Pas de données pour {symbol}"}

        close = round(float(hist["Close"].iloc[-1]), 6)
        ret_1d = None
        if len(hist) >= 2:
            ret_1d = round((hist["Close"].iloc[-1] - hist["Close"].iloc[-2]) / hist["Close"].iloc[-2] * 100, 4)
        ret_5d = None
        if len(hist) >= 5:
            ret_5d = round((hist["Close"].iloc[-1] - hist["Close"].iloc[-5]) / hist["Close"].iloc[-5] * 100, 4)

        high = round(float(hist["High"].max()), 6)
        low = round(float(hist["Low"].min()), 6)

        return {
            "rate": close,
            "return_1d_pct": ret_1d,
            "return_5d_pct": ret_5d,
            "range_10d_high": high,
            "range_10d_low": low,
            "volatility_pct": round((high - low) / low * 100, 4) if low > 0 else None,
            "date": str(hist.index[-1].date()),
        }

    async def run(self) -> dict[str, Any]:
        tasks = [self._fetch_pair(s) for s in YAHOO_FOREX]
        raw = await asyncio.gather(*tasks, return_exceptions=True)
        results = {}
        for symbol, res in zip(YAHOO_FOREX, raw):
            results[symbol] = {"error": str(res)} if isinstance(res, Exception) else res

        score = self._compute_score(results)
        eurusd = results.get("EURUSD=X", {}).get("rate")
        dxy = results.get("DX-Y.NYB", {}).get("rate")

        return {
            "agent": self.name,
            "timestamp": datetime.utcnow().isoformat(),
            "data": results,
            "liquidity_score": score,
            "summary": f"EUR/USD={eurusd} | DXY={dxy} | score={score}/10",
        }

    def _compute_score(self, data: dict) -> float:
        score = 5.0
        dxy = data.get("DX-Y.NYB", {})
        eurusd = data.get("EURUSD=X", {})

        dxy_ret = dxy.get("return_1d_pct")
        dxy_vol = dxy.get("volatility_pct")
        eurusd_vol = eurusd.get("volatility_pct")

        if dxy_ret is not None:
            if dxy_ret > 0.5:
                score -= 1.0
            elif dxy_ret < -0.5:
                score += 0.5

        if dxy_vol is not None:
            if dxy_vol < 1.5:
                score += 1.0
            elif dxy_vol > 3.0:
                score -= 1.5

        if eurusd_vol is not None and eurusd_vol > 2.5:
            score -= 0.5

        return round(max(0.0, min(10.0, score)), 2)
