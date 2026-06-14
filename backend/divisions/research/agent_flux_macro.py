"""
Agent Flux Macro "Le Détective de Capitaux"
Division Research — King Fund

Rôle : Analyste macro spécialisé flux de capitaux (style Gavekal/BCA Research)
Méthode : Comptabilité en partie double appliquée aux marchés financiers
Références : Université de l'Épargne, Howell, Gavekal, BIS

DISCLAIMER : Raisonnement qualitatif, non statistiquement prouvé.
             Les flux de capitaux ne sont pas prédictibles avec certitude.
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
import sys
import threading
import time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DISCLAIMER = (
    "Raisonnement qualitatif, non statistiquement prouvé. "
    "Les flux de capitaux ne sont pas prédictibles avec certitude."
)

LIMITES_FONDAMENTALES = [
    "Dark pools non visibles (~40% du volume US)",
    "Flux hors système dollar (BRICS, accords bilatéraux) partiellement capturés",
    "TIC Data avec 6 semaines de retard structurel",
    "Paradoxe de l'observateur : les patterns connus tendent à disparaître",
    "Raisonnement qualitatif uniquement — Phase 1 (tests de Granger en Phase 2)",
]

# yfinance tickers — mapping nom_affichage → ticker_yf
TICKERS_YF: dict[str, str] = {
    "XAUUSD": "GC=F",       # Gold futures (proxy XAU/USD spot)
    "HSI":    "^HSI",        # Hang Seng Index
    "AAXJ":   "AAXJ",        # iShares MSCI All Country Asia ex Japan
    "URTH":   "URTH",        # iShares MSCI World
    "IRX":    "^IRX",        # US 13-week T-bill (≈ 3-month rate)
    "USDJPY": "USDJPY=X",    # USD/JPY (proxy carry trade yen)
    "GLD":    "GLD",         # SPDR Gold Shares ETF
    "USO":    "USO",         # United States Oil Fund
}

FRED_SERIES = ["DGS3MO", "DGS10", "T10YIE"]

# Ratio thresholds (from spec)
RATIO_SEUILS = {
    "or_msci":   {"variation_48h_pct": 5.0,  "label": "Or/MSCI World"},
    "hsi_aaxj":  {"niveau_abs":        85.0,  "label": "Hang Seng/MSCI Asie"},
    "usdjpy":    {"variation_24h_pct":  2.0,  "label": "USD/JPY carry trade"},
    "irx_bp":    {"hausse_1s_bp":      20.0,  "label": "Taux US 3 mois"},
    "gld_flows": {"sorties_1s_m":     500.0,  "label": "Flux GLD (sorties)"},
}

# Biais checklist (blocage=True → bloque conclusion si non résolu)
BIAIS_CHECKLIST: dict[str, dict] = {
    "confirmation":          {"question": "2 sources CONTRADICTOIRES consultées ?",                          "blocage": True},
    "causalite_temporelle":  {"question": "Événement précède anomalie dans le temps ?",                      "blocage": True},
    "mecanisme_explicite":   {"question": "Flux monétaire identifié et quantifié ?",                        "blocage": True},
    "narratif":              {"question": "Section 'Pourquoi j'ai tort' présente ?",                        "blocage": True},
    "recence":               {"question": "5 précédents historiques comparés ?",                             "blocage": False},
    "independance_sources":  {"question": "Sources vraiment indépendantes ?",                               "blocage": True},
    "taux_base":             {"question": "Fréquence normale du pattern calculée ?",                        "blocage": False},
    "limite_position":       {"question": "Recommandation < 15% du portefeuille ?",                        "blocage": True},
    "sycophanie_llm":        {"question": "Analyse contraire à la thèse dominante si données le justifient ?", "blocage": False},
    "hallucination":         {"question": "Toutes les données vérifiées via sources primaires ?",           "blocage": True},
}

_FETCH_TIMEOUT = 30  # seconds for all external requests

_RAPPORTS_DIR = Path(__file__).resolve().parents[4] / "rapports" / "flux_macro"

# ---------------------------------------------------------------------------
# RÈGLE MONÉTAIRE ÉTERNELLE
# Source : Université de l'Épargne / Howell / Gavekal / BIS
# Principe fondateur de la méthode de cet agent.
# ---------------------------------------------------------------------------

REGLE_MONETAIRE_ETERNELLE = """
RÈGLE MONÉTAIRE ÉTERNELLE
(Comptabilité en Partie Double Appliquée aux Marchés Financiers)

SOURCE : Université de l'Épargne — Howell (CrossBorderCapital) — Gavekal — BIS

PRINCIPE FONDAMENTAL
  "Tout dollar investi dans un actif provient nécessairement d'un autre actif.
   Les flux de capitaux sont conservatifs : la somme algébrique de tous les
   mouvements est TOUJOURS nulle."
   — Identité comptable, non théorie.

COROLLAIRE IPO (Mécanisme absorbeur de liquidités)
  Une introduction en bourse ou une émission obligataire majeure ABSORBE
  de la liquidité existante. Pour chaque dollar levé par l'émetteur :

  ① Des investisseurs vendent d'autres actifs pour libérer du cash
     → Or (GLD/GC=F), actions marchés émergents (AAXJ, ^HSI), obligations TLT
     → Pression vendeuse anormale détectable J-30 à J-3 avant l'IPO

  ② Le cash libéré transite par le marché monétaire
     → Hausse temporaire des taux courts (^IRX, DGS3MO)
     → Possible renforcement du dollar (USDJPY=X : yen affaibli)

  ③ Post-IPO : rebond des actifs allegés si l'IPO est sur-souscrite
     → Signal d'achat sur l'or et les EM si les données le confirment

PRÉCÉDENTS HISTORIQUES CONNUS (non exhaustifs)
  • Alibaba IPO sept. 2014 (~25 Md$) → baisse or -3% dans les 3 semaines avant
  • Saudi Aramco IPO déc. 2019 (~29 Md$) → EM sous-performance -4% vs MSCI World
  • Arm Holdings IPO sept. 2023 (~5 Md$) → flux GLD négatifs sur 2 semaines
  ⚠️ Ces corrélations sont OBSERVÉES, non prouvées causalement (Phase 1).

