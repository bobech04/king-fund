"""Agent 9 — Bertez Energy: économie comme énergie transformée. Thèse complète de Bruno Bertez.

5 piliers :
  1. L'économie est de l'énergie transformée → ratio énergie/PIB (FRED + EIA)
  2. Dette productive vs consommée → ratio investissement privé / dette souveraine
  3. Dette hors bilan énergétique des États → dépendance France/EU via Eurostat
  4. Signal rotation défensif si ratio énergie/PIB +15% → XLE, XLU, XLRE, GLD, TTE.PA…
  5. Principe Bastiat → risques hors bilan invisibles

Intégration :
  - Morning Brief : _get_bertez_block() lit le cache via get_last_bertez_result()
  - Risk Committee : importer get_last_bertez_result() et bertez_signal
  - ExpertSignalClient : ajouter "Bertez_Energy" dans _DOMAINS si besoin
"""
import asyncio
import logging
import os
from datetime import datetime, timedelta
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

# ── Séries FRED ──────────────────────────────────────────────────────────────

# Séries pour comparaison 12 mois (pilier 1)
_FRED_12M = {
    "energy_cpi":  "CPIENGSL",        # CPI Energie, mensuel, index 1982-84=100
    "nominal_gdp": "GDP",             # PIB nominal, trimestriel, milliards USD
    "wti_crude":   "DCOILWTICO",      # WTI crude, quotidien (→ dernière obs)
}

# Séries courantes (pilier 2 — dette productive)
_FRED_CURRENT = {
    "private_invest": "PNFI",         # Investissement privé non-résidentiel, Mds USD
    "federal_debt":   "GFDEBTN",      # Dette totale fédérale US, millions USD
    "real_gdp_growth":"A191RL1Q225SBEA", # Croissance PIB réel, %
    "net_exports":    "NETEXP",       # Exportations nettes (proxy balance commerciale)
}

# ── Actifs rotation Bertez (mode DEFENSIF) ───────────────────────────────────

ROTATION_ASSETS = {
    "etf_energie":       ["XLE"],
    "etf_infra":         ["XLU", "XLRE"],
    "or":                ["GLD"],
    "energie_europe":    ["TTE.PA", "SU.PA"],
    "infrastructure_fr": ["VIE.PA", "GTT.PA"],
    "materiaux_stockage":["VPK.AS", "AI.PA"],
}

ROTATION_TICKERS_FLAT = [
    "XLE", "XLU", "XLRE", "GLD",
    "TTE.PA", "AI.PA", "VIE.PA", "VPK.AS", "GTT.PA", "SU.PA",
]

# ── Seuils ───────────────────────────────────────────────────────────────────

ENERGY_GDP_ALERT_PCT = 15.0   # % hausse ratio énergie/PIB → mode DEFENSIF
PROD_DEBT_FLOOR      = 0.08   # ratio invest/dette < 8% → économie consommatrice
EU_DEPENDENCY_ALERT  = 55.0   # dépendance énergétique EU/FR > 55% → hors bilan

# ── Eurostat & EIA ───────────────────────────────────────────────────────────

_EUROSTAT_URL = (
    "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/"
    "nrg_ind_id?geo=FR&geo=EU27_2020&lang=en&lastTimePeriod=5"
)

_EIA_BASE = "https://api.eia.gov/v2"


# ── Agent ─────────────────────────────────────────────────────────────────────

