"""Agent 4 — Yahoo Finance ETFs: TLT/HYG/LQD/JNK/AGG — flux obligataires."""
import asyncio
from datetime import datetime
from typing import Any

from desk_liquidite.config import YAHOO_ETFS


class YahooETFAgent:
    name = "Yahoo_ETF"

    async def _fetch_etf(self, symbol: str) -> dict[str, Any]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._get_etf_data, symbol)

    def _get_etf_data(self, symbol: str) -> dict[str, Any]:
        import yfinance as yf
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period="10d")
        if hist.empty:
            return {"error": f"Pas de données pour {symbol}"}

        close = round(float(hist["Close"].iloc[-1]), 4)
        volume = int(hist["Volume"].iloc[-1]) if "Volume" in hist.columns else 0
        avg_vol = int(hist["Volume"].mean()) if "Volume" in hist.columns else 0
        ret_1d = None
        if len(hist) >= 2:
            ret_1d = round((hist["Close"].iloc[-1] - hist["Close"].iloc[-2]) / hist["Close"].iloc[-2] * 100, 3)
        ret_5d = None
        if len(hist) >= 5:
            ret_5d = round((hist["Close"].iloc[-1] - hist["Close"].iloc[-5]) / hist["Close"].iloc[-5] * 100, 3)

        return {
            "close": close,
            "volume": volume,
            "avg_volume_10d": avg_vol,
            "volume_ratio": round(volume / avg_vol, 3) if avg_vol > 0 else 1.0,
            "return_1d_pct": ret_1d,
            "return_5d_pct": ret_5d,
            "date": str(hist.index[-1].date()),
        }

    async def run(self) -> dict[str, Any]:
        tasks = [self._fetch_etf(s) for s in YAHOO_ETFS]
        raw = await asyncio.gather(*tasks, return_exceptions=True)
        results = {}
        for symbol, res in zip(YAHOO_ETFS, raw):
            results[symbol] = {"error": str(res)} if isinstance(res, Exception) else res

        score = self._compute_score(results)
        hyg_ret = results.get("HYG", {}).get("return_1d_pct")
        tlt_ret = results.get("TLT", {}).get("return_1d_pct")

        return {
            "agent": self.name,
            "timestamp": datetime.utcnow().isoformat(),
            "data": results,
            "liquidity_score": score,
            "summary": f"HYG_1d={hyg_ret}% | TLT_1d={tlt_ret}% | score={score}/10",
        }

    def _compute_score(self, data: dict) -> float:
        score = 5.0
        hyg = data.get("HYG", {})
        lqd = data.get("LQD", {})
        tlt = data.get("TLT", {})

        hyg_ret = hyg.get("return_1d_pct")
        lqd_ret = lqd.get("return_1d_pct")
        tlt_vol_ratio = tlt.get("volume_ratio")

        if hyg_ret is not None:
            if hyg_ret > 0.2:
                score += 1.0
            elif hyg_ret < -0.5:
                score -= 1.5

        if lqd_ret is not None:
            if lqd_ret < -0.3:
                score -= 1.0
            elif lqd_ret > 0.1:
                score += 0.5

        if tlt_vol_ratio is not None and tlt_vol_ratio > 2.0:
            score -= 0.5

        return round(max(0.0, min(10.0, score)), 2)
