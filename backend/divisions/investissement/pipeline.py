"""
divisions.investissement.pipeline
==================================
Pipeline d'analyse fondamentale en 17 étapes.

Inspiré des cadres de Buffett, Graham, Lynch, Damodaran, Dalio,
Soros, Taleb, Klarman et Howard Marks.

Score final : 0–10
  ≥ 7  → buy
  4–6  → hold
  < 4  → sell
"""

import sys
import time
import threading
import logging
from pathlib import Path

import yfinance as yf

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from data.fred_client import get_fred_client
from data.rss_client  import get_rss_client

logger = logging.getLogger(__name__)

_TTL = 3_600   # 1 h — yfinance.info est lent, cache agressif
_ERP = 0.055   # 5.5 % prime de risque actions historique USA

# RSS agrégateur de nouvelles géopolitiques globales (BIS discours)
_GEO_RSS = "https://www.bis.org/doclist/all_speeches.rss"

# Secteurs dans le cercle de compétence (Buffett)
_KNOWN_SECTORS = frozenset([
    "Technology", "Financial Services", "Consumer Cyclical",
    "Consumer Defensive", "Healthcare", "Communication Services",
    "Industrials", "Energy", "Utilities",
])


def _safe(val, default=0.0):
    """Retourne val si c'est un nombre valide, sinon default."""
    if val is None:
        return default
    try:
        f = float(val)
        return f if f == f else default  # NaN check
    except (TypeError, ValueError):
        return default


