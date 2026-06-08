"""Agent sentiment — StockTwits retail + Glassnode BTC on-chain (free tier)."""
import asyncio
import logging
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

STOCKTWITS_SYMBOLS = ["AAPL", "TSLA", "SPY", "BTC.X"]
STOCKTWITS_BASE    = "https://api.stocktwits.com/api/2/streams/symbol/{symbol}.json"
GLASSNODE_BASE     = "https://api.glassnode.com/v1/metrics/indicators/mvrv_ratio"


class SentimentAgent:
    name = "Sentiment"

    def __init__(self):
        from desk_liquidite.config import GLASSNODE_API_KEY
        self._gn_key = GLASSNODE_API_KEY

    async def run(self) -> dict[str, Any]:
        loop = asyncio.get_event_loop()
        st_data, gn_data = await asyncio.gather(
            loop.run_in_executor(None, self._fetch_stocktwits),
            loop.run_in_executor(None, self._fetch_glassnode),
            return_exceptions=True,
        )
        if isinstance(st_data, Exception):
            st_data = {"error": str(st_data)}
        if isinstance(gn_data, Exception):
            gn_data = {"error": str(gn_data)}

        score = self._compute_score(st_data, gn_data)
        return {
            "agent":           self.name,
            "timestamp":       datetime.utcnow().isoformat(),
            "data":            {"stocktwits": st_data, "glassnode": gn_data},
            "liquidity_score": score,
            "summary":         self._build_summary(st_data, gn_data, score),
        }

    def _fetch_stocktwits(self) -> dict:
        import requests
        results = {}
        for sym in STOCKTWITS_SYMBOLS:
            try:
                r = requests.get(
                    STOCKTWITS_BASE.format(symbol=sym),
                    timeout=8,
                    headers={"User-Agent": "KingFund/1.0"},
                )
                if r.status_code != 200:
                    results[sym] = {"error": f"HTTP {r.status_code}"}
                    continue
                messages = r.json().get("messages", [])
                bullish = sum(
                    1 for m in messages
                    if (m.get("entities", {}).get("sentiment") or {}).get("basic") == "Bullish"
                )
                bearish = sum(
                    1 for m in messages
                    if (m.get("entities", {}).get("sentiment") or {}).get("basic") == "Bearish"
                )
                total   = bullish + bearish
                results[sym] = {
                    "bullish_count":  bullish,
                    "bearish_count":  bearish,
                    "total_labelled": total,
                    "bullish_pct":    round(bullish / total * 100, 1) if total else 50.0,
                }
            except Exception as exc:
                results[sym] = {"error": str(exc)}
        return results

    def _fetch_glassnode(self) -> dict:
        if not self._gn_key:
            return {"error": "GLASSNODE_API_KEY non configurée"}
        try:
            import requests
            r = requests.get(
                GLASSNODE_BASE,
                params={"a": "BTC", "api_key": self._gn_key},
                timeout=10,
            )
            if r.status_code != 200:
                return {"error": f"Glassnode HTTP {r.status_code}"}
            data = r.json()
            if not data:
                return {"error": "Glassnode: réponse vide"}
            latest = data[-1]
            mvrv   = round(float(latest.get("v", 0)), 3)
            interp = (
                "SURVALORISE" if mvrv > 3.0 else
                "SOUSVALORISE" if mvrv < 1.0 else
                "NEUTRE"
            )
            return {
                "mvrv_ratio":      mvrv,
                "interpretation":  interp,
                "timestamp_gn":    latest.get("t"),
            }
        except Exception as exc:
            return {"error": str(exc)}

    def _compute_score(self, st_data: dict, gn_data: dict) -> float:
        score = 5.0

        # StockTwits : bullish% moyen sur les symboles valides
        pcts = []
        for sym, info in st_data.items():
            if "error" not in info and info.get("total_labelled", 0) > 0:
                pcts.append(info["bullish_pct"])
        if pcts:
            avg_bull = sum(pcts) / len(pcts)
            # bullish% 70+ → +1.5 (euphorie retail = risque de retournement → neutre/légèrement neg)
            # bullish% 30- → +1.5 (panique retail = opportunité achat = score liquidité +)
            if avg_bull > 70:
                score -= 1.0   # retail trop optimiste → signe de top
            elif avg_bull > 55:
                score += 0.5
            elif avg_bull < 30:
                score += 1.5   # capitulation retail → opportunité
            elif avg_bull < 45:
                score -= 0.5

        # Glassnode MVRV
        if "error" not in gn_data:
            mvrv = gn_data.get("mvrv_ratio", 0)
            if mvrv > 3.0:
                score -= 1.5   # BTC survalué → risque
            elif mvrv < 1.0:
                score += 1.5   # BTC sous-valorisé → opportunité
            elif mvrv < 2.0:
                score += 0.5

        return round(max(0.0, min(10.0, score)), 2)

    def _build_summary(self, st_data: dict, gn_data: dict, score: float) -> str:
        mvrv = gn_data.get("mvrv_ratio", "n/a") if "error" not in gn_data else "n/a"
        st_parts = []
        for sym, info in st_data.items():
            if "error" not in info:
                st_parts.append(f"{sym}={info.get('bullish_pct', 0):.0f}%bull")
        st_str = " ".join(st_parts) if st_parts else "n/a"
        return f"Retail: {st_str} | BTC MVRV={mvrv} | score={score}/10"
