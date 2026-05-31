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

        for result in agent_results:
            agent_name = result.get("agent", "unknown")
            if "error" in result:
                errors.append(f"{agent_name}: {result['error']}")
                continue
            score = result.get("liquidity_score")
            if score is not None:
                scores[agent_name] = score
            summaries[agent_name] = result.get("summary", "")

        global_score = self._weighted_score(scores)
        regime = self._classify_regime(global_score)
        alerts = self._generate_alerts(global_score, scores)
        report = self._build_report(global_score, regime, scores, summaries, alerts, errors)

        return {
            "agent": self.name,
            "timestamp": datetime.utcnow().isoformat(),
            "global_liquidity_score": global_score,
            "regime": regime,
            "agent_scores": scores,
            "agent_summaries": summaries,
            "alerts": alerts,
            "errors": errors,
            "report": report,
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
