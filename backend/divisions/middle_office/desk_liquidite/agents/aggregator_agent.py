"""Agent 8 - Aggregateur: consolide les 7 agents, calcule score global, affiche rapport."""
from datetime import datetime
from typing import Any


AGENT_WEIGHTS = {
    "FRED_Macro":        0.20,
    "FRED_Credit":       0.20,
    "Yahoo_Equity":      0.15,
    "Yahoo_ETF":         0.15,
    "Yahoo_Forex":       0.10,
    "CoinGecko_Market":  0.10,
    "CoinGecko_DeFi":    0.10,
    # Thèse Bertez : énergie/PIB, dette productive, Bastiat hors bilan
    "Bertez_Energy":     0.15,
}

SCORE_THRESHOLDS = {
    "critique":  (0.0, 3.0),
    "tendu":     (3.0, 5.0),
    "neutre":    (5.0, 6.5),
    "ample":     (6.5, 8.0),
    "abondant":  (8.0, 10.01),
}

ALERT_THRESHOLDS = {
    "score_bas":    3.5,
    "score_eleve":  8.5,
}


class LiquidityAggregatorAgent:
    name = "Aggregator"

    def run(self, agent_results: list[dict[str, Any]]) -> dict[str, Any]:
        scores = {}
        errors = []
        summaries = {}
        bertez_data: dict[str, Any] = {}

        for result in agent_results:
            agent_name = result.get("agent", "unknown")
            if "error" in result:
                errors.append(f"{agent_name}: {result['error']}")
                continue
            score = result.get("liquidity_score")
            if score is not None:
                scores[agent_name] = score
            summaries[agent_name] = result.get("summary", "")
            if agent_name == "Bertez_Energy":
                bertez_data = {
                    "signal": result.get("bertez_signal"),
                    "mode":   result.get("mode"),
                    "data":   result.get("data", {}),
                }

        global_score = self._weighted_score(scores)
        regime = self._classify_regime(global_score)
        alerts = self._generate_alerts(global_score, scores)
        report = self._build_report(
            global_score, regime, scores, summaries, alerts, errors, bertez_data
        )

        return {
            "agent":                self.name,
            "timestamp":            datetime.utcnow().isoformat(),
            "global_liquidity_score": global_score,
            "regime":               regime,
            "agent_scores":         scores,
            "agent_summaries":      summaries,
            "alerts":               alerts,
            "errors":               errors,
            "report":               report,
            "bertez_signal":        bertez_data.get("signal"),
            "bertez_mode":          bertez_data.get("mode"),
        }

    def _weighted_score(self, scores: dict[str, float]) -> float:
        total_weight = 0.0
        weighted_sum = 0.0
        for agent_name, score in scores.items():
            w = AGENT_WEIGHTS.get(agent_name, 0.0)
            weighted_sum += score * w
            total_weight += w
        if total_weight == 0:
            return 5.0
        raw = weighted_sum / total_weight
        return round(raw, 2)

    def _classify_regime(self, score: float) -> str:
        for label, (lo, hi) in SCORE_THRESHOLDS.items():
            if lo <= score < hi:
                return label
        return "inconnu"

    def _generate_alerts(self, global_score: float, scores: dict) -> list[str]:
        alerts = []
        if global_score <= ALERT_THRESHOLDS["score_bas"]:
            alerts.append(f"ALERTE CRITIQUE: score global={global_score}/10 - liquidite tres tendue")
        if global_score >= ALERT_THRESHOLDS["score_eleve"]:
            alerts.append(f"SIGNAL: score global={global_score}/10 - conditions tres accommodantes")

        for agent, score in scores.items():
            if score <= 2.5:
                alerts.append(f"ALERTE {agent}: score={score}/10")
            elif score >= 9.0:
                alerts.append(f"SIGNAL {agent}: score={score}/10 - exuberance")
        return alerts

    def _build_report(
        self,
        global_score: float,
        regime: str,
        scores: dict,
        summaries: dict,
        alerts: list,
        errors: list,
        bertez_data: dict | None = None,
    ) -> str:
        now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
        lines = [
            "=" * 60,
            f"  DESK LIQUIDITE - RAPPORT GLOBAL",
            f"  {now}",
            "=" * 60,
            f"  SCORE GLOBAL  : {global_score:>5.2f} / 10",
            f"  REGIME        : {regime.upper()}",
            "-" * 60,
            "  SCORES PAR AGENT",
        ]
        bar_width = 20
        for agent, score in sorted(scores.items(), key=lambda x: -x[1]):
            filled = int(score / 10 * bar_width)
            bar = "#" * filled + "." * (bar_width - filled)
            lines.append(f"  {agent:<22} [{bar}] {score:>5.2f}/10")

        if summaries:
            lines += ["-" * 60, "  RESUME PAR SOURCE"]
            for agent, summary in summaries.items():
                lines.append(f"  {agent:<22} {summary}")

        if bertez_data:
            lines += ["-" * 60, "  SIGNAL BERTEZ — ENERGIE / PIB"]
            mode = bertez_data.get("mode", "NEUTRE")
            sig  = bertez_data.get("signal")
            d    = bertez_data.get("data", {})
            eg   = d.get("energy_gdp", {})
            pd_  = d.get("productive_debt", {})
            bast = d.get("bastiat", {})
            rot  = d.get("rotation", {})

            sig_str = f"{sig:+.3f}" if sig is not None else "N/A"
            lines.append(f"  MODE           : {mode}")
            lines.append(f"  Signal [-1,+1] : {sig_str}")

            chg = eg.get("change_pct")
            wti = eg.get("wti_latest")
            if chg is not None:
                lines.append(f"  Energie/PIB Δ12m: {chg:+.1f}%")
            if wti:
                lines.append(f"  WTI            : {wti} $/b")

            pa = pd_.get("assessment")
            if pa:
                ratio = pd_.get("ratio")
                lines.append(f"  Dette prod.    : {pa}  (ratio={ratio})")

            b_level = bast.get("risk_level")
            b_score = bast.get("risk_score")
            if b_level:
                lines.append(f"  Bastiat risque : {b_level}  (score={b_score}/10)")
            for flag in bast.get("flags", []):
                lines.append(f"    • {flag}")

            if mode == "DEFENSIF" and rot.get("active"):
                prices = rot.get("prices", {})
                chg5d  = rot.get("chg_5d_pct", {})
                if prices:
                    lines.append("  ROTATION DEFENSIVE :")
                    for t, p in list(prices.items())[:6]:
                        c = chg5d.get(t)
                        c_str = f"  {c:+.1f}%5j" if c is not None else ""
                        lines.append(f"    {t:<10} {p:>8.2f}{c_str}")

        if alerts:
            lines += ["-" * 60, "  ALERTES & SIGNAUX"]
            for alert in alerts:
                lines.append(f"  !! {alert}")

        if errors:
            lines += ["-" * 60, "  ERREURS"]
            for err in errors:
                lines.append(f"  [ERR] {err}")

        lines.append("=" * 60)
        return "\n".join(lines)
