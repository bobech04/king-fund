"""
AgentDueDiligence — analyse chaque candidat du screener.

Pour chaque ticker :
  1. Pipeline InvestmentPipeline (17 étapes Graham-Buffett-Damodaran)
  2. DCF / WACC Damodaran explicite
  3. Marge de sécurité vs valeur intrinsèque
  4. EDGAR (SEC API) pour les 10-K / 10-Q US — ratio dettes long terme, FCF réel
  5. Qualité des bénéfices (ACCRUALS ratio)
Score final sur 17 + EDGAR overlay → dictionnaire complet par candidat.
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any

import requests
import yfinance as yf

logger = logging.getLogger(__name__)

_ERP        = 0.055        # prime de risque actions US historique
_EDGAR_BASE = "https://data.sec.gov/submissions/CIK{cik}.json"
_EDGAR_FACT = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
_EDGAR_HDR  = {"User-Agent": "KingFund research@kingfund.ai"}
_EDGAR_TTL  = 86_400       # 24h


def _safe(val, default=None):
    if val is None:
        return default
    try:
        f = float(val)
        return f if f == f else default
    except (TypeError, ValueError):
        return default


def _pct(val):
    """Convertit une valeur décimale en pourcentage arrondi."""
    if val is None:
        return None
    return round(float(val) * 100, 2)


class AgentDueDiligence:
    """
    Analyse approfondie des 10 candidats issus du ScreenerMondial.
    Délégation de la notation à InvestmentPipeline (17 étapes).
    Overlay EDGAR pour les titres US (ticker sans suffixe bourse).
    """

    def __init__(self) -> None:
        self._lock        = threading.Lock()
        self._pipeline    = None     # chargé lazily pour éviter l'import circulaire
        self._fred        = None
        self._edgar_cache: dict[str, dict] = {}
        self._edgar_ts:    dict[str, float] = {}

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def analyser(self, candidats: list[dict]) -> list[dict[str, Any]]:
        """Analyse les candidats en entrée et retourne les résultats enrichis."""
        self._lazy_init()
        resultats = []
        for c in candidats:
            ticker = c["ticker"]
            logger.info("[DueDiligence] Analyse %s — %s", ticker, c.get("nom", ""))
            r = self._analyser_un(c)
            resultats.append(r)
            time.sleep(0.5)   # politesse Yahoo Finance
        return resultats

    # ------------------------------------------------------------------
    # Analyse individuelle
    # ------------------------------------------------------------------

    def _analyser_un(self, candidat: dict) -> dict[str, Any]:
        ticker = candidat["ticker"]
        ts     = datetime.now(timezone.utc).isoformat()
        try:
            # 1. Pipeline 17 étapes
            pipeline_result = self._pipeline.analyze(ticker)
            score_pipeline  = pipeline_result["score"]
            signal_pipeline = pipeline_result["signal"]
            stages          = pipeline_result["stages"]

            # 2. Données yfinance étendues
            info    = yf.Ticker(ticker).info or {}
            prix    = _safe(info.get("currentPrice"))
            target  = _safe(info.get("targetMeanPrice"))
            fcf     = _safe(info.get("freeCashflow"))
            mcap    = _safe(info.get("marketCap"), 1.0)
            beta    = _safe(info.get("beta"), 1.0)
            de      = _safe(info.get("debtToEquity"), 0.0)
            growth  = min(_safe(info.get("revenueGrowth"), 0.03), 0.15)

            # 3. WACC Damodaran explicite
            fed_rate = self._get_fed_rate()
            wacc     = self._calc_wacc(beta, de, fed_rate)

            # 4. DCF Gordon Growth
            valeur_dcf, marge_securite_dcf = self._calc_dcf(fcf, mcap, growth, wacc)

            # 5. Marge de sécurité analyste
            marge_analyste = ((target - prix) / prix) if (prix and target and prix > 0) else None

            # 6. EDGAR overlay (US uniquement — ticker sans point ni suffixe bourse)
            edgar_data = self._fetch_edgar(ticker)

            # 7. Score DD final = pipeline + bonus EDGAR
            score_edgar_bonus = self._edgar_bonus(edgar_data)
            score_final = min(10.0, round(score_pipeline + score_edgar_bonus, 2))
            signal_final = "buy" if score_final >= 7.0 else ("sell" if score_final < 4.0 else "hold")

            return {
                "ticker":            ticker,
                "nom":               candidat.get("nom", ""),
                "marche":            candidat.get("marche", ""),
                "score_pipeline":    score_pipeline,
                "score_final":       score_final,
                "signal":            signal_final.upper(),
                "signal_pipeline":   signal_pipeline.upper(),
                "score_graham":      candidat.get("score_graham"),
                "stages":            stages,
                # Valorisation
                "wacc":              round(wacc * 100, 2),
                "valeur_dcf":        valeur_dcf,
                "marge_securite_dcf":    round(marge_securite_dcf * 100, 1) if marge_securite_dcf is not None else None,
                "marge_securite_analyste": round(marge_analyste * 100, 1) if marge_analyste is not None else None,
                # Données de base
                "prix":              prix,
                "target_analyste":   target,
                "per":               candidat.get("per"),
                "pbr":               candidat.get("pbr"),
                "dividende":         candidat.get("dividende"),
                "dette_equity":      de,
                "croissance_rev":    candidat.get("croissance_rev"),
                "secteur":           candidat.get("secteur"),
                "pays":              candidat.get("pays"),
                # EDGAR
                "edgar":             edgar_data,
                "timestamp":         ts,
            }
        except Exception as e:
            logger.warning("[DueDiligence] %s erreur: %s", ticker, e)
            return {
                "ticker":    ticker,
                "nom":       candidat.get("nom", ""),
                "marche":    candidat.get("marche", ""),
                "erreur":    str(e),
                "timestamp": ts,
            }

    # ------------------------------------------------------------------
    # Finance
    # ------------------------------------------------------------------

    def _calc_wacc(self, beta: float, de: float, rfr: float) -> float:
        cost_equity  = rfr + beta * _ERP
        debt_ratio   = de / (de + 100) if de > 0 else 0.0
        equity_ratio = 1.0 - debt_ratio
        return equity_ratio * cost_equity + debt_ratio * 0.04 * 0.79

    def _calc_dcf(self, fcf, mcap, growth, wacc) -> tuple:
        """Retourne (valeur_dcf, marge_securite)."""
        if not fcf or not mcap or mcap <= 0 or fcf <= 0 or wacc <= growth:
            return None, None
        intrinsic = fcf * (1 + growth) / (wacc - growth)
        marge     = (intrinsic - mcap) / mcap
        return round(intrinsic, 0), marge

    def _get_fed_rate(self) -> float:
        try:
            return self._fred.fed_rate() / 100
        except Exception:
            return 0.043   # fallback Fed rate ~4.3%

    # ------------------------------------------------------------------
    # EDGAR (SEC)
    # ------------------------------------------------------------------

    def _is_us_ticker(self, ticker: str) -> bool:
        return "." not in ticker

    def _fetch_edgar(self, ticker: str) -> dict:
        if not self._is_us_ticker(ticker):
            return {}
        now = time.monotonic()
        with self._lock:
            if ticker in self._edgar_cache and (now - self._edgar_ts.get(ticker, 0)) < _EDGAR_TTL:
                return self._edgar_cache[ticker]
        data = self._pull_edgar(ticker)
        with self._lock:
            self._edgar_cache[ticker] = data
            self._edgar_ts[ticker]    = now
        return data

    def _pull_edgar(self, ticker: str) -> dict:
        try:
            # Recherche CIK via SEC
            search_url = f"https://efts.sec.gov/LATEST/search-index?q=%22{ticker}%22&dateRange=custom&startdt=2020-01-01&forms=10-K"
            # Méthode directe : base de mapping tickers → CIK de la SEC
            cik_map_url = "https://www.sec.gov/files/company_tickers.json"
            r = requests.get(cik_map_url, headers=_EDGAR_HDR, timeout=10)
            if r.status_code != 200:
                return {}
            mapping = r.json()
            # Chercher le ticker dans la map (valeurs sont {cik_str, ticker, title})
            cik = None
            for entry in mapping.values():
                if entry.get("ticker", "").upper() == ticker.upper():
                    cik = str(entry["cik_str"]).zfill(10)
                    break
            if not cik:
                return {}

            # Télécharger les facts XBRL
            facts_url = _EDGAR_FACT.format(cik=cik)
            r2 = requests.get(facts_url, headers=_EDGAR_HDR, timeout=15)
            if r2.status_code != 200:
                return {"cik": cik}

            facts = r2.json().get("facts", {})
            us_gaap = facts.get("us-gaap", {})

            # FCF opérationnel (NetCashProvidedByUsedInOperatingActivities)
            op_cf   = self._last_annual(us_gaap, "NetCashProvidedByUsedInOperatingActivities")
            capex   = self._last_annual(us_gaap, "PaymentsToAcquirePropertyPlantAndEquipment")
            fcf_real = (op_cf - capex) if (op_cf is not None and capex is not None) else None

            # Dette long terme
            lt_debt = self._last_annual(us_gaap, "LongTermDebt")

            # Accruals ratio (qualité bénéfices)
            net_inc = self._last_annual(us_gaap, "NetIncomeLoss")
            accruals = None
            if net_inc and op_cf and net_inc != 0:
                accruals = round((net_inc - op_cf) / abs(net_inc), 3)

            return {
                "cik":             cik,
                "fcf_real":        fcf_real,
                "lt_debt":         lt_debt,
                "op_cash_flow":    op_cf,
                "capex":           capex,
                "accruals_ratio":  accruals,
            }
        except Exception as e:
            logger.debug("[DueDiligence] EDGAR %s: %s", ticker, e)
            return {}

    def _last_annual(self, us_gaap: dict, concept: str):
        """Extrait la dernière valeur annuelle d'un concept US-GAAP."""
        try:
            units = us_gaap.get(concept, {}).get("units", {})
            usd   = units.get("USD", [])
            if not usd:
                return None
            # Filtrer les filings annuels (form 10-K)
            annual = [e for e in usd if e.get("form") in ("10-K", "10-K/A")]
            if not annual:
                annual = usd  # fallback
            last = sorted(annual, key=lambda x: x.get("end", ""), reverse=True)[0]
            return last.get("val")
        except Exception:
            return None

    def _edgar_bonus(self, edgar: dict) -> float:
        """Bonus score +0/-0.5 selon la qualité des bénéfices EDGAR."""
        accruals = edgar.get("accruals_ratio")
        if accruals is None:
            return 0.0
        # Accruals < 0 = cash earnings > accruals → bonne qualité bénéfices
        if accruals < -0.05:
            return 0.3
        if accruals > 0.20:
            return -0.5
        return 0.0

    # ------------------------------------------------------------------
    # Init lazy (évite import circulaire avec pipeline.py)
    # ------------------------------------------------------------------

    def _lazy_init(self):
        if self._pipeline is not None:
            return
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).parent.parent.parent))
        from divisions.investissement.pipeline import InvestmentPipeline
        from data.fred_client import get_fred_client
        self._pipeline = InvestmentPipeline()
        self._fred     = get_fred_client()


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------
_instance: AgentDueDiligence | None = None
_lock = threading.Lock()


def get_due_diligence() -> AgentDueDiligence:
    global _instance
    if _instance is None:
        with _lock:
            if _instance is None:
                _instance = AgentDueDiligence()
    return _instance