class BertezEnergyAgent:
    name = "Bertez_Energy"

    def __init__(self):
        self._fred_client = None

    # ── FRED helpers ─────────────────────────────────────────────────────────

    def _get_fred(self):
        if self._fred_client is None:
            from fredapi import Fred
            from desk_liquidite.config import FRED_API_KEY
            if not FRED_API_KEY:
                raise ValueError("FRED_API_KEY manquant dans .env")
            self._fred_client = Fred(api_key=FRED_API_KEY)
        return self._fred_client

    def _fetch_current(self, series_id: str, periods: int = 12) -> dict[str, Any]:
        fred = self._get_fred()
        end   = datetime.today()
        start = end - timedelta(days=periods * 35)
        raw   = fred.get_series(series_id, observation_start=start.strftime("%Y-%m-%d")).dropna()
        if raw.empty:
            return {"latest": None, "change_pct": None, "trend": "N/A"}
        latest = float(raw.iloc[-1])
        prev   = float(raw.iloc[-2]) if len(raw) >= 2 else latest
        chg    = round((latest - prev) / abs(prev) * 100, 4) if prev != 0 else 0.0
        return {
            "latest":     round(latest, 4),
            "prev":       round(prev, 4),
            "date":       str(raw.index[-1].date()),
            "change_pct": chg,
            "trend":      "up" if chg > 0 else ("down" if chg < 0 else "flat"),
        }

    def _fetch_12m_change(self, series_id: str) -> dict[str, Any]:
        """Valeur courante + valeur d'il y a ~12 mois pour calculer la variation."""
        fred   = self._get_fred()
        end    = datetime.today()
        start  = end - timedelta(days=420)
        raw    = fred.get_series(series_id, observation_start=start.strftime("%Y-%m-%d")).dropna()
        if len(raw) < 2:
            return {"latest": None, "year_ago": None, "change_12m_pct": None}
        latest  = float(raw.iloc[-1])
        cutoff  = raw.index[-1] - timedelta(days=365)
        past    = raw[raw.index <= cutoff]
        year_ago = float(past.iloc[-1]) if not past.empty else float(raw.iloc[0])
        chg     = round((latest - year_ago) / abs(year_ago) * 100, 4) if year_ago != 0 else 0.0
        return {
            "latest":         round(latest, 4),
            "year_ago":       round(year_ago, 4),
            "date":           str(raw.index[-1].date()),
            "change_12m_pct": chg,
        }

    # ── Sources async (Eurostat + EIA) ───────────────────────────────────────

    async def _fetch_eurostat(self) -> dict[str, Any]:
        """
        Pilier 3 — Dépendance énergétique France + EU27 via Eurostat.
        Dataset nrg_ind_id = Energy import dependency (%).
        Hors bilan : drain invisible sur la capacité productive souveraine.
        """
        try:
            import aiohttp
        except ImportError:
            return {"error": "aiohttp non installé — pip install aiohttp"}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    _EUROSTAT_URL, timeout=aiohttp.ClientTimeout(total=20)
                ) as resp:
                    if resp.status != 200:
                        return {"error": f"Eurostat HTTP {resp.status}"}
                    js = await resp.json(content_type=None)

            values   = js.get("value", {})
            dims     = js.get("dimension", {})
            geo_idx  = dims.get("geo", {}).get("category", {}).get("index", {})
            time_idx = dims.get("time", {}).get("category", {}).get("index", {})
            n_time   = len(time_idx)

            result: dict[str, Any] = {}
            for geo_code, g_pos in geo_idx.items():
                # Prend la dernière période disponible
                for t_label, t_pos in sorted(time_idx.items(), key=lambda x: -x[1]):
                    flat = str(g_pos * n_time + t_pos)
                    if flat in values:
                        result[geo_code] = {
                            "dependency_pct": round(float(values[flat]), 2),
                            "year":           t_label,
                        }
                        break
            return result or {"error": "Eurostat aucune valeur parsée"}
        except Exception as exc:
            return {"error": str(exc)}

    async def _fetch_eia_wti(self) -> dict[str, Any]:
        """
        Pilier 1 (backup) — Prix WTI hebdomadaire via EIA API v2.
        Actif seulement si EIA_API_KEY présent dans .env.
        """
        eia_key = os.getenv("EIA_API_KEY", "")
        if not eia_key:
            return {"error": "EIA_API_KEY absent — FRED WTI utilisé en priorité"}
        try:
            import aiohttp
        except ImportError:
            return {"error": "aiohttp non installé"}
        try:
            url = (
                f"{_EIA_BASE}/petroleum/pri/spt/data/"
                f"?api_key={eia_key}&frequency=weekly&data[0]=value"
                f"&facets[series][]=EMD_EPD2D_PTE_NUS_DPG"
                f"&sort[0][column]=period&sort[0][direction]=desc&length=54"
            )
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status != 200:
                        return {"error": f"EIA HTTP {resp.status}"}
                    js = await resp.json()
            rows = js.get("response", {}).get("data", [])
            if not rows:
                return {"error": "EIA: aucune donnée"}
            latest   = float(rows[0]["value"])
            year_ago = float(rows[-1]["value"]) if len(rows) > 1 else latest
            chg      = round((latest - year_ago) / abs(year_ago) * 100, 2) if year_ago else 0.0
            return {
                "latest":         round(latest, 2),
                "year_ago":       round(year_ago, 2),
                "change_12m_pct": chg,
                "period":         rows[0].get("period", ""),
                "source":         "EIA",
            }
        except Exception as exc:
            return {"error": str(exc)}

    # ── Calculs Bertez ───────────────────────────────────────────────────────

    def _compute_energy_gdp_ratio(self, fred: dict) -> dict[str, Any]:
        """
        Pilier 1 : ratio énergie/PIB.
        Proxy = energy_cpi / nominal_gdp (normalisé ×1000).
        Signal DEFENSIF si hausse > +15% sur 12 mois (seuil Bertez).
        """
        e  = fred.get("energy_cpi", {})
        g  = fred.get("nominal_gdp", {})

        e_now, e_past = e.get("latest"), e.get("year_ago")
        g_now, g_past = g.get("latest"), g.get("year_ago")

        if None in (e_now, e_past, g_now, g_past) or g_now == 0 or g_past == 0:
            return {"ratio_now": None, "change_pct": None, "signal": "INCONNU"}

        ratio_now  = e_now  / g_now  * 1000
        ratio_past = e_past / g_past * 1000
        chg        = round((ratio_now - ratio_past) / abs(ratio_past) * 100, 2)

        if chg >= ENERGY_GDP_ALERT_PCT:
            signal = "DEFENSIF"
        elif chg <= -ENERGY_GDP_ALERT_PCT:
            signal = "OFFENSIF"
        else:
            signal = "NEUTRE"

        return {
            "ratio_now":  round(ratio_now,  4),
            "ratio_past": round(ratio_past, 4),
            "change_pct": chg,
            "signal":     signal,
            "wti_latest": (fred.get("wti_crude") or {}).get("latest"),
            "wti_chg12m": (fred.get("wti_crude") or {}).get("change_12m_pct"),
        }

    def _compute_productive_debt(self, fred: dict) -> dict[str, Any]:
        """
        Pilier 2 : dette productive vs consommée (Bertez).
        Ratio = investissement privé (Mds USD) / dette fédérale (Mds USD).
        Déclin du ratio → économie consomme le capital plutôt qu'investir.
        """
        inv_data   = fred.get("private_invest", {})
        debt_data  = fred.get("federal_debt",   {})

        invest  = inv_data.get("latest")
        debt_m  = debt_data.get("latest")   # en millions USD dans FRED

        if invest is None or debt_m is None or debt_m == 0:
            return {"ratio": None, "assessment": "INCONNU"}

        debt_b = debt_m / 1000              # millions → milliards
        ratio  = round(invest / debt_b, 4)

        invest_chg = inv_data.get("change_pct", 0) or 0
        debt_chg   = debt_data.get("change_pct", 0) or 0
        delta      = round(invest_chg - debt_chg, 2)

        if ratio < PROD_DEBT_FLOOR:
            assessment = "CRITIQUE"         # dette écrase l'investissement
        elif delta < -5:
            assessment = "DEGRADATION"      # dette croît plus vite
        elif delta > 5:
            assessment = "AMELIORATION"
        else:
            assessment = "STABLE"

        return {
            "ratio":       ratio,
            "invest_mds":  round(invest, 2),
            "debt_mds":    round(debt_b, 2),
            "invest_chg":  round(invest_chg, 2),
            "debt_chg":    round(debt_chg, 2),
            "delta":       delta,
            "assessment":  assessment,
        }

    def _compute_bastiat_risk(
        self,
        energy_gdp:  dict,
        prod_debt:   dict,
        eu_dep:      dict,
    ) -> dict[str, Any]:
        """
        Pilier 5 : Principe Bastiat — risques hors bilan invisibles.

        Bastiat distingue ce qu'on VOIT (PIB officiel, dette nominale)
        de ce qu'on NE VOIT PAS (drain énergétique, dépendance importée,
        capital consommé déguisé en croissance).

        Score 0-10 : 10 = risques systémiques cachés très élevés.
        """
        score = 0.0
        flags = []

        # Stress énergie/PIB
        chg = energy_gdp.get("change_pct")
        if chg is not None:
            if chg >= ENERGY_GDP_ALERT_PCT:
                score += 3.5
                flags.append(
                    f"ratio énergie/PIB +{chg:.1f}% → charge cachée sur marges réelles"
                )
            elif chg >= 8:
                score += 1.5
                flags.append(f"ratio énergie/PIB +{chg:.1f}% → pression montante non encore visible")

        # Dette non productive
        pa = prod_debt.get("assessment", "STABLE")
        if pa == "CRITIQUE":
            score += 3.0
            flags.append(
                f"ratio invest/dette={prod_debt.get('ratio'):.4f} → "
                "économie consommatrice, capital invisible détruit"
            )
        elif pa == "DEGRADATION":
            score += 1.5
            flags.append("invest/dette se dégrade → destructions futures masquées par effet base")

        # Dépendance énergétique France/EU (Bastiat : drain hors bilan souverain)
        if isinstance(eu_dep, dict) and not eu_dep.get("error"):
            fr_data  = eu_dep.get("FR", {})
            eu27_data = eu_dep.get("EU27_2020", {})
            fr_pct   = fr_data.get("dependency_pct")
            eu_pct   = eu27_data.get("dependency_pct")
            yr       = fr_data.get("year", eu27_data.get("year", ""))

            if fr_pct is not None and fr_pct > EU_DEPENDENCY_ALERT:
                score += 2.0
                flags.append(
                    f"France dépendance énergétique {fr_pct}% ({yr}) → "
                    "passif hors bilan non comptabilisé dans dette publique"
                )
            if eu_pct is not None and eu_pct > EU_DEPENDENCY_ALERT:
                score += 0.5
                flags.append(f"EU27 dépendance {eu_pct}% ({yr}) → fragilité systémique zone euro")
        else:
            flags.append("Eurostat indisponible — dépendance énergétique non vérifiée (risque inconnu)")

        return {
            "risk_score":  round(min(score, 10.0), 2),
            "risk_level":  "ELEVE" if score >= 5 else ("MODERE" if score >= 2.5 else "FAIBLE"),
            "flags":       flags,
            "fr_dep_pct":  (eu_dep.get("FR", {}) if isinstance(eu_dep, dict) else {}).get("dependency_pct"),
            "eu_dep_pct":  (eu_dep.get("EU27_2020", {}) if isinstance(eu_dep, dict) else {}).get("dependency_pct"),
        }

    def _screen_rotation_assets(self, mode: str) -> dict[str, Any]:
        """
        Pilier 4 : screener rotation Bertez.
        Mode DEFENSIF → prix actuels + momentum 5j de tous les actifs recommandés.
        Secteurs : énergie, infrastructure, stockage, transport, matières premières, eau, or.
        """
        if mode != "DEFENSIF":
            return {"mode": mode, "assets": ROTATION_ASSETS, "active": False, "prices": {}}

        try:
            import yfinance as yf
            data = yf.download(
                ROTATION_TICKERS_FLAT,
                period="5d",
                interval="1d",
                progress=False,
                auto_adjust=True,
            )
            prices: dict[str, float] = {}
            chg5d:  dict[str, float] = {}

            close = data.get("Close")
            if close is not None and not close.empty:
                last_row  = close.iloc[-1]
                first_row = close.iloc[0]
                for t in ROTATION_TICKERS_FLAT:
                    if t in last_row.index:
                        val = last_row[t]
                        if not pd.isna(val):
                            prices[t] = round(float(val), 2)
                        v0 = first_row[t]
                        if not pd.isna(val) and not pd.isna(v0) and float(v0) != 0:
                            chg5d[t] = round((float(val) - float(v0)) / float(v0) * 100, 2)

            return {
                "mode":       mode,
                "assets":     ROTATION_ASSETS,
                "active":     True,
                "prices":     prices,
                "chg_5d_pct": chg5d,
                "count":      len(prices),
            }
        except Exception as exc:
            return {
                "mode":   mode,
                "assets": ROTATION_ASSETS,
                "active": True,
                "prices": {},
                "error":  str(exc),
            }

    def _compute_score_and_mode(
        self,
        energy_gdp: dict,
        prod_debt:  dict,
        bastiat:    dict,
    ) -> tuple[float, str]:
        """
        Convertit les 3 piliers en score 0-10 compatible avec l'agrégateur.
        Score élevé = conditions favorables (énergie bon marché, économie productive).
        Score bas   = stress énergétique, économie consommatrice → signal DEFENSIF.
        """
        score = 5.0

        chg = energy_gdp.get("change_pct") or 0
        if chg >= ENERGY_GDP_ALERT_PCT:
            score -= 2.5
        elif chg >= 8:
            score -= 1.0
        elif chg <= -ENERGY_GDP_ALERT_PCT:
            score += 2.0
        elif chg <= -8:
            score += 1.0

        pa = prod_debt.get("assessment", "STABLE")
        if pa == "CRITIQUE":
            score -= 2.0
        elif pa == "DEGRADATION":
            score -= 1.0
        elif pa == "AMELIORATION":
            score += 1.5

        # Bastiat pèse jusqu'à −3.0 pts (risk_score 0-10 → factor 0.30)
        score -= bastiat.get("risk_score", 0) * 0.30

        final = round(max(0.0, min(10.0, score)), 2)

        if final <= 3.5:
            mode = "DEFENSIF"
        elif final >= 7.0:
            mode = "OFFENSIF"
        else:
            mode = "NEUTRE"

        return final, mode

    # ── Point d'entrée async ─────────────────────────────────────────────────

    async def run(self) -> dict[str, Any]:
        loop = asyncio.get_running_loop()

        # Pilier 1 & 2 — FRED (synchrones, dans executor)
        fred: dict = {}
        for key, series_id in _FRED_12M.items():
            try:
                fred[key] = await loop.run_in_executor(
                    None, self._fetch_12m_change, series_id
                )
            except Exception as exc:
                fred[key] = {"error": str(exc)}

        for key, series_id in _FRED_CURRENT.items():
            try:
                fred[key] = await loop.run_in_executor(
                    None, self._fetch_current, series_id
                )
            except Exception as exc:
                fred[key] = {"error": str(exc)}

        # Pilier 1 (backup EIA) + Pilier 3 (Eurostat) en parallèle
        eu_dep, eia_wti = await asyncio.gather(
            self._fetch_eurostat(),
            self._fetch_eia_wti(),
            return_exceptions=True,
        )
        if isinstance(eu_dep,  Exception):
            eu_dep  = {"error": str(eu_dep)}
        if isinstance(eia_wti, Exception):
            eia_wti = {"error": str(eia_wti)}

        # Calculs Bertez
        energy_gdp = self._compute_energy_gdp_ratio(fred)
        prod_debt  = self._compute_productive_debt(fred)
        bastiat    = self._compute_bastiat_risk(energy_gdp, prod_debt, eu_dep)

        score, mode = self._compute_score_and_mode(energy_gdp, prod_debt, bastiat)

        # Pilier 4 : screener rotation (synchrone, dans executor)
        rotation = await loop.run_in_executor(
            None, self._screen_rotation_assets, mode
        )

        # Signal [-1, +1] pour ExpertSignalClient
        bertez_signal = round((score - 5.0) / 5.0, 3)

        wti   = (fred.get("wti_crude") or {}).get("latest") or \
                (eia_wti if not (isinstance(eia_wti, dict) and "error" in eia_wti) else {}).get("latest")
        e_chg = energy_gdp.get("change_pct")

        result: dict[str, Any] = {
            "agent":          self.name,
            "timestamp":      datetime.utcnow().isoformat(),
            "data": {
                "fred":            fred,
                "eurostat":        eu_dep,
                "eia_wti":         eia_wti,
                "energy_gdp":      energy_gdp,
                "productive_debt": prod_debt,
                "bastiat":         bastiat,
                "rotation":        rotation,
            },
            "liquidity_score": score,
            "mode":            mode,
            "bertez_signal":   bertez_signal,
            "summary": (
                f"WTI={wti}$/b | énergie/PIB Δ12m={e_chg}% | "
                f"mode={mode} | Bastiat={bastiat['risk_level']} | score={score}/10"
            ),
        }

        # Cache module pour Morning Brief + Risk Committee
        global _last_result
        _last_result = result

        # Historique prédictif — un enregistrement par jour calendaire
        try:
            from data.signal_history import log_signal as _log_sig
            _log_sig(
                "bertez",
                direction=mode.lower(),
                confidence=abs(bertez_signal),
                mode=mode,
                score=score,
            )
        except Exception:
            pass

        return result


# ── Cache module-level ────────────────────────────────────────────────────────

_last_result: dict | None = None


def get_last_bertez_result() -> dict | None:
    """Retourne le dernier résultat de l'agent Bertez (thread-safe en lecture)."""
    return _last_result


def get_bertez_signal() -> float:
    """Signal Bertez en [-1, +1] pour le Risk Committee et ExpertSignalClient."""
    r = _last_result
    return float(r["bertez_signal"]) if r else 0.0


def get_bertez_mode() -> str:
    """Mode courant : 'DEFENSIF', 'NEUTRE' ou 'OFFENSIF'."""
    r = _last_result
    return r["mode"] if r else "NEUTRE"