def _clamp(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


class InvestmentPipeline:
    """
    Analyse un ticker en 17 étapes et produit un score final sur 10.

    Usage :
        pipeline = InvestmentPipeline()
        result   = pipeline.analyze("AAPL", prices)
        print(result["score"], result["signal"])
    """

    def __init__(self):
        self._lock     = threading.Lock()
        self._cache:    dict = {}
        self._cache_ts: dict = {}
        self._fred = get_fred_client()
        self._rss  = get_rss_client()

    # ------------------------------------------------------------------
    # Cache yfinance.info
    # ------------------------------------------------------------------

    def _info(self, symbol: str) -> dict:
        now = time.monotonic()
        with self._lock:
            if symbol in self._cache and now - self._cache_ts[symbol] < _TTL:
                return self._cache[symbol]
        try:
            data = yf.Ticker(symbol).info or {}
        except Exception as e:
            logger.warning(f"yfinance.info [{symbol}]: {e}")
            data = {}
        with self._lock:
            self._cache[symbol]    = data
            self._cache_ts[symbol] = now
        return data

    # ------------------------------------------------------------------
    # 17 étapes — chacune retourne un score dans [-1, +1]
    # ------------------------------------------------------------------

    def _s01_cercle_competence(self, info: dict) -> float:
        """Étape 1 — Cercle de compétence (Buffett)
        Le secteur est-il lisible et prévisible ?
        """
        sector = info.get("sector", "")
        return 1.0 if sector in _KNOWN_SECTORS else 0.0

    def _s02_moat(self, info: dict) -> float:
        """Étape 2 — Moat économique (Buffett / Morningstar)
        Marges brutes élevées + ROE stable → avantage concurrentiel durable.
        """
        gm  = _safe(info.get("grossMargins"))
        roe = _safe(info.get("returnOnEquity"))
        # grossMargins > 40 % = excellent, > 20 % = ok, < 0 = bad
        s_gm  = _clamp((gm - 0.20) / 0.30)
        # ROE > 15 % = fort, < 0 % = faible
        s_roe = _clamp(roe / 0.15)
        return _clamp((s_gm + s_roe) / 2)

    def _s03_management(self, info: dict) -> float:
        """Étape 3 — Qualité du management
        ROE, ROA et actionnariat insiders comme proxies.
        """
        roe      = _safe(info.get("returnOnEquity"))
        roa      = _safe(info.get("returnOnAssets"))
        insiders = _safe(info.get("heldPercentInsiders"))
        s_roe = _clamp(roe / 0.20)
        s_roa = _clamp(roa / 0.10)
        s_ins = _clamp(insiders / 0.10)   # 10 % insiders = max positif
        return _clamp((s_roe + s_roa + s_ins) / 3)

    def _s04_bilan_graham(self, info: dict) -> float:
        """Étape 4 — Bilan Graham
        Ratio courant > 2, dette < capitaux propres.
        """
        cr  = _safe(info.get("currentRatio"),   default=1.0)
        de  = _safe(info.get("debtToEquity"),    default=100.0)
        # current ratio : 2 = excellent, 1 = neutre, < 0.5 = danger
        s_cr = _clamp((cr - 1.0) / 1.5)
        # D/E : 0 = excellent, 50 = neutre, > 150 = danger
        s_de = _clamp((50.0 - de) / 100.0)
        return _clamp((s_cr + s_de) / 2)

    def _s05_croissance_lynch(self, info: dict) -> float:
        """Étape 5 — Croissance Lynch (PEG ratio)
        PEG < 1 = sous-évalué, PEG > 2 = surévalué.
        """
        pe     = _safe(info.get("trailingPE"),     default=25.0)
        growth = _safe(info.get("earningsGrowth"), default=0.0)
        if growth <= 0 or pe <= 0:
            return 0.0
        peg = pe / (growth * 100)   # growth est en décimal, Lynch utilise %
        return _clamp(1.0 - peg)    # PEG=1 → 0, PEG=0.5 → +0.5, PEG=2 → -1.0

    def _s06_fcf(self, info: dict) -> float:
        """Étape 6 — Free Cash Flow (génération de trésorerie)
        Rendement FCF > 5 % = excellent.
        """
        fcf  = _safe(info.get("freeCashflow"))
        mcap = _safe(info.get("marketCap"), default=1.0)
        if mcap <= 0:
            return 0.0
        fcf_yield = fcf / mcap
        # 5 % = score plein positif, 0 % = neutre, négatif = négatif
        return _clamp(fcf_yield / 0.05)

    def _s07_wacc_damodaran(self, info: dict) -> float:
        """Étape 7 — WACC / Damodaran (ROIC > WACC = création de valeur)"""
        beta      = _safe(info.get("beta"), default=1.0)
        de        = _safe(info.get("debtToEquity"), default=0.0)
        op_margin = _safe(info.get("operatingMargins"))
        rfr       = self._fred.fed_rate() / 100   # taux sans risque actuel

        cost_of_equity = rfr + beta * _ERP
        debt_ratio     = de / (de + 100) if de > 0 else 0.0
        equity_ratio   = 1.0 - debt_ratio
        wacc           = equity_ratio * cost_of_equity + debt_ratio * 0.04 * 0.79

        # ROIC approx = op_margin * (1 - tax) / (1 + de/100)
        roic = op_margin * 0.79 / max(1.0, 1.0 + de / 100) if op_margin else 0.0
        spread = roic - wacc   # positif = création de valeur
        return _clamp(spread / 0.05)   # ±5 % = saturation

    def _s08_dcf(self, info: dict) -> float:
        """Étape 8 — DCF simplifié (Damodaran / Gordon Growth)
        Valeur intrinsèque FCF vs capitalisation boursière.
        """
        fcf    = _safe(info.get("freeCashflow"))
        mcap   = _safe(info.get("marketCap"), default=1.0)
        growth = min(_safe(info.get("revenueGrowth"), default=0.03), 0.15)
        rfr    = self._fred.fed_rate() / 100
        beta   = _safe(info.get("beta"), default=1.0)

        wacc = rfr + beta * _ERP
        if wacc <= growth or fcf <= 0 or mcap <= 0:
            return 0.0

        # Modèle de Gordon : V = FCF(1+g) / (r-g)
        intrinsic = fcf * (1 + growth) / (wacc - growth)
        discount  = (intrinsic - mcap) / mcap   # positif = sous-évalué
        return _clamp(discount / 0.30)          # 30 % discount = score plein

    def _s09_marge_securite(self, info: dict) -> float:
        """Étape 9 — Marge de sécurité (Graham / Klarman)
        Écart prix courant vs cible analyste.
        """
        current = _safe(info.get("currentPrice"))
        target  = _safe(info.get("targetMeanPrice"))
        if current <= 0 or target <= 0:
            return 0.0
        mos = (target - current) / current
        return _clamp(mos / 0.20)   # 20 % upside = score plein

    def _s10_multiples(self, info: dict) -> float:
        """Étape 10 — Multiples de valorisation
        P/E, EV/EBITDA, P/S agrégés vs benchmarks raisonnables.
        """
        pe      = _safe(info.get("trailingPE"))
        ev_ebit = _safe(info.get("enterpriseToEbitda"))
        ps      = _safe(info.get("priceToSalesTrailing12Months"))

        scores = []
        if pe > 0:
            scores.append(_clamp((25.0 - pe) / 25.0))
        if ev_ebit > 0:
            scores.append(_clamp((15.0 - ev_ebit) / 15.0))
        if ps > 0:
            scores.append(_clamp((5.0 - ps) / 5.0))
        return _clamp(sum(scores) / len(scores)) if scores else 0.0

    def _s11_macro_dalio(self, info: dict) -> float:
        """Étape 11 — Macro Dalio (cycle d'endettement)
        Biais FRED : -1 hawkish (fin de cycle) → +1 dovish (début de cycle).
        """
        return self._fred.macro_bias()

    def _s12_geopolitique_soros(self, info: dict) -> float:
        """Étape 12 — Géopolitique Soros (réflexivité)
        Sentiment des discours BIS comme proxy de stabilité mondiale.
        """
        return self._rss.get_bias(_GEO_RSS)

    def _s13_risque_taleb(self, info: dict) -> float:
        """Étape 13 — Risque Taleb (queue de distribution / cygne noir)
        Bêta élevé + short interest élevé + volatilité extrême → pénalité.
        Score inversé : faible risque = score positif.
        """
        beta   = _safe(info.get("beta"), default=1.0)
        short  = _safe(info.get("shortPercentOfFloat"), default=0.0)
        chg52w = abs(_safe(info.get("52WeekChange"), default=0.0))

        risk = (beta / 2.0) * 0.4 + (short / 0.10) * 0.3 + (chg52w / 0.50) * 0.3
        return _clamp(1.0 - risk)   # inversé : moins de risque = meilleur score

    def _s14_catalyseurs(self, info: dict) -> float:
        """Étape 14 — Catalyseurs court terme
        Révisions d'analystes et recommandation moyenne.
        recommendationMean : 1 = Strong Buy, 5 = Sell
        """
        rec = _safe(info.get("recommendationMean"), default=3.0)
        # 1.0 → +1.0, 3.0 → 0.0, 5.0 → -1.0
        return _clamp((3.0 - rec) / 2.0)

    def _s15_these_klarman(self, info: dict) -> float:
        """Étape 15 — Thèse Klarman (valeur tangible vs prix)
        Prix/Book < 1 = opportunité claire de valeur.
        """
        pb = _safe(info.get("priceToBook"), default=1.0)
        if pb <= 0:
            return 0.0
        # P/B = 0.5 → +1.0, P/B = 1.0 → 0.0, P/B = 3.0 → -1.0
        return _clamp((1.0 - pb) / 2.0)

    def _s16_plan_sortie_marks(self, info: dict) -> float:
        """Étape 16 — Plan de sortie Marks (Howard Marks)
        Upside vers cible analyste comme proxy d'un exit clair et rentable.
        """
        current = _safe(info.get("currentPrice"))
        high52w = _safe(info.get("fiftyTwoWeekHigh"))
        target  = _safe(info.get("targetMeanPrice"))

        if current <= 0:
            return 0.0
        # Distance au plus haut 52 semaines (positif = loin du sommet)
        s_high = _clamp((high52w - current) / high52w) if high52w > 0 else 0.0
        # Upside vers cible
        s_tgt  = _clamp((target - current) / current / 0.15) if target > 0 else 0.0
        return _clamp((s_high + s_tgt) / 2)

    # ------------------------------------------------------------------
    # Étape 17 — RSI(14) + MACD(12,26,9) : signal d'entrée technique
    # ------------------------------------------------------------------

    def _compute_rsi_macd(self, symbol: str) -> dict:
        """Calcule RSI(14) et MACD(12,26,9) depuis l'historique yfinance (3 mois)."""
        try:
            hist = yf.Ticker(symbol).history(period="3mo")["Close"].dropna()
            if len(hist) < 30:
                return {}

            # RSI(14) — méthode Wilder (EWM com=13)
            delta    = hist.diff()
            gain     = delta.clip(lower=0)
            loss     = -delta.clip(upper=0)
            avg_gain = gain.ewm(com=13, adjust=False).mean()
            avg_loss = loss.ewm(com=13, adjust=False).mean()
            rs       = avg_gain / (avg_loss + 1e-10)
            rsi      = 100 - (100 / (1 + rs))
            rsi_val  = float(rsi.iloc[-1])

            # MACD(12,26,9)
            ema12     = hist.ewm(span=12, adjust=False).mean()
            ema26     = hist.ewm(span=26, adjust=False).mean()
            macd_line = ema12 - ema26
            sig_line  = macd_line.ewm(span=9, adjust=False).mean()
            histogram = macd_line - sig_line
            hist_val  = float(histogram.iloc[-1])
            macd_val  = float(macd_line.iloc[-1])

            rsi_oversold = rsi_val < 40
            macd_neg     = hist_val < 0

            if rsi_oversold and macd_neg:
                signal = "ENTREE_OPTIMALE"
            elif rsi_val > 70:
                signal = "SURACHAT"
            elif rsi_oversold or macd_neg:
                signal = "PARTIEL"
            else:
                signal = "NORMAL"

            return {
                "rsi":            round(rsi_val,  2),
                "macd_line":      round(macd_val, 4),
                "macd_histogram": round(hist_val, 4),
                "signal":         signal,
            }
        except Exception as e:
            logger.debug(f"RSI/MACD [{symbol}]: {e}")
            return {}

    # ------------------------------------------------------------------
    # Étape 18 — Agrégation : score final sur 10
    # ------------------------------------------------------------------

    def _s18_score_final(self, stage_scores: list[float]) -> float:
        """Étape 18 — Score final sur 10 (17 étapes : 16 fondamentaux/macro + 1 RSI/MACD).
        Pondérations :
          Fondamentaux 1–10 : poids 0.55  (55 %)
          Macro/Risque 11–16 : poids 0.35  (35 %)
          Technique RSI/MACD 17 : poids 0.10  (10 %)
        """
        fundamental = stage_scores[:10]    # étapes 1–10
        macro_risk  = stage_scores[10:16]  # étapes 11–16
        technique   = stage_scores[16:17]  # étape 17 RSI+MACD

        avg_fund = sum(fundamental) / len(fundamental) if fundamental else 0.0
        avg_mac  = sum(macro_risk)  / len(macro_risk)  if macro_risk  else 0.0
        avg_tech = sum(technique)   / len(technique)   if technique   else 0.0

        composite = avg_fund * 0.55 + avg_mac * 0.35 + avg_tech * 0.10
        return round((composite + 1.0) * 5.0, 2)       # mapping [-1,+1] → [0,10]

    # ------------------------------------------------------------------
    # Point d'entrée public
    # ------------------------------------------------------------------

    def analyze(self, symbol: str, prices: dict | None = None) -> dict:
        """
        Analyse complète du ticker en 17 étapes (16 fondamentaux/macro + 1 RSI/MACD).

        Retourne :
            score      — float 0–10
            signal     — "buy" | "hold" | "sell"
            stages     — liste de 18 dicts {name, score}
            rsi_macd   — {rsi, macd_line, macd_histogram, signal}
        """
        if prices is None:
            prices = {}

        info = self._info(symbol)

        # Calcul RSI/MACD en amont (évite double fetch yfinance)
        rsi_macd = self._compute_rsi_macd(symbol)

        def _rsi_macd_stage(info, _d=rsi_macd):
            """Étape 17 — Signal optimal si RSI < 40 ET histogramme MACD < 0."""
            if not _d:
                return 0.0
            rsi_oversold = _d.get("rsi", 50) < 40
            macd_neg     = _d.get("macd_histogram", 0) < 0
            if rsi_oversold and macd_neg:
                return 1.0
            if _d.get("rsi", 50) > 70:
                return -0.5
            if rsi_oversold or macd_neg:
                return 0.3
            return 0.0

        stage_fns = [
            ("Cercle de compétence",  self._s01_cercle_competence),
            ("Moat économique",       self._s02_moat),
            ("Qualité management",    self._s03_management),
            ("Bilan Graham",          self._s04_bilan_graham),
            ("Croissance Lynch",      self._s05_croissance_lynch),
            ("Free Cash Flow",        self._s06_fcf),
            ("WACC Damodaran",        self._s07_wacc_damodaran),
            ("DCF simplifié",         self._s08_dcf),
            ("Marge de sécurité",     self._s09_marge_securite),
            ("Multiples valorisation",self._s10_multiples),
            ("Macro Dalio",           self._s11_macro_dalio),
            ("Géopolitique Soros",    self._s12_geopolitique_soros),
            ("Risque Taleb",          self._s13_risque_taleb),
            ("Catalyseurs",           self._s14_catalyseurs),
            ("Thèse Klarman",         self._s15_these_klarman),
            ("Plan sortie Marks",     self._s16_plan_sortie_marks),
            ("RSI + MACD",            _rsi_macd_stage),
        ]

        raw_scores: list[float] = []
        stages_out: list[dict]  = []

        for name, fn in stage_fns:
            try:
                s = float(fn(info))
            except Exception as e:
                logger.debug(f"Pipeline [{symbol}] étape {name!r}: {e}")
                s = 0.0
            raw_scores.append(s)
            stages_out.append({"name": name, "score": round(s, 3)})

        final = self._s18_score_final(raw_scores)
        stages_out.append({"name": "Score final", "score": final})

        signal = "buy" if final >= 7.0 else ("sell" if final < 4.0 else "hold")

        logger.info(f"Pipeline [{symbol}] → {final:.1f}/10 ({signal})")
        return {
            "symbol":   symbol,
            "score":    final,
            "signal":   signal,
            "stages":   stages_out,
            "rsi_macd": rsi_macd,
        }


_instance: InvestmentPipeline | None = None
_lock = threading.Lock()


def get_pipeline() -> InvestmentPipeline:
    global _instance
    if _instance is None:
        with _lock:
            if _instance is None:
                _instance = InvestmentPipeline()
    return _instance
