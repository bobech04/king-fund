"""Agent 2 — FRED Credit Conditions: TED spread, IG/HY spreads, crédit bancaire."""
import asyncio
from datetime import datetime, timedelta
from typing import Any

from desk_liquidite.config import FRED_API_KEY, FRED_CREDIT_SERIES


class FREDCreditAgent:
    name = "FRED_Credit"

    def __init__(self):
        self._client = None

    def _get_client(self):
        if self._client is None:
            from fredapi import Fred
            if not FRED_API_KEY:
                raise ValueError("FRED_API_KEY manquant dans .env")
            self._client = Fred(api_key=FRED_API_KEY)
        return self._client

    def _fetch_series(self, series_id: str) -> dict[str, Any]:
        fred = self._get_client()
        end = datetime.today()
        start = end - timedelta(days=90)
        data = fred.get_series(series_id, observation_start=start.strftime("%Y-%m-%d"))
        if data.empty:
            return {"latest": None, "change_pct": None}
        latest = float(data.iloc[-1])
        prev = float(data.iloc[-2]) if len(data) >= 2 else latest
        change_pct = round((latest - prev) / abs(prev) * 100, 4) if prev != 0 else 0.0
        return {
            "latest": round(latest, 4),
            "date": str(data.index[-1].date()),
            "change_pct": change_pct,
            "trend": "widening" if change_pct > 0 else ("tightening" if change_pct < 0 else "stable"),
        }

    async def run(self) -> dict[str, Any]:
        loop = asyncio.get_running_loop()
        results = {}
        for name, series_id in FRED_CREDIT_SERIES.items():
            try:
                results[name] = await loop.run_in_executor(
                    None, self._fetch_series, series_id
                )
            except Exception as exc:
                results[name] = {"error": str(exc)}

        score = self._compute_score(results)

        return {
            "agent": self.name,
            "timestamp": datetime.utcnow().isoformat(),
            "data": results,
            "liquidity_score": score,
            "summary": (
                f"TED={results.get('ted_spread', {}).get('latest')}bp | "
                f"HY={results.get('hy_spread', {}).get('latest')}bp | "
                f"score={score}/10"
            ),
        }

    def _compute_score(self, data: dict) -> float:
        score = 5.0
        ted = data.get("ted_spread", {}).get("latest")
        hy = data.get("hy_spread", {}).get("latest")
        ig = data.get("ig_spread", {}).get("latest")

        if ted is not None:
            if ted < 0.20:
                score += 1.5
            elif ted > 0.50:
                score -= 2.0

        if hy is not None:
            if hy < 3.5:
                score += 1.0
            elif hy > 7.0:
                score -= 2.0

        if ig is not None:
            if ig < 1.0:
                score += 0.5
            elif ig > 2.5:
                score -= 1.0

        return round(max(0.0, min(10.0, score)), 2)