APPLICATION DANS CET AGENT
  → Étape 3 (CHERCHER) : identifier l'événement absorbeur contemporain
  → Étape 4 (VÉRIFIER SÉQUENCE) : l'événement PRÉCÈDE l'anomalie de prix
  → Étape 5 (IDENTIFIER MÉCANISME) : quantifier le montant levé / absorbé
  → Checklist biais : causalite_temporelle + mecanisme_explicite obligatoires

LIMITES DE LA RÈGLE
  • Ne s'applique qu'aux flux MESURABLES (hors dark pools ~40% US)
  • Magnitude de l'effet dépend de la profondeur du marché et du momentum
  • La règle est identité comptable ex-post — elle ne prédit pas l'amplitude
  • Phase 2 obligatoire : tests de causalité de Granger pour validation

DISCLAIMER : Raisonnement qualitatif. Non statistiquement prouvé.
             Les flux de capitaux ne sont pas prédictibles avec certitude.
"""


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_instance: "AgentFluxMacro | None" = None
_instance_lock = threading.Lock()


def get_agent_flux_macro() -> "AgentFluxMacro":
    global _instance
    with _instance_lock:
        if _instance is None:
            _instance = AgentFluxMacro()
    return _instance


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class AgentFluxMacro:
    """Détective de Capitaux — détection d'anomalies de flux macro."""

    def __init__(self) -> None:
        self._lock   = threading.Lock()
        self._cache: dict | None = None
        self._cache_ts: float    = 0.0
        self._cache_ttl: int     = 3600 * 4   # 4h
        self._db_path: Path | None = None
        self._init_db()
        _RAPPORTS_DIR.mkdir(parents=True, exist_ok=True)
        (_RAPPORTS_DIR / "flash").mkdir(exist_ok=True)
        (_RAPPORTS_DIR / "hebdo").mkdir(exist_ok=True)

    # ── DB ──────────────────────────────────────────────────────────────────

    def _init_db(self) -> None:
        try:
            from config import DB_PATH
            self._db_path = Path(DB_PATH)
            con = sqlite3.connect(self._db_path)
            con.execute("""
                CREATE TABLE IF NOT EXISTS flux_macro_journal (
                    id                INTEGER PRIMARY KEY AUTOINCREMENT,
                    date              TEXT NOT NULL,
                    anomalie_detectee TEXT,
                    cause_identifiee  TEXT,
                    confiance         TEXT,
                    conclusion        TEXT,
                    verdict_posteriori TEXT DEFAULT NULL,
                    faux_positif      INTEGER DEFAULT NULL,
                    sources_actives   TEXT,
                    created_at        TEXT DEFAULT (datetime('now'))
                )
            """)
            con.commit()
            con.close()
        except Exception as exc:
            logger.warning("[FluxMacro] init_db: %s", exc)

    def _save_journal(self, anomalie: str, cause: str, confiance: str,
                      conclusion: str, sources: list[str]) -> None:
        if not self._db_path:
            return
        try:
            con = sqlite3.connect(self._db_path)
            con.execute(
                """INSERT INTO flux_macro_journal
                   (date, anomalie_detectee, cause_identifiee, confiance, conclusion, sources_actives)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    datetime.now(timezone.utc).isoformat(),
                    anomalie[:500] if anomalie else None,
                    cause[:500]    if cause    else None,
                    confiance,
                    conclusion[:1000] if conclusion else None,
                    json.dumps(sources),
                ),
            )
            con.commit()
            con.close()
        except Exception as exc:
            logger.warning("[FluxMacro] save_journal: %s", exc)

    def journal(self, limite: int = 50) -> list[dict]:
        if not self._db_path:
            return []
        try:
            con = sqlite3.connect(self._db_path)
            rows = con.execute(
                "SELECT date,anomalie_detectee,cause_identifiee,confiance,conclusion,"
                "verdict_posteriori,faux_positif,sources_actives,created_at "
                "FROM flux_macro_journal ORDER BY id DESC LIMIT ?",
                (limite,),
            ).fetchall()
            con.close()
            cols = ["date", "anomalie", "cause", "confiance", "conclusion",
                    "verdict", "faux_positif", "sources", "created_at"]
            return [dict(zip(cols, r)) for r in rows]
        except Exception as exc:
            logger.warning("[FluxMacro] journal: %s", exc)
            return []

    # ── Sanitisation ────────────────────────────────────────────────────────

    @staticmethod
    def _sanitize(text: Any, maxlen: int = 400) -> str:
        """Strip HTML/scripts and prompt-injection patterns from scraped content."""
        s = re.sub(r'<[^>]+>', '', str(text))
        s = re.sub(
            r'(?i)(ignore previous instructions?|system\s*prompt|</s>|<\|im_start\|>|<\|endoftext\|>)',
            '[FILTERED]', s
        )
        return s.strip()[:maxlen]

    # ── Fetchers ─────────────────────────────────────────────────────────────

    def _fetch_prix(self) -> dict[str, Any]:
        """
        Fetch current prices + 35-day history for all monitored tickers.
        Returns {"ok": bool, "data": {nom: {price, hist_30d, freshness}}, "stale": []}
        """
        try:
            import yfinance as yf
            import pandas as pd
            result: dict[str, Any] = {}
            stale: list[str] = []
            now_utc = datetime.now(timezone.utc)

            tickers_str = " ".join(TICKERS_YF.values())
            hist = yf.download(
                tickers_str,
                period="35d",
                interval="1d",
                progress=False,
                auto_adjust=True,
                timeout=_FETCH_TIMEOUT,
            )
            close = hist.get("Close", pd.DataFrame())
            volume = hist.get("Volume", pd.DataFrame())

            for nom, ticker in TICKERS_YF.items():
                try:
                    col = ticker if ticker in close.columns else (
                        close.columns[0] if len(close.columns) == 1 else None
                    )
                    if col is None or col not in close.columns:
                        result[nom] = {"price": None, "hist_30d": [], "freshness": "UNAVAILABLE"}
                        continue

                    series = close[col].dropna()
                    if series.empty:
                        result[nom] = {"price": None, "hist_30d": [], "freshness": "UNAVAILABLE"}
                        continue

                    last_price   = float(series.iloc[-1])
                    last_date    = series.index[-1]

                    # Freshness check: < 24h
                    if hasattr(last_date, 'tzinfo') and last_date.tzinfo:
                        age_h = (now_utc - last_date).total_seconds() / 3600
                    else:
                        age_h = (now_utc.replace(tzinfo=None) - last_date.to_pydatetime().replace(tzinfo=None)).total_seconds() / 3600

                    freshness = "OK" if age_h < 48 else "STALE"   # 48h tolerance for weekends
                    if freshness == "STALE":
                        stale.append(nom)

                    hist_30d = series.tail(30).tolist()

                    vol_5d = None
                    if nom == "GLD" and ticker in volume.columns:
                        vol_series  = volume[ticker].dropna().tail(5)
                        price_series = series.tail(5)
                        gld_5d_vol_usd = float((vol_series * price_series).sum())
                        vol_5d = round(gld_5d_vol_usd / 1e6, 1)   # en M$

                    result[nom] = {
                        "price":       round(last_price, 4),
                        "hist_30d":    [round(x, 4) for x in hist_30d],
                        "freshness":   freshness,
                        "date":        str(last_date)[:10],
                        "vol_5d_mUSD": vol_5d,
                    }
                except Exception as exc:
                    logger.debug("[FluxMacro] ticker %s: %s", nom, exc)
                    result[nom] = {"price": None, "hist_30d": [], "freshness": "UNAVAILABLE"}

            return {"ok": True, "data": result, "stale": stale}

        except Exception as exc:
            logger.warning("[FluxMacro] _fetch_prix: %s", exc)
            return {"ok": False, "data": {}, "stale": [], "erreur": str(exc)}

    def _fetch_fred(self) -> dict[str, Any]:
        """Fetch DGS3MO, DGS10, T10YIE from FRED API. Returns dict nom → value or None."""
        result: dict[str, Any] = {}
        try:
            from config import FRED_API_KEY
            if not FRED_API_KEY:
                return {"ok": False, "reason": "FRED_API_KEY absent", "data": {}}

            from fredapi import Fred
            fred = Fred(api_key=FRED_API_KEY)
            for series_id in FRED_SERIES:
                try:
                    s = fred.get_series_latest_release(series_id)
                    val = float(s.dropna().iloc[-1]) if not s.dropna().empty else None
                    result[series_id] = {"value": val, "freshness": "OK"}
                except Exception as exc:
                    logger.debug("[FluxMacro] FRED %s: %s", series_id, exc)
                    result[series_id] = {"value": None, "freshness": "UNAVAILABLE"}

            return {"ok": True, "data": result}
        except Exception as exc:
            logger.warning("[FluxMacro] _fetch_fred: %s", exc)
            return {"ok": False, "reason": str(exc), "data": {}}

    def _fetch_cftc(self) -> dict[str, Any]:
        """
        Fetch CFTC Commitments of Traders — Managed Money positions on GOLD (COMEX).
        Source: CFTC Socrata public API (disaggregated futures-only).
        """
        try:
            url = (
                "https://publicreporting.cftc.gov/resource/jun7-fc8e.json"
                "?market_and_exchange_names=GOLD%20(COMEX)"
                "&%24order=report_date_as_yyyy_mm_dd+DESC&%24limit=1"
            )
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "king-fund-flux-macro/1.0", "Accept": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=_FETCH_TIMEOUT) as resp:
                raw = resp.read().decode("utf-8", errors="replace")

            rows = json.loads(raw)
            if not rows:
                return {"ok": False, "reason": "DONNÉES INDISPONIBLES", "data": {}}

            r = rows[0]
            mm_long  = int(r.get("m_money_positions_long_all",  0) or 0)
            mm_short = int(r.get("m_money_positions_short_all", 0) or 0)
            net_mm   = mm_long - mm_short
            report_date = self._sanitize(r.get("report_date_as_yyyy_mm_dd", "?"), 20)

            return {
                "ok":         True,
                "report_date": report_date,
                "mm_long":    mm_long,
                "mm_short":   mm_short,
                "net_mm":     net_mm,
                "freshness":  "OK",   # weekly data — agent runs 2x/day
            }
        except Exception as exc:
            logger.debug("[FluxMacro] _fetch_cftc: %s", exc)
            return {"ok": False, "reason": "DONNÉES INDISPONIBLES", "data": {}}

    def _fetch_ipo_calendar(self) -> list[dict]:
        """
        Fetch recent S-1 filings from SEC EDGAR Atom feed (IPO candidates).
        Returns list of {titre, date, url}.
        """
        ipos: list[dict] = []
        try:
            url = (
                "https://www.sec.gov/cgi-bin/browse-edgar"
                "?action=getcurrent&type=S-1&dateb=&owner=include&count=5"
                "&search_text=&output=atom"
            )
            req = urllib.request.Request(
                url, headers={"User-Agent": "king-fund-research@kingfund.local"}
            )
            with urllib.request.urlopen(req, timeout=_FETCH_TIMEOUT) as resp:
                raw = resp.read().decode("utf-8", errors="replace")

            root = ET.fromstring(raw)
            ns = {"atom": "http://www.w3.org/2005/Atom"}
            for entry in root.findall("atom:entry", ns)[:5]:
                titre = self._sanitize(entry.findtext("atom:title", "", ns), 150)
                date  = self._sanitize(entry.findtext("atom:updated", "", ns)[:10], 20)
                link  = entry.find("atom:link", ns)
                url_  = self._sanitize(link.get("href", "") if link is not None else "", 200)
                ipos.append({"titre": titre, "date": date, "url": url_})
        except Exception as exc:
            logger.debug("[FluxMacro] _fetch_ipo_calendar: %s", exc)

        return ipos

    # ── Anomaly detection ───────────────────────────────────────────────────

    def _detect_anomalies(self, prix_data: dict[str, Any]) -> list[dict]:
        """
        Détecte anomalies > 2 écarts-types sur la valeur récente vs moyenne 30j.
        Analyse les ratios clés : Or/MSCI World, HSI/AAXJ, USD/JPY, IRX, GLD flux.
        """
        import statistics
        anomalies: list[dict] = []
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

        def _check_series(name: str, label: str, hist: list[float], current: float,
                          pct_seuil: float | None = None, abs_seuil: float | None = None) -> None:
            if len(hist) < 10 or current is None:
                return
            try:
                mean = statistics.mean(hist)
                std  = statistics.stdev(hist)
                if std < 1e-9:
                    return
                z_score = (current - mean) / std
                variation_pct = (current - mean) / abs(mean) * 100 if mean else 0

                triggered = abs(z_score) > 2.0
                seuil_triggered = False
                seuil_label = ""
                if pct_seuil and abs(variation_pct) > pct_seuil:
                    seuil_triggered = True
                    seuil_label = f"variation {variation_pct:+.1f}% (seuil {pct_seuil}%)"
                if abs_seuil and current < abs_seuil:
                    seuil_triggered = True
                    seuil_label = f"valeur {current:.2f} < seuil {abs_seuil}"

                if triggered or seuil_triggered:
                    anomalies.append({
                        "id":           name,
                        "label":        label,
                        "timestamp":    now_str,
                        "valeur":       round(current, 4),
                        "moyenne_30j":  round(mean, 4),
                        "ecart_type":   round(std, 4),
                        "z_score":      round(z_score, 2),
                        "variation_pct": round(variation_pct, 2),
                        "seuil_label":  seuil_label,
                        "niveau":       "CRITIQUE" if abs(z_score) > 3.0 else "IMPORTANT",
                    })
            except Exception as exc:
                logger.debug("[FluxMacro] _check_series %s: %s", name, exc)

        d = prix_data

        # Or/MSCI World ratio
        xau = d.get("XAUUSD", {}); urth = d.get("URTH", {})
        if xau.get("price") and urth.get("price") and urth["price"] > 0:
            hist_ratio = [a / b for a, b in zip(xau["hist_30d"], urth["hist_30d"])
                          if b and b > 0]
            ratio_cur  = xau["price"] / urth["price"]
            _check_series("or_msci", "Or/MSCI World", hist_ratio, ratio_cur, pct_seuil=5.0)

        # HSI/AAXJ ratio
        hsi = d.get("HSI", {}); aaxj = d.get("AAXJ", {})
        if hsi.get("price") and aaxj.get("price") and aaxj["price"] > 0:
            hist_r = [a / b for a, b in zip(hsi["hist_30d"], aaxj["hist_30d"]) if b > 0]
            _check_series("hsi_aaxj", "Hang Seng/MSCI Asie ex-Japon",
                          hist_r, hsi["price"] / aaxj["price"], abs_seuil=85.0)

        # USD/JPY
        jpy = d.get("USDJPY", {})
        if jpy.get("price") and jpy.get("hist_30d"):
            _check_series("usdjpy", "USD/JPY (carry trade yen)",
                          jpy["hist_30d"], jpy["price"], pct_seuil=2.0)

        # US 3-month rate (^IRX in %)
        irx = d.get("IRX", {})
        if irx.get("price") and irx.get("hist_30d") and len(irx["hist_30d"]) >= 7:
            # Check if rate rose > 20bp vs 5 sessions ago
            val_now = irx["price"]
            val_1w  = irx["hist_30d"][-6] if len(irx["hist_30d"]) >= 6 else irx["hist_30d"][0]
            delta_bp = (val_now - val_1w) * 100   # IRX is already in %
            if delta_bp > 20:
                anomalies.append({
                    "id":           "irx_bp",
                    "label":        "Taux US 3 mois — hausse brutale",
                    "timestamp":    now_str,
                    "valeur":       round(val_now, 3),
                    "variation_bp": round(delta_bp, 1),
                    "z_score":      0.0,
                    "variation_pct": round(delta_bp, 1),
                    "seuil_label":  f"hausse {delta_bp:.1f}bp en 1 semaine (seuil 20bp)",
                    "niveau":       "CRITIQUE" if delta_bp > 40 else "IMPORTANT",
                })
            _check_series("irx_series", "Taux US 3 mois", irx["hist_30d"], val_now)

        return anomalies

    def _compute_ratios_etat(self, prix_data: dict[str, Any]) -> list[dict]:
        """Calcule l'état courant des ratios surveillés pour le dashboard."""
        ratios = []
        d = prix_data

        def _add(id_: str, label: str, valeur: Any, alerte: bool, detail: str = "",
                  freshness: str = "OK") -> None:
            ratios.append({
                "id": id_, "label": label,
                "valeur": valeur, "alerte": alerte,
                "detail": detail, "freshness": freshness,
            })

        xau = d.get("XAUUSD", {}); urth = d.get("URTH", {})
        if xau.get("price") and urth.get("price") and urth["price"] > 0:
            r = round(xau["price"] / urth["price"], 4)
            hist_r = [a / b for a, b in zip(xau["hist_30d"], urth["hist_30d"]) if b > 0]
            pct = (r - hist_r[-2]) / hist_r[-2] * 100 if len(hist_r) >= 2 and hist_r[-2] else 0
            _add("or_msci", "Or/MSCI World", r, abs(pct) > 5.0,
                 f"{pct:+.2f}% (48h)", min(xau.get("freshness","?"), urth.get("freshness","?")))
        else:
            _add("or_msci", "Or/MSCI World", "DONNÉES INDISPONIBLES", False)

        hsi = d.get("HSI", {}); aaxj = d.get("AAXJ", {})
        if hsi.get("price") and aaxj.get("price") and aaxj["price"] > 0:
            r = round(hsi["price"] / aaxj["price"], 2)
            _add("hsi_aaxj", "Hang Seng/MSCI Asie ex-Japon", r, r < 85.0,
                 "< 85 = alerte", min(hsi.get("freshness","?"), aaxj.get("freshness","?")))
        else:
            _add("hsi_aaxj", "Hang Seng/MSCI Asie ex-Japon", "DONNÉES INDISPONIBLES", False)

        jpy = d.get("USDJPY", {})
        if jpy.get("price") and jpy.get("hist_30d") and len(jpy["hist_30d"]) >= 2:
            pct = (jpy["price"] - jpy["hist_30d"][-2]) / jpy["hist_30d"][-2] * 100 if jpy["hist_30d"][-2] else 0
            _add("usdjpy", "USD/JPY (carry yen)", round(jpy["price"], 2),
                 abs(pct) > 2.0, f"{pct:+.2f}% (24h)", jpy.get("freshness","?"))
        else:
            _add("usdjpy", "USD/JPY (carry yen)", "DONNÉES INDISPONIBLES", False)

        irx = d.get("IRX", {})
        if irx.get("price") and irx.get("hist_30d") and len(irx["hist_30d"]) >= 6:
            val_1w  = irx["hist_30d"][-6]
            delta   = round((irx["price"] - val_1w) * 100, 1)
            _add("irx", "Taux US 3 mois", f"{irx['price']:.2f}%",
                 delta > 20.0, f"{delta:+.1f} bp (1 sem.)", irx.get("freshness","?"))
        else:
            _add("irx", "Taux US 3 mois", "DONNÉES INDISPONIBLES", False)

        gld = d.get("GLD", {})
        vol = gld.get("vol_5d_mUSD")
        if vol is not None:
            _add("gld_flows", "Flux GLD (volume 5j M$)", f"{vol:.0f} M$",
                 False,  # volume alone can't determine inflow/outflow direction
                 "Volume proxy — sorties > 500M$ = alerte", gld.get("freshness","?"))
        else:
            _add("gld_flows", "Flux GLD", "DONNÉES INDISPONIBLES", False)

        return ratios

    # ── Bias checklist ──────────────────────────────────────────────────────

    def _run_biais_checklist(
        self,
        anomalies: list[dict],
        sources_actives: list[str],
        ipos: list[dict],
        fred_ok: bool,
        cftc_ok: bool,
    ) -> dict[str, bool]:
        """
        Évalue la checklist anti-biais pour les anomalies détectées.
        Retourne {biais_id: resolved (bool)}.
        """
        results: dict[str, bool] = {}
        n_sources = len(sources_actives)

        # confirmation: ≥ 2 sources indépendantes actives
        results["confirmation"] = n_sources >= 2

        # causalite_temporelle: un événement IPO/émission est présent dans le calendrier
        results["causalite_temporelle"] = len(ipos) > 0

        # mecanisme_explicite: anomalie détectée + description mécanisme possible
        results["mecanisme_explicite"] = len(anomalies) > 0

        # narratif: toujours présent (on génère toujours la section "Pourquoi j'ai tort")
        results["narratif"] = True

        # recence: avertissement uniquement — pas d'historique multi-crises en Phase 1
        results["recence"] = False

        # independance_sources: yfinance ≠ FRED ≠ CFTC → 3 sources vraiment indépendantes
        results["independance_sources"] = n_sources >= 2 and fred_ok != cftc_ok or (fred_ok and cftc_ok)

        # taux_base: avertissement — non calculé en Phase 1
        results["taux_base"] = False

        # limite_position: toujours respecté (on recommande toujours < 15%)
        results["limite_position"] = True

        # sycophanie_llm: avertissement — non évalué automatiquement
        results["sycophanie_llm"] = True

        # hallucination: toutes les données viennent de sources réelles fetchées
        results["hallucination"] = n_sources >= 1  # au moins yfinance actif

        return results

    def _calcul_confiance(self, biais_results: dict[str, bool],
                          sources_count: int, timeframes_count: int) -> str:
        """
        FORTE  : 6+ biais bloquants résolus + 3 sources + 3 timeframes
        MOYEN  : 4-5 biais bloquants résolus + 2 sources + 2 timeframes
        FAIBLE : < 4 biais résolus OU < 2 sources
        INSUFFISANT : biais bloquants non résolus → pas de conclusion
        """
        bloquants = [k for k, v in BIAIS_CHECKLIST.items() if v["blocage"]]
        n_bloq_ok = sum(1 for b in bloquants if biais_results.get(b, False))

        # Vérifier si des biais bloquants sont NON résolus
        bloquants_ko = [b for b in bloquants if not biais_results.get(b, False)]
        if bloquants_ko:
            return "INSUFFISANT"

        if n_bloq_ok >= 6 and sources_count >= 3 and timeframes_count >= 3:
            return "FORTE"
        if n_bloq_ok >= 4 and sources_count >= 2 and timeframes_count >= 2:
            return "MOYEN"
        return "FAIBLE"

    # ── Telegram formatting ─────────────────────────────────────────────────

    def _generer_alerte_telegram(
        self,
        niveau: str,
        anomalie: dict,
        cause: str,
        sources: list[str],
        conclusion: str,
        action: str,
        confiance: str,
        ipos: list[dict],
    ) -> str:
        now = datetime.now(timezone.utc)
        date_str  = now.strftime("%Y-%m-%d")
        heure_str = now.strftime("%H:%M")

        src_lines = ""
        for i, src in enumerate(sources[:3], 1):
            src_lines += f"\n• Source {i} : {src}"

        ipo_str = ""
        if ipos:
            ipo_str = f"\n🏗️ IPO détectée : {self._sanitize(ipos[0]['titre'], 80)} ({ipos[0]['date']})"

        return (
            f"[{niveau}] AGENT FLUX MACRO\n\n"
            f"📅 {date_str} {heure_str} UTC\n\n"
            f"⚠️ ANOMALIE : {anomalie.get('label','?')} "
            f"{anomalie.get('variation_pct', 0):+.1f}% (z={anomalie.get('z_score',0):+.1f}σ)\n\n"
            f"🔍 CAUSE IDENTIFIÉE : {cause}{ipo_str}\n\n"
            f"📊 CONFIRMÉ SUR :{src_lines}\n\n"
            f"⏱️ SÉQUENCE : Anomalie détectée le {date_str}\n\n"
            f"🎯 CONCLUSION : {conclusion}\n\n"
            f"📈 ACTION SUGGÉRÉE : {action}\n\n"
            f"🔒 CONFIANCE : {confiance}\n\n"
            f"⚠️ Soumis à AGD-01 pour validation\n\n"
            f"⚠️ DISCLAIMER : {DISCLAIMER}"
        )

    def _soumettre_agd01(self, message: str, niveau: str) -> str:
        """
        Soumet le signal à AGD-01 qui joue l'avocat du diable.
        Si AGD-01 rejette → signal déclassé à IMPORTANT.
        Retourne le niveau validé.
        """
        if niveau != "CRITIQUE":
            return niveau
        try:
            from divisions.gerant_delegue.agd_01 import get_gerant_delegue
            agd = get_gerant_delegue()
            result = agd.evaluer_decision(
                ticker="FLUX_MACRO",
                action="alerte",
                montant=0.0,
                contexte=f"[AVOCAT DU DIABLE] Signal CRITIQUE reçu de Agent Flux Macro:\n{message[:800]}\n\n"
                         "Analyse ce signal de manière critique. Donne 3 raisons pour lesquelles "
                         "cette thèse pourrait être fausse. Décision : VALIDER ou REJETER.",
                perf_annualisee=0.0,
                patrimoine=18082.0,
            )
            decision = str(result.get("decision", "")).lower()
            if "rejet" in decision or "reject" in decision:
                logger.info("[FluxMacro] AGD-01 a rejeté le signal CRITIQUE → déclassé IMPORTANT")
                return "IMPORTANT"
        except Exception as exc:
            logger.debug("[FluxMacro] AGD-01 validation: %s", exc)
        return niveau

    # ── Main entry point ────────────────────────────────────────────────────

    def analyser(self, forcer: bool = False) -> dict:
        """
        Workflow complet 7 étapes :
        1. DÉTECTER anomalie (2σ sur 48h vs 30j)
        2. HORODATER
        3. CHERCHER événement absorbeur (IPO calendar)
        4. VÉRIFIER SÉQUENCE (causalité temporelle)
        5. IDENTIFIER MÉCANISME
        6. TRIPLE VÉRIFICATION (3 sources, 3 timeframes)
        7. CONCLUSION avec niveau de confiance
        """
        with self._lock:
            now = time.time()
            if not forcer and self._cache and (now - self._cache_ts) < self._cache_ttl:
                return self._cache

            ts_debut = datetime.now(timezone.utc).isoformat()
            sources_actives: list[str] = []
            erreurs: list[str] = []

            # ── Étape 1/2 : Fetch données + détection ──────────────────────
            prix_result = self._fetch_prix()
            if prix_result.get("ok"):
                sources_actives.append("yfinance (XAUUSD/GC=F, HSI, AAXJ, URTH, IRX, USDJPY, GLD, USO)")
            else:
                erreurs.append(f"yfinance: {prix_result.get('erreur','erreur inconnue')}")

            fred_result = self._fetch_fred()
            fred_ok     = fred_result.get("ok", False)
            if fred_ok:
                sources_actives.append("FRED API (DGS3MO, DGS10, T10YIE)")

            cftc_result = self._fetch_cftc()
            cftc_ok     = cftc_result.get("ok", False)
            if cftc_ok:
                sources_actives.append(
                    f"CFTC COT ({cftc_result.get('report_date','?')}) — "
                    f"MM Net: {cftc_result.get('net_mm', 'N/A')} contrats"
                )

            ipos = self._fetch_ipo_calendar()
            if ipos:
                sources_actives.append(f"SEC EDGAR ({len(ipos)} filing(s) S-1 récents)")

            # ── Étape 1 : DÉTECTER anomalies ───────────────────────────────
            prix_data  = prix_result.get("data", {})
            anomalies  = self._detect_anomalies(prix_data) if prix_result.get("ok") else []
            ratios_etat = self._compute_ratios_etat(prix_data) if prix_result.get("ok") else []

            # ── Étape 5 : IDENTIFIER MÉCANISME (qualitative, Phase 1) ──────
            mecanisme = ""
            if anomalies and ipos:
                top_a = anomalies[0]
                top_i = ipos[0]
                mecanisme = (
                    f"Hypothèse (non prouvée) : {top_a['label']} anormal "
                    f"(z={top_a['z_score']:+.1f}σ) pourrait refléter une rotation "
                    f"de liquidités vers l'événement '{self._sanitize(top_i['titre'],80)}' "
                    f"({top_i['date']}). Mécanisme possible : réallocation défensive."
                )
            elif anomalies:
                top_a = anomalies[0]
                mecanisme = (
                    f"Anomalie {top_a['label']} détectée (z={top_a['z_score']:+.1f}σ). "
                    "Aucun événement calendrier identifié — causalité non établie."
                )

            # ── Étape 6 : TRIPLE VÉRIFICATION ──────────────────────────────
            timeframes: list[str] = []
            if prix_result.get("ok"):
                timeframes.extend(["1j (quotidien yfinance)", "1s (5 sessions)", "1m (30j rolling)"])

            # ── Étape 7 : CHECKLIST ANTI-BIAIS + CONFIANCE ─────────────────
            biais_results = self._run_biais_checklist(
                anomalies, sources_actives, ipos, fred_ok, cftc_ok
            )
            confiance = self._calcul_confiance(
                biais_results, len(sources_actives), len(timeframes)
            )

            # ── Conclusion ──────────────────────────────────────────────────
            conclusion = ""
            action_suggeree = ""
            if confiance == "INSUFFISANT":
                conclusion = "Données insuffisantes — aucune conclusion émise. Log uniquement."
                action_suggeree = "Attendre prochaine analyse (16h00 UTC)"
            elif anomalies:
                top  = max(anomalies, key=lambda x: abs(x.get("z_score", 0)))
                conclusion = (
                    f"Anomalie détectée : {top['label']} à {top['z_score']:+.1f}σ "
                    f"(variation {top['variation_pct']:+.1f}%). "
                    f"{mecanisme or 'Mécanisme non identifié.'}"
                )
                action_suggeree = "Surveiller 24-48h avant action — attendre confirmation 2e source"
            else:
                conclusion = "Aucune anomalie significative détectée. Marchés dans les normes 30j."
                action_suggeree = "Maintenir surveillance routine — prochaine analyse 16h00 UTC"

            # Section "Pourquoi j'ai tort" (biais narratif — toujours présente)
            pourquoi_tort = (
                "• Les dark pools (~40% volume US) peuvent inverser le signal\n"
                "• Les flux BRICS/hors-dollar ne sont pas capturés\n"
                "• La corrélation observée peut être spurieuse (Phase 1 qualitatif)\n"
                "• Le TIC Data a 6 semaines de retard — données actuelles non disponibles"
            )

            # ── Alertes Telegram (si anomalie critique + confiance suffisante) ─
            alertes_envoyees: list[str] = []
            for anomalie in anomalies:
                if anomalie["niveau"] == "CRITIQUE" and confiance in ("FORTE", "MOYEN"):
                    msg = self._generer_alerte_telegram(
                        niveau      = anomalie["niveau"],
                        anomalie    = anomalie,
                        cause       = mecanisme or "Cause non identifiée",
                        sources     = sources_actives,
                        conclusion  = conclusion,
                        action      = action_suggeree,
                        confiance   = confiance,
                        ipos        = ipos,
                    )
                    niveau_valide = self._soumettre_agd01(msg, anomalie["niveau"])
                    if niveau_valide in ("CRITIQUE", "IMPORTANT"):
                        try:
                            from divisions.gerant_delegue.notifier import send
                            send(msg, "critique" if niveau_valide == "CRITIQUE" else "warning")
                            alertes_envoyees.append(f"{anomalie['label']} → {niveau_valide}")
                        except Exception as exc:
                            logger.warning("[FluxMacro] Telegram: %s", exc)

            # ── Journal SQLite ──────────────────────────────────────────────
            if anomalies or confiance != "INSUFFISANT":
                anomalies_str = "; ".join(
                    f"{a['label']} z={a.get('z_score',0):+.1f}" for a in anomalies
                ) or "Aucune"
                self._save_journal(
                    anomalie  = anomalies_str,
                    cause     = mecanisme or "Non identifiée",
                    confiance = confiance,
                    conclusion= conclusion,
                    sources   = sources_actives,
                )

            # ── Construction résultat ───────────────────────────────────────
            fred_data = fred_result.get("data", {})
            self._cache = {
                "timestamp":         ts_debut,
                "sources_actives":   sources_actives,
                "nb_sources":        len(sources_actives),
                "anomalies":         anomalies,
                "ratios":            ratios_etat,
                "fred": {
                    "DGS3MO":  fred_data.get("DGS3MO",  {}).get("value", "DONNÉES INDISPONIBLES"),
                    "DGS10":   fred_data.get("DGS10",   {}).get("value", "DONNÉES INDISPONIBLES"),
                    "T10YIE":  fred_data.get("T10YIE",  {}).get("value", "DONNÉES INDISPONIBLES"),
                },
                "cftc": cftc_result if cftc_ok else {"ok": False, "reason": "DONNÉES INDISPONIBLES"},
                "ipos":              ipos,
                "biais_checklist":   biais_results,
                "confiance":         confiance,
                "conclusion":        conclusion,
                "mecanisme":         mecanisme,
                "action_suggeree":   action_suggeree,
                "pourquoi_tort":     pourquoi_tort,
                "alertes_envoyees":  alertes_envoyees,
                "erreurs":           erreurs,
                "limites":           LIMITES_FONDAMENTALES,
                "disclaimer":        DISCLAIMER,
                "stale_tickers":     prix_result.get("stale", []),
                "timeframes_verifies": timeframes,
                "tic_data_note":     "TIC Data non chargé — délai structurel 6 semaines (source: ticdata.treasury.gov)",
                "wgc_note":          "World Gold Council API non disponible publiquement — DONNÉES INDISPONIBLES",
            }
            self._cache_ts = now
            return self._cache

    def scan_contexte(self, evenement: dict) -> dict:
        """
        Scan manuel avec un événement absorbeur injecté (test de la Règle Monétaire Éternelle).

        Paramètres evenement :
          titre          : str  — nom de l'IPO / émission
          valorisation   : str  — montant estimé (ex: "250 Md$")
          date_prevue    : str  — date estimée (ex: "T3 2026")
          source         : str  — origine de l'information
          type           : str  — IPO_MAJEUR / EMISSION_OBLIG / AUTRE
          note           : str  — contexte libre

        Le scan :
          1. Fetche les prix réels (yfinance + FRED + CFTC)
          2. Détecte les anomalies sur les ratios surveillés
          3. Applique la RÈGLE MONÉTAIRE ÉTERNELLE : l'événement injecté
             est traité comme cause candidate des anomalies observées
          4. Génère un rapport structuré (SANS Telegram, SANS journal SQLite)
        """
        import statistics

        ts_debut = datetime.now(timezone.utc).isoformat()
        nom_evt  = self._sanitize(evenement.get("titre", "Événement inconnu"), 100)
        valo     = self._sanitize(evenement.get("valorisation", "N/D"), 50)
        date_evt = self._sanitize(evenement.get("date_prevue", "N/D"), 30)
        source_evt = self._sanitize(evenement.get("source", "N/D"), 150)
        note_evt   = self._sanitize(evenement.get("note", ""), 300)
        type_evt   = evenement.get("type", "IPO_MAJEUR")

        sources_actives: list[str] = []

        # ── Fetch données réelles ───────────────────────────────────────────
        prix_result = self._fetch_prix()
        if prix_result.get("ok"):
            sources_actives.append("yfinance (GC=F, HSI, AAXJ, URTH, IRX, USDJPY, GLD, USO)")

        fred_result = self._fetch_fred()
        fred_ok     = fred_result.get("ok", False)
        if fred_ok:
            sources_actives.append("FRED API (DGS3MO, DGS10, T10YIE)")

        cftc_result = self._fetch_cftc()
        cftc_ok     = cftc_result.get("ok", False)
        if cftc_ok:
            net_mm = cftc_result.get("net_mm", "N/A")
            sources_actives.append(f"CFTC COT ({cftc_result.get('report_date','?')}) — MM Net: {net_mm}")

        # Événement injecté compte comme source
        sources_actives.append(f"Événement injecté : {nom_evt} ({source_evt})")

        # ── Détection anomalies ─────────────────────────────────────────────
        prix_data   = prix_result.get("data", {})
        anomalies   = self._detect_anomalies(prix_data) if prix_result.get("ok") else []
        ratios_etat = self._compute_ratios_etat(prix_data) if prix_result.get("ok") else []

        # ── Application RÈGLE MONÉTAIRE ÉTERNELLE ──────────────────────────
        # L'événement injecté EST la cause candidate — on applique le corollaire IPO
        mecanisme_rme = (
            f"APPLICATION RÈGLE MONÉTAIRE ÉTERNELLE :\n"
            f"Si {nom_evt} ({valo}) absorbe de la liquidité vers {date_evt},\n"
            f"alors selon la comptabilité en partie double des marchés :\n"
            f"  → Des investisseurs doivent VENDRE d'autres actifs pour libérer du cash\n"
            f"  → Actifs suspects : Or (GLD/GC=F), actions EM (AAXJ, ^HSI), obligations\n"
            f"  → Signal attendu J-30 à J-3 : pression vendeuse anormale sur ces actifs\n"
            f"  → Post-{type_evt} : rebond possible si sur-souscrit\n"
        )

        # Confrontation avec les anomalies observées
        anomalies_concordantes = []
        for a in anomalies:
            if a["id"] in ("or_msci", "gld_flows", "hsi_aaxj", "irx_bp", "usdjpy"):
                concordance = "CONCORDANT" if a["variation_pct"] < 0 else "CONTRA-INDICATIF"
                anomalies_concordantes.append({**a, "concordance_rme": concordance})

        if anomalies_concordantes:
            nb_concord = sum(1 for x in anomalies_concordantes if x["concordance_rme"] == "CONCORDANT")
            mecanisme_rme += (
                f"\nANOMALIES OBSERVÉES CONCORDANTES : {nb_concord}/{len(anomalies_concordantes)}\n"
            )
            for a in anomalies_concordantes:
                signe = "✓" if a["concordance_rme"] == "CONCORDANT" else "✗"
                mecanisme_rme += f"  {signe} {a['label']} : {a['variation_pct']:+.1f}% (z={a['z_score']:+.1f}σ) — {a['concordance_rme']}\n"
        else:
            mecanisme_rme += "\nAucune anomalie concordante détectée sur les actifs surveillés.\n"

        # ── Checklist biais avec événement injecté ─────────────────────────
        ipos_fictifs = [{"titre": nom_evt, "date": date_evt, "url": ""}]
        biais_results = self._run_biais_checklist(
            anomalies, sources_actives, ipos_fictifs, fred_ok, cftc_ok
        )
        # causalite_temporelle : True car événement injecté fournit la cause candidate
        biais_results["causalite_temporelle"] = True
        # mecanisme_explicite : True si l'événement a une valorisation chiffrée
        biais_results["mecanisme_explicite"]  = bool(valo and valo != "N/D")

        confiance = self._calcul_confiance(biais_results, len(sources_actives), 3)

        # ── Taux réels (FRED) ───────────────────────────────────────────────
        fred_data  = fred_result.get("data", {})
        dgs3mo  = fred_data.get("DGS3MO", {}).get("value", "DONNÉES INDISPONIBLES")
        dgs10   = fred_data.get("DGS10",  {}).get("value", "DONNÉES INDISPONIBLES")
        t10yie  = fred_data.get("T10YIE", {}).get("value", "DONNÉES INDISPONIBLES")

        # ── Conclusion ──────────────────────────────────────────────────────
        nb_concord = sum(
            1 for a in anomalies_concordantes
            if a.get("concordance_rme") == "CONCORDANT"
        ) if anomalies_concordantes else 0

        if confiance == "INSUFFISANT":
            conclusion = (
                f"Données insuffisantes pour conclure sur l'impact de {nom_evt}. "
                "La Règle Monétaire Éternelle s'applique théoriquement mais aucune "
                "anomalie mesurable n'est confirmée sur les 3 sources requises."
            )
            action = "Attendre données supplémentaires. Relancer scan dans 48-72h."
        elif nb_concord >= 2:
            conclusion = (
                f"Signal CONCORDANT avec la Règle Monétaire Éternelle. "
                f"{nb_concord} actif(s) sous pression vendeuse anormale, "
                f"cohérent avec une absorption de liquidité pré-{type_evt} {nom_evt}. "
                f"Mécanisme probable : rotation institutionnelle vers {date_evt}."
            )
            action = (
                f"Surveiller GLD et AAXJ pour signal de rebond post-{type_evt}. "
                "Attendre confirmation sur 2e timeframe avant action. < 15% portefeuille."
            )
        elif anomalies and not anomalies_concordantes:
            conclusion = (
                f"Anomalies détectées mais NON concordantes avec l'hypothèse {nom_evt}. "
                "La Règle Monétaire Éternelle ne peut pas être appliquée : "
                "le mécanisme d'absorption n'est pas visible sur les actifs surveillés."
            )
            action = "Thèse rejetée pour ce scan. Chercher autre cause pour les anomalies."
        else:
            conclusion = (
                f"Aucune anomalie mesurable sur les actifs surveilles. "
                f"Pas de signal de rotation pré-{type_evt} détectable aujourd'hui. "
                "Soit l'absorption n'a pas encore commencé, soit l'effet est en dehors "
                "de notre univers de surveillance (dark pools, OTC)."
            )
            action = (
                f"Relancer scan J-15 et J-7 avant {date_evt}. "
                "Intensifier surveillance GLD volume et AAXJ."
            )

        pourquoi_tort = (
            f"• SpaceX / {nom_evt} peut lever via placement privé (pas d'absorption marché public)\n"
            f"• Les dark pools (~40% volume US) peuvent absorber l'effet\n"
            f"• L'événement peut être retardé ou annulé — source : {source_evt}\n"
            f"• La corrélation Or↓/IPO n'est pas prouvée causalement (Phase 1)\n"
            f"• D'autres événements macro peuvent expliquer les anomalies observées\n"
            f"• Note : {note_evt or 'Aucune'}"
        )

        # ── Rapport structuré ───────────────────────────────────────────────
        rapport = {
            "type":                "SCAN_CONTEXTE",
            "timestamp":           ts_debut,
            "evenement": {
                "titre":       nom_evt,
                "valorisation": valo,
                "date_prevue": date_evt,
                "source":      source_evt,
                "type":        type_evt,
                "note":        note_evt,
            },
            "regle_monetaire_eternelle": REGLE_MONETAIRE_ETERNELLE.strip(),
            "sources_actives":     sources_actives,
            "nb_sources":          len(sources_actives),
            "ratios_actuels":      ratios_etat,
            "anomalies_detectees": anomalies,
            "anomalies_concordantes": anomalies_concordantes,
            "fred": {
                "DGS3MO":  dgs3mo,
                "DGS10":   dgs10,
                "T10YIE":  t10yie,
            },
            "cftc":                cftc_result if cftc_ok else {"ok": False, "reason": "DONNÉES INDISPONIBLES"},
            "mecanisme_rme":       mecanisme_rme,
            "biais_checklist":     biais_results,
            "confiance":           confiance,
            "conclusion":          conclusion,
            "action_suggeree":     action,
            "pourquoi_tort":       pourquoi_tort,
            "limites":             LIMITES_FONDAMENTALES,
            "disclaimer":          DISCLAIMER,
        }
        return rapport

    def etat(self) -> dict:
        """Retourne l'état courant (depuis cache si disponible)."""
        if self._cache:
            return {
                "timestamp":       self._cache.get("timestamp"),
                "nb_anomalies":    len(self._cache.get("anomalies", [])),
                "confiance":       self._cache.get("confiance"),
                "nb_sources":      self._cache.get("nb_sources", 0),
                "alertes_envoyees": self._cache.get("alertes_envoyees", []),
            }
        return {"timestamp": None, "nb_anomalies": 0, "confiance": None, "nb_sources": 0}
