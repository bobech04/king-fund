"""Agent 3 — Yahoo Finance Equities: SPY/QQQ volume, VIX, liquidité actions."""
import asyncio
from datetime import datetime
from typing import Any

from desk_liquidite.config import YAHOO_EQUITIES


class YahooEquityAgent:
    name = "Yahoo_Equity"

    async def _fetch_ticker(self, symbol: str) -> dict[str, Any]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._get_info, symbol)

    def _get_info(self, symbol: str) -> dict[str, Any]:
        import yfinance as yf
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period="5d")
        info = ticker.fast_info

        if hist.empty:
            return {"error": f"Pas de données pour {symbol}"}

        latest_close = round(float(hist["Close"].iloc[-1]), 4)
        avg_volume = int(hist["Volume"].mean()) if "Volume" in hist.columns else 0
        latest_volume = int(hist["Volume"].iloc[-1]) if "Volume" in hist.columns else 0
        vol_ratio = round(latest_volume / avg_volume, 3) if avg_volume > 0 else 1.0

        result = {
            "close": latest_close,
            "volume": latest_volume,
            "avg_volume_5d": avg_volume,
            "volume_ratio": vol_ratio,
            "date": str(hist.index[-1].date()),
        }
        try:
            result["day_change_pct"] = round(
                (hist["Close"].iloc[-1] - hist["Close"].iloc[-2]) / hist["Close"].iloc[-2] * 100, 3
            )
        except Exception:
            result["day_change_pct"] = None

        return result

    async def run(self) -> dict[str, Any]:
        tasks = [self._fetch_ticker(s) for s in YAHOO_EQUITIES]
        raw = await asyncio.gather(*tasks, return_exceptions=True)
        results = {}
        for symbol, res in zip(YAHOO_EQUITIES, raw):
            results[symbol] = {"error": str(res)} if isinstance(res, Exception) else res

        vix = results.get("^VIX", {}).get("close")
        score = self._compute_score(results, vix)

        return {
            "agent": self.name,
            "timestamp": datetime.utcnow().isoformat(),
            "data": results,
            "liquidity_score": score,
            "summary": f"VIX={vix} | SPY_vol_ratio={results.get('SPY', {}).get('volume_ratio')} | score={score}/10",
        }

    def _compute_score(self, data: dict, vix: float | None) -> float:
        score = 5.0
        if vix is not None:
            if vix < 15:
                score += 2.0
            elif vix < 20:
                score += 1.0
            elif vix > 30:
                score -= 2.0
            elif vix > 25:
                score -= 1.0

        spy_vol_ratio = data.get("SPY", {}).get("volume_ratio", 1.0)
        if spy_vol_ratio is not None:
            if spy_vol_ratio > 1.5:
                score -= 0.5
            elif spy_vol_ratio < 0.5:
                score -= 0.5

        return round(max(0.0, min(10.0, score)), 2)
