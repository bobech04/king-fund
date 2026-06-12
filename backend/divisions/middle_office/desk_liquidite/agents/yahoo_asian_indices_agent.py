"""Agent — Indices asiatiques : N225 HSI SSEC KS11 BSESN AXJO via Yahoo Finance."""
import asyncio
from datetime import datetime
from typing import Any

ASIAN_INDICES = ["^N225", "^HSI", "000001.SS", "^KS11", "^BSESN", "^AXJO"]
ASIAN_LABELS  = {
    "^N225":     "Nikkei225",
    "^HSI":      "HangSeng",
    "000001.SS": "Shanghai",
    "^KS11":     "KOSPI",
    "^BSESN":    "Sensex",
    "^AXJO":     "ASX200",
}


class YahooAsianIndicesAgent:
    name = "Yahoo_Asian"

    async def _fetch_index(self, symbol: str) -> dict[str, Any]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._get_info, symbol)

    def _get_info(self, symbol: str) -> dict[str, Any]:
        import yfinance as yf
        ticker = yf.Ticker(symbol)
        hist   = ticker.history(period="5d")

        if hist.empty:
            return {"error": f"Pas de données pour {symbol}"}

        latest_close = round(float(hist["Close"].iloc[-1]), 2)
        result = {
            "label": ASIAN_LABELS.get(symbol, symbol),
            "close": latest_close,
            "date":  str(hist.index[-1].date()),
        }

        try:
            prev  = float(hist["Close"].iloc[-2])
            chg   = (latest_close - prev) / prev * 100 if prev else 0.0
            result["day_change_pct"] = round(chg, 3)
        except Exception:
            result["day_change_pct"] = None

        return result

    async def run(self) -> dict[str, Any]:
        tasks = [self._fetch_index(s) for s in ASIAN_INDICES]
        raw   = await asyncio.gather(*tasks, return_exceptions=True)

        data: dict[str, Any] = {}
        for symbol, res in zip(ASIAN_INDICES, raw):
            label = ASIAN_LABELS.get(symbol, symbol)
            data[label] = {"error": str(res)} if isinstance(res, Exception) else res

        score   = self._compute_score(data)
        summary = self._build_summary(data, score)

        return {
            "agent":           self.name,
            "timestamp":       datetime.utcnow().isoformat(),
            "data":            data,
            "liquidity_score": score,
            "summary":         summary,
        }

    def _compute_score(self, data: dict) -> float:
        """Score 0-10 : base 5.0, ±0.5 par indice selon variation journalière."""
        score = 5.0
        count = 0
        for label, info in data.items():
            if "error" in info:
                continue
            chg = info.get("day_change_pct")
            if chg is None:
                continue
            count += 1
            if chg > 1.5:
                score += 0.5
            elif chg > 0.5:
                score += 0.25
            elif chg < -1.5:
                score -= 0.5
            elif chg < -0.5:
                score -= 0.25
        return round(max(0.0, min(10.0, score)), 2)

    def _build_summary(self, data: dict, score: float) -> str:
        parts = []
        for label, info in data.items():
            if "error" in info:
                continue
            chg = info.get("day_change_pct")
            if chg is not None:
                sign = "+" if chg >= 0 else ""
                parts.append(f"{label}={sign}{chg:.1f}%")
        indices_str = " | ".join(parts) if parts else "n/a"
        return f"Asian sessions: {indices_str} | score={score}/10"
