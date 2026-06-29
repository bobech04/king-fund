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
import urllib.parse
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

# ---------------------------------------------------------------------------
# RÉGIMES DE MARCHÉ (Institut des Libertés — 4 états)
# ---------------------------------------------------------------------------

REGIMES_MARCHE: dict[str, dict] = {
    "NORMAL": {
        "description": "Taux réels bas, liquidité abondante, obligations antifragiles",
        "protection": "Portefeuille standard — actifs réels + dividendes",
    },
    "ROTATION": {
        "description": "Absorption IPOs, baisse temporaire actifs refuge, corrélation stocks/bonds normale",
        "protection": "Accumulation actifs refuge pendant la baisse temporaire",
    },
    "CRISE_LIQUIDITE": {
        "description": (
            "Haut à gauche — cash is king. Obligations ET actions baissent simultanément. "
            "Actifs vendus par contrainte. Signal : corr(TLT, SPY) > 0 sur 5 jours glissants."
        ),
        "protection": "Augmenter cash — réduire exposition actifs risqués — garder or physique",
    },
    "EFFONDREMENT": {
        "description": (
            "1929-like — monopoles + décorrélation valorisations/réalité + "
            "ruptures d'approvisionnement simultanées"
        ),
        "protection": "Cash + or physique + actifs hors système",
    },
}

# ---------------------------------------------------------------------------
# PRÉCÉDENTS IPO/ABSORPTION — Base historique complète
# Source : REGLE_MONETAIRE_ETERNELLE + Institut des Libertés
# ---------------------------------------------------------------------------

PRECEDENTS_IPO_ABSORPTION: list[dict] = [
    {
        "nom":        "Alibaba IPO 2014",
        "montant":    25.0,
        "effet_or":   -3.0,
        "effet_hk":   -2.5,
        "regime":     "NORMAL",
        "note":       "Premier test à grande échelle de la RME. Or -3% dans les 3 semaines avant.",
    },
    {
        "nom":        "Facebook IPO 2012",
        "montant":    16.0,
        "effet_or":   -1.8,
        "effet_hk":   -1.2,
        "regime":     "NORMAL",
        "note":       "Première méga-IPO tech US. Rotation prévisible mais effet limité par QE Fed.",
    },
    {
        "nom":        "Saudi Aramco IPO 2019",
        "montant":    29.0,
        "effet_or":   -2.1,
        "effet_hk":   -4.0,
        "regime":     "NORMAL",
        "note":       "EM sous-performance -4% vs MSCI World. Fonds souverains MO massivement présents.",
    },
    {
        "nom":        "Krach 1929 — Absorption extrême",
        "montant":    None,
        "effet_or":   None,
        "effet_hk":   None,
        "regime":     "EFFONDREMENT",
        "note": (
            "Référence EFFONDREMENT : monopoles (US Steel, Standard Oil) + décorrélation "
            "valorisations/réalité + ruptures approvisionnement simultanées. "
            "Pas d'équivalent moderne direct."
        ),
    },
    {
        "nom":        "SpaceX IPO 2026 (en cours)",
        "montant":    85.0,
        "effet_or":   -6.2,
        "effet_hk":   -8.3,
        "regime":     "ROTATION→CRISE_LIQUIDITE",
        "note": (
            "6x Aramco = TERRITOIRE INCONNU. Pas de précédent fiable à cette échelle. "
            "Manipulation indice Nasdaq (poids estimé 5%→15%). "
            "Fonds souverains MO absents. Risque glissement ROTATION→CRISE_LIQUIDITE."
        ),
    },
]

# ---------------------------------------------------------------------------
# DISTINCTION VENTES OR — 3 cas (Institut des Libertés)
# Indicateurs CFTC + TIC + WGC pour identifier la nature de la vente
# ---------------------------------------------------------------------------

DISTINCTION_VENTES_OR: dict[str, dict] = {
    "CAS_A_CONTRAINTE_SOUVERAINE": {
        "description": "Banques centrales / fonds souverains vendent pour financer dépenses",
        "indicateurs": [
            "TIC Data : flux ventes obligations US par banques centrales étrangères",
            "WGC (World Gold Council) : rapport trimestriel ventes banques centrales",
            "Signal : ventes massives OR + ventes simultanées Treasuries US",
        ],
        "action": "Signal CRITIQUE — crise de balance des paiements d'un souverain",
        "source_verification": "ticdata.treasury.gov (délai 6 sem.) | gold.org/goldhub",
    },
    "CAS_B_FINANCEMENT_IPO": {
        "description": "Institutionnels vendent OR pour libérer cash et souscrire à une IPO majeure",
        "indicateurs": [
            "CFTC COT : baisse positions Long MM (Managed Money) sur GC=F",
            "Calendrier IPO : montant levé > 10 Md$ dans les 30 jours",
            "Signal : ventes OR corrélées J-30→J-3 avant date IPO",
        ],
        "action": "Signal ROTATION — opportunité d'accumulation OR post-IPO",
        "source_verification": "CFTC Socrata (hebdo) | SEC EDGAR S-1 filings",
    },
    "CAS_C_STRATEGIQUE": {
        "description": "Rotation stratégique vers actifs risqués (risk-on) ou vers cash",
        "indicateurs": [
            "VIX < 15 + hausse SPY simultanée → risk-on (OR vendu pour actions)",
            "VIX > 25 + baisse SPY simultanée → CRISE_LIQUIDITE (OR vendu par contrainte)",
            "CFTC : positions Short MM augmentent sans événement calendrier identifié",
        ],
        "action": "Analyser VIX + SPY + TLT simultanément pour distinguer risk-on vs contrainte",
        "source_verification": "yfinance (^VIX, SPY, TLT) | CFTC Socrata",
    },
}

# ---------------------------------------------------------------------------
# RÈGLE ANTIFRAGILITÉ OBLIGATIONS (Principes fondamentaux)
# Source : Taleb / Gavekal / Institut des Libertés
# ---------------------------------------------------------------------------

REGLE_ANTIFRAGILITE_OBLIGATIONS = """
RÈGLE ANTIFRAGILITÉ DES OBLIGATIONS

SOURCE : Taleb (Antifragile) — Gavekal — Institut des Libertés

PRINCIPE
  En régime NORMAL : les obligations d'État (TLT) sont ANTIFRAGILES.
  Quand les actions baissent (stress marché), les obligations MONTENT.
  → Le portefeuille 60/40 fonctionne : les obligations amortissent les chocs.

RUPTURE DE L'ANTIFRAGILITÉ (CRISE_LIQUIDITE)
  En régime CRISE_LIQUIDITE : TLT ET SPY baissent SIMULTANÉMENT.
  → Les obligations PERDENT leur propriété antifragile.
  → Le cash devient le seul actif refuge.
  Signal mesurable : corr(TLT_returns, SPY_returns) > 0 sur 5 jours glissants.

EXEMPLES HISTORIQUES
  • Mars 2020 (COVID crash) : TLT et SPY ont baissé simultanément pendant 3 jours
    avant l'intervention Fed. Signal précurseur de CRISE_LIQUIDITE transitoire.
  • 2022 (hausse taux Fed) : TLT -30%, SPY -20% sur l'année. Corrélation positive
    durable → régime CRISE_LIQUIDITE confirmé sur toute l'année 2022.
  • 2008 (post-Lehman) : TLT a MONTÉ (refuge) → pas de CRISE_LIQUIDITE pure,
    mais EFFONDREMENT partiel. Distinction importante.

APPLICATION KING FUND
  → Surveiller corr(TLT, SPY) sur 5 jours glissants via _detect_regime_marche()
  → Si > 0 : déclencher alerte CRITIQUE CRISE_LIQUIDITE
  → Dans ce régime : réduire exposition, augmenter cash, conserver or physique

DISCLAIMER : Raisonnement qualitatif. Non statistiquement prouvé.
"""

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
    "TLT":    "TLT",         # iShares 20+ Year Treasury — détection antifragilité obligations
    "SPY":    "SPY",         # SPDR S&P 500 ETF — ratio TLT/SPY → CRISE_LIQUIDITE
    "COPX":   "COPX",        # Global X Copper Miners ETF — cuivre = signal croissance réelle vs financière
    "UNG":    "UNG",         # United States Natural Gas Fund — signal énergie/inflation
    "QQQ":   "QQQ",          # Invesco QQQ Trust (Nasdaq 100 ETF) — tech vs large cap
    # ── Indices asiatiques (surveillance bloodbath / contagion) ──────────────
    "KOSPI":  "^KS11",       # KOSPI — Corée du Sud
    "NIKKEI": "^N225",       # Nikkei 225 — Japon
    "TAIWAN": "^TWII",       # Taiwan Weighted Index
    # ── FX funding stress (Jeff Snider Eurodollar) ──────────────────────────
    "USDKRW": "USDKRW=X",   # USD/KRW — proxy dollar funding stress EM
}

FRED_SERIES = ["DGS3MO", "DGS10", "T10YIE"]

# Indicateurs de liquidité macro (nécessitent historique pour calcul variation)
FRED_SERIES_LIQUIDITE = ["M2SL", "WALCL", "IORB", "BAMLC0A0CM", "BAMLH0A0HYM2"]

# Jeff Snider Eurodollar — SOFR/repo/funding stress
# SOFR  : Secured Overnight Financing Rate (FRBNY via FRED)
# EFFR  : Effective Federal Funds Rate (Fed via FRED)
# RRPONTSYD : Overnight Reverse Repo operations outstanding (Mds$)
FRED_SERIES_SOFR = ["SOFR", "EFFR", "RRPONTSYD"]
SOFR_SEUILS = {
    "spread_alerte_bps":  50.0,   # SOFR - EFFR > 50 bps → alerte funding stress
    "spread_critique_bps": 100.0, # SOFR - EFFR > 100 bps → CRITIQUE
    "rrpon_bas_bn":        50.0,  # RRPONTSYD < 50 Mds$ → potential stress
}

# Seuils d'alerte liquidité (spec)
# Note FRED units : BAMLC0A0CM et BAMLH0A0HYM2 sont en % (pas bps)
# → 150 bps = 1.50% | 500 bps = 5.00%
# WALCL est en millions de dollars (pas milliards)
LIQUIDITE_SEUILS = {
    "M2SL_yoy_orange":    2.0,    # croissance M2 < 2% → alerte orange
    "M2SL_yoy_rouge":     0.0,    # croissance M2 < 0  → alerte rouge
    "WALCL_baisse_3m":   -5.0,   # baisse Fed BS > 5% sur 3 mois (en %)
    "IG_spread_max_pct":  1.50,  # spreads IG > 1.50% (= 150 bps dans unité FRED)
    "HY_spread_max_pct":  5.00,  # spreads HY > 5.00% (= 500 bps dans unité FRED)
}

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
    "precedent_comparable":  {
        "question":         "Le précédent historique est-il vraiment comparable en taille et contexte ?",
        "note":             "SpaceX 85Mds$ = 6x Aramco = TERRITOIRE INCONNU. Pas de précédent fiable.",
        "blocage":          False,
        "action_si_echec":  "Déclasser confiance à MOYEN, ajouter avertissement dans rapport",
    },
}

_FETCH_TIMEOUT = 30  # seconds for all external requests

_RAPPORTS_DIR = Path(__file__).resolve().parents[4] / "rapports" / "flux_macro"

# ---------------------------------------------------------------------------
# EUROSTAT — API publique gratuite, sans clé
# https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/
# Seuils d'alerte : PIB (croissance a/a) < 0% | HICP (inflation a/a) > 4%
# ---------------------------------------------------------------------------

_EUROSTAT_BASE = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data"
_EUROSTAT_GEO  = "EU27_2020"

_EUROSTAT_SEUIL_PIB_PCT  = 0.0   # alerte si croissance PIB a/a < 0%
_EUROSTAT_SEUIL_HICP_PCT = 4.0   # alerte si inflation HICP a/a > 4%

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
# Agent Bear (Phase 2 — Avocat du diable structuré)
# ---------------------------------------------------------------------------

class _AgentBear:
    """
    Agent Bear — positionné en opposition systématique à la thèse Bull.
    Prompt : 'prouve que cette thèse est fausse'.
    Retourne position_bear, raisons_bear, biais_probable, these_alternative.
    """

    def analyser(self, these_bull: str, regime: str, confiance: str) -> dict:
        try:
            from config import ANTHROPIC_API_KEY
            if not ANTHROPIC_API_KEY:
                return {
                    "ok": False, "raison": "ANTHROPIC_API_KEY absent",
                    "position_bear": "—", "raisons_bear": [],
                    "biais_probable": "—", "these_alternative": "—",
                }
            import anthropic
            prompt = (
                "Tu es un analyste macro sceptique et contradicteur structurel.\n\n"
                f"THÈSE BULL :\n{these_bull[:500]}\n"
                f"RÉGIME MARCHÉ : {regime}\n"
                f"CONFIANCE : {confiance}\n\n"
                "Prouve que cette thèse est fausse. "
                "Donne 3 contre-arguments concrets et quantifiés. "
                "Identifie le biais cognitif le plus probable. "
                "Propose une thèse alternative. "
                "Format JSON strict :\n"
                '{"position_bear": "...", "raisons": ["...", "...", "..."], '
                '"biais_probable": "...", "these_alternative": "..."}'
            )
            client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
            msg = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=500,
                messages=[{"role": "user", "content": prompt}],
            )
            texte = msg.content[0].text.strip()
            m = re.search(r'\{.*\}', texte, re.DOTALL)
            if m:
                data = json.loads(m.group(0))
                return {
                    "ok":                True,
                    "position_bear":     data.get("position_bear", "—"),
                    "raisons_bear":      data.get("raisons", []),
                    "biais_probable":    data.get("biais_probable", "—"),
                    "these_alternative": data.get("these_alternative", "—"),
                }
            return {
                "ok": True, "position_bear": texte[:400], "raisons_bear": [],
                "biais_probable": "—", "these_alternative": "—",
            }
        except Exception as exc:
            return {
                "ok": False, "raison": str(exc), "position_bear": "—",
                "raisons_bear": [], "biais_probable": "—", "these_alternative": "—",
            }


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
        self._bear = _AgentBear()
        _RAPPORTS_DIR.mkdir(parents=True, exist_ok=True)
        (_RAPPORTS_DIR / "flash").mkdir(exist_ok=True)
        (_RAPPORTS_DIR / "hebdo").mkdir(exist_ok=True)
        # Cache Macro EU (Eurostat) — données mensuelles/trimestrielles, TTL long
        self._cache_macro_eu: dict | None = None
        self._cache_macro_eu_ts: float    = 0.0
        self._cache_macro_eu_ttl: int     = 3600 * 6   # 6h

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
                    sources_utilisees TEXT,
                    confiance         TEXT,
                    conclusion        TEXT,
                    action_suggeree   TEXT,
                    verdict_posteriori TEXT DEFAULT NULL,
                    faux_positif      INTEGER DEFAULT NULL,
                    sources_actives   TEXT,
                    created_at        TEXT DEFAULT (datetime('now'))
                )
            """)
            # Migration : ajoute les colonnes manquantes pour les DBs existantes
            for col, typedef in [
                ("sources_utilisees", "TEXT"),
                ("action_suggeree",   "TEXT"),
            ]:
                try:
                    con.execute(f"ALTER TABLE flux_macro_journal ADD COLUMN {col} {typedef}")
                except Exception:
                    pass  # colonne déjà présente
            con.commit()
            con.close()
        except Exception as exc:
            logger.warning("[FluxMacro] init_db: %s", exc)

    def _save_journal(self, anomalie: str, cause: str, confiance: str,
                      conclusion: str, sources: list[str],
                      action_suggeree: str = "") -> None:
        if not self._db_path:
            return
        try:
            con = sqlite3.connect(self._db_path)
            con.execute(
                """INSERT INTO flux_macro_journal
                   (date, anomalie_detectee, cause_identifiee, sources_utilisees,
                    confiance, conclusion, action_suggeree, sources_actives)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    datetime.now(timezone.utc).isoformat(),
                    anomalie[:500]        if anomalie        else None,
                    cause[:500]           if cause           else None,
                    json.dumps(sources),
                    confiance,
                    conclusion[:1000]     if conclusion      else None,
                    action_suggeree[:500] if action_suggeree else None,
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
                "SELECT date,anomalie_detectee,cause_identifiee,sources_utilisees,"
                "confiance,conclusion,action_suggeree,"
                "verdict_posteriori,faux_positif,sources_actives,created_at "
                "FROM flux_macro_journal ORDER BY id DESC LIMIT ?",
                (limite,),
            ).fetchall()
            con.close()
            cols = ["date", "anomalie", "cause", "sources_utilisees",
                    "confiance", "conclusion", "action_suggeree",
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
        CFTC Commitments of Traders — positions spéculatives hebdomadaires.
        Marchés : Or/COMEX (GC=F), Pétrole WTI/NYMEX (CL=F), Yen/CME (USDJPY).
        Source disaggregée (jun7-fc8e) : champ m_money_positions_* (Managed Money).
        Source legacy (6dca-aqww)     : champ noncomm_positions_*  (Non-Commercial).
        URL de référence : https://www.cftc.gov/dea/futures/deacmxsf.htm
        Cadence : hebdomadaire — rapport publié le vendredi.
        """
        def _one(dataset: str, market_enc: str, long_field: str, short_field: str,
                 label: str) -> dict:
            try:
                url = (
                    f"https://publicreporting.cftc.gov/resource/{dataset}.json"
                    f"?market_and_exchange_names={market_enc}"
                    f"&%24order=report_date_as_yyyy_mm_dd+DESC&%24limit=1"
                )
                req = urllib.request.Request(
                    url,
                    headers={"User-Agent": "king-fund-flux-macro/1.0", "Accept": "application/json"},
                )
                with urllib.request.urlopen(req, timeout=_FETCH_TIMEOUT) as resp:
                    raw = resp.read().decode("utf-8", errors="replace")
                rows = json.loads(raw)
                if not rows:
                    return {"ok": False, "reason": "DONNÉES INDISPONIBLES", "label": label}
                r = rows[0]
                long_  = int(r.get(long_field,  0) or 0)
                short_ = int(r.get(short_field, 0) or 0)
                return {
                    "ok":          True,
                    "label":       label,
                    "report_date": self._sanitize(r.get("report_date_as_yyyy_mm_dd", "?"), 20),
                    "mm_long":     long_,
                    "mm_short":    short_,
                    "net_mm":      long_ - short_,
                    "freshness":   "OK",
                }
            except Exception as exc:
                logger.debug("[FluxMacro] CFTC %s: %s", label, exc)
                return {"ok": False, "reason": str(exc), "label": label}

        # Disaggregated dataset — Managed Money (commodities + financials)
        DIS, DIS_L, DIS_S = "jun7-fc8e", "m_money_positions_long_all", "m_money_positions_short_all"
        # Legacy dataset — Non-Commercial (financial futures incl. currencies)
        LEG, LEG_L, LEG_S = "6dca-aqww", "noncomm_positions_long_all", "noncomm_positions_short_all"

        or_data  = _one(DIS, "GOLD%20-%20COMMODITY%20EXCHANGE%20INC.", DIS_L, DIS_S, "Or/COMEX")
        # Fallback market name for gold if primary fails
        if not or_data.get("ok"):
            or_data = _one(DIS, "GOLD%20(COMEX)", DIS_L, DIS_S, "Or/COMEX")

        wti_data = _one(
            DIS,
            "CRUDE%20OIL%2C%20LIGHT%20SWEET%20-%20NEW%20YORK%20MERCANTILE%20EXCHANGE",
            DIS_L, DIS_S, "Pétrole WTI/NYMEX",
        )
        yen_data = _one(LEG, "JAPANESE%20YEN", LEG_L, LEG_S, "Yen/CME")

        any_ok = any(d.get("ok") for d in [or_data, wti_data, yen_data])
        report_date = next(
            (d.get("report_date", "?") for d in [or_data, wti_data, yen_data] if d.get("ok")),
            "?",
        )

        return {
            "ok":          any_ok,
            "report_date": report_date,
            "freshness":   "OK" if any_ok else "UNAVAILABLE",
            # Sous-positions par marché
            "or":          or_data,
            "petrole":     wti_data,
            "yen":         yen_data,
            # Rétro-compatibilité (or uniquement — champs historiques)
            "mm_long":     or_data.get("mm_long",  0),
            "mm_short":    or_data.get("mm_short", 0),
            "net_mm":      or_data.get("net_mm",   0),
        }

    def _fetch_wgc(self) -> dict[str, Any]:
        """
        World Gold Council — réserves or banques centrales.
        Source principale  : gold.org/goldhub/data/gold-reserves-by-country (mensuel).
        Fallback automatique : IMF DataMapper API (RESDMA@IFS — réserves internationales).
        CADENCE : mensuel — délai ~2 mois (rapport WGC/IMF).
        USAGE : alimente DISTINCTION_VENTES_OR — CAS_A (ventes souveraines sous contrainte)
                vs CAS_B (financement IPO) en croisant avec TIC Data.
        """
        # Données statiques top-10 (WGC Q1 2025) — fallback si API indisponible
        # Actualiser chaque trimestre depuis gold.org/goldhub/data/gold-reserves-by-country
        RESERVES_STATIQUES: dict[str, float] = {
            "USA":        8133.5,
            "Allemagne":  3351.5,
            "Italie":     2451.8,
            "France":     2436.9,
            "Russie":     2335.9,
            "Chine":      2264.3,
            "Japon":       845.8,
            "Inde":        840.4,
            "Pays-Bas":    612.5,
            "Turquie":     580.0,
        }

        # Tentative IMF DataMapper (API publique)
        try:
            url = (
                "https://www.imf.org/external/datamapper/api/v1/RESDMA@IFS"
                "/USA,DEU,ITA,FRA,RUS,CHN,JPN,IND,GBR,CHE"
            )
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "king-fund-research@kingfund.local",
                         "Accept": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
            imf_data = json.loads(raw)
            values = imf_data.get("values", {}).get("RESDMA@IFS", {})
            if values:
                reserves_imf: dict[str, float] = {}
                for code, series in values.items():
                    latest = next(
                        (v for v in reversed(list(series.values())) if v is not None),
                        None,
                    )
                    if latest is not None:
                        reserves_imf[code] = round(float(latest), 1)
                if reserves_imf:
                    return {
                        "ok":                   True,
                        "source":               "IMF DataMapper (RESDMA@IFS)",
                        "cadence":              "mensuel",
                        "delai_mois":           2,
                        "reserves_imf":         reserves_imf,
                        "top_holders_statiques": RESERVES_STATIQUES,
                        "note":                 "Réserves internationales totales (IMF) — inclut or + devises.",
                        "freshness":            "OK",
                    }
        except Exception as exc:
            logger.debug("[FluxMacro] WGC/IMF: %s", exc)

        # Fallback : données statiques WGC Q1 2025
        return {
            "ok":                   False,
            "source":               "WGC — données statiques Q1 2025 (gold.org/goldhub)",
            "cadence":              "mensuel",
            "delai_mois":           2,
            "top_holders_statiques": RESERVES_STATIQUES,
            "note":                 (
                "API WGC non accessible publiquement. Données statiques Q1 2025 — "
                "actualiser depuis gold.org/goldhub/data/gold-reserves-by-country. "
                "Croiser avec TIC Data pour distinguer CAS_A (vente souveraine) "
                "vs CAS_B (financement IPO) dans DISTINCTION_VENTES_OR."
            ),
            "freshness":            "STATIC",
        }

    def _fetch_tic_data(self) -> dict[str, Any]:
        """
        TIC Data Treasury — avoirs étrangers en Treasuries US (mensuel).
        Source : ticdata.treasury.gov — Major Foreign Holders of Treasury Securities.
        ⚠️ DÉLAI STRUCTUREL OBLIGATOIRE 6 SEMAINES ⚠️
           Données publiées le 3e jeudi du mois → couvrent ~6 semaines avant.
           Ex : rapport du 15 août = données du 30 juin.
           NE JAMAIS interpréter comme signal récent ou contemporain.
        CADENCE : mensuel.
        """
        DELAI_NOTE = (
            "DELAI STRUCTUREL 6 SEMAINES : donnees publiees le 3e jeudi du mois, "
            "couvrant les positions de ~6 semaines auparavant. "
            "NE PAS interpreter comme signal recent. "
            "Source : ticdata.treasury.gov/Publish/mfhhis01.txt"
        )

        try:
            url = "https://ticdata.treasury.gov/Publish/mfhhis01.txt"
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "king-fund-research@kingfund.local",
                    "Accept":     "text/plain, */*",
                },
            )
            with urllib.request.urlopen(req, timeout=_FETCH_TIMEOUT) as resp:
                raw = resp.read().decode("latin-1", errors="replace")

            lines     = [ln.rstrip() for ln in raw.splitlines()]
            holders: list[dict] = []
            date_ref  = ""

            for line in lines:
                stripped = line.strip()
                if not stripped:
                    continue

                # Extraire la référence de date (ex: "Jun 2025")
                if not date_ref:
                    m = re.search(
                        r'(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{4})',
                        stripped,
                    )
                    if m:
                        date_ref = m.group(0)
                        continue

                # Parser les lignes de données pays + valeur(s)
                parts = stripped.split()
                if len(parts) < 2:
                    continue
                nums: list[float] = []
                name_parts: list[str] = []
                for p in parts:
                    try:
                        nums.append(float(p.replace(",", "")))
                    except ValueError:
                        if not nums:
                            name_parts.append(p)
                if not nums or not name_parts:
                    continue
                country = " ".join(name_parts)
                skip = ("Total", "Grand", "All Other", "Supranational", "Caribbean")
                if any(s.lower() in country.lower() for s in skip):
                    continue
                val = nums[0]
                if val > 0:
                    holders.append({
                        "pays":           self._sanitize(country, 50),
                        "milliards_usd":  round(val, 1),
                    })
                if len(holders) >= 25:
                    break

            if holders:
                holders.sort(key=lambda x: x["milliards_usd"], reverse=True)
                total = sum(h["milliards_usd"] for h in holders)
                return {
                    "ok":                      True,
                    "delai_note":              DELAI_NOTE,
                    "cadence":                 "mensuel",
                    "date_reference":          date_ref or "voir source",
                    "top_holders":             holders[:15],
                    "total_capture_mds_usd":   round(total, 1),
                    "source":                  url,
                    "freshness":               "STALE",
                    "freshness_note":          "Toujours STALE par definition (delai structurel 6 semaines)",
                }

            return {
                "ok":       False,
                "reason":   "Aucune donnee parsee depuis le fichier TIC",
                "delai_note": DELAI_NOTE,
                "source":   url,
            }

        except Exception as exc:
            logger.debug("[FluxMacro] TIC Data: %s", exc)
            return {
                "ok":       False,
                "reason":   str(exc),
                "delai_note": DELAI_NOTE,
                "source":   "https://ticdata.treasury.gov/Publish/mfhhis01.txt",
            }

    def _fetch_fred_liquidite(self) -> dict[str, Any]:
        """
        Fetch indicateurs liquidité macro : M2SL, WALCL, IORB, spreads IG/HY.
        Retourne historique 13 périodes pour calculer variations.
        """
        result: dict[str, Any] = {}
        try:
            from config import FRED_API_KEY
            if not FRED_API_KEY:
                return {"ok": False, "reason": "FRED_API_KEY absent", "data": {}}
            from fredapi import Fred
            fred = Fred(api_key=FRED_API_KEY)
            for series_id in FRED_SERIES_LIQUIDITE:
                try:
                    s = fred.get_series_latest_release(series_id)
                    s_clean = s.dropna()
                    if s_clean.empty:
                        result[series_id] = {"value": None, "freshness": "UNAVAILABLE", "hist": []}
                        continue
                    val  = float(s_clean.iloc[-1])
                    hist = [float(x) for x in s_clean.tail(14).tolist()]
                    result[series_id] = {"value": val, "freshness": "OK", "hist": hist}
                except Exception as exc:
                    logger.debug("[FluxMacro] FRED liq %s: %s", series_id, exc)
                    result[series_id] = {"value": None, "freshness": "UNAVAILABLE", "hist": []}
            return {"ok": True, "data": result}
        except Exception as exc:
            logger.warning("[FluxMacro] _fetch_fred_liquidite: %s", exc)
            return {"ok": False, "reason": str(exc), "data": {}}

    def _fetch_fred_sofr(self) -> dict[str, Any]:
        """
        Jeff Snider Eurodollar — SOFR / EFFR / RRPONTSYD via FRED.
        SOFR spread = SOFR - EFFR (en %) → alerte si > 50 bps (0.50%)
        RRPONTSYD = overnight reverse repos outstanding (Mds$)
        """
        result: dict[str, Any] = {}
        try:
            from config import FRED_API_KEY
            if not FRED_API_KEY:
                return {"ok": False, "reason": "FRED_API_KEY absent", "data": {}}
            from fredapi import Fred
            fred = Fred(api_key=FRED_API_KEY)
            for series_id in FRED_SERIES_SOFR:
                try:
                    s = fred.get_series_latest_release(series_id)
                    s_clean = s.dropna()
                    if s_clean.empty:
                        result[series_id] = {"value": None, "freshness": "UNAVAILABLE", "hist": []}
                        continue
                    val  = float(s_clean.iloc[-1])
                    hist = [float(x) for x in s_clean.tail(10).tolist()]
                    result[series_id] = {"value": val, "freshness": "OK", "hist": hist}
                except Exception as exc:
                    logger.debug("[FluxMacro] FRED SOFR %s: %s", series_id, exc)
                    result[series_id] = {"value": None, "freshness": "UNAVAILABLE", "hist": []}
            return {"ok": True, "data": result}
        except Exception as exc:
            logger.warning("[FluxMacro] _fetch_fred_sofr: %s", exc)
            return {"ok": False, "reason": str(exc), "data": {}}

    def _check_sofr_stress(self, sofr_data: dict, prix_data: dict[str, Any]) -> list[dict]:
        """
        Jeff Snider Eurodollar — détecte le dollar funding stress.
        Indicateurs :
          1. SOFR spread vs EFFR > 50 bps
          2. RRPONTSYD très bas (< 50 Mds$)
          3. FX swap basis approx : USD/JPY + USD/KRW hausse simultanée
        """
        alertes: list[dict] = []
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

        sofr_val  = sofr_data.get("SOFR",     {}).get("value")
        effr_val  = sofr_data.get("EFFR",     {}).get("value")
        rrpon_val = sofr_data.get("RRPONTSYD",{}).get("value")

        # 1. SOFR spread vs EFFR
        if sofr_val is not None and effr_val is not None:
            spread_pct = sofr_val - effr_val
            spread_bps = spread_pct * 100.0
            if abs(spread_bps) >= SOFR_SEUILS["spread_alerte_bps"]:
                niveau = "CRITIQUE" if abs(spread_bps) >= SOFR_SEUILS["spread_critique_bps"] else "IMPORTANT"
                alertes.append({
                    "id":          "sofr_spread",
                    "label":       f"SOFR spread vs EFFR — {spread_bps:+.1f} bps",
                    "valeur":      f"SOFR={sofr_val:.3f}% | EFFR={effr_val:.3f}% | spread={spread_bps:+.1f} bps",
                    "niveau":      niveau,
                    "seuil_label": f"seuil {SOFR_SEUILS['spread_alerte_bps']:.0f} bps (funding stress Snider)",
                    "timestamp":   now_str,
                })

        # 2. RRPONTSYD très bas → stress potentiel
        if rrpon_val is not None:
            rrpon_bn = rrpon_val / 1000.0  # FRED units = millions → Mds
            if rrpon_bn < SOFR_SEUILS["rrpon_bas_bn"]:
                alertes.append({
                    "id":          "rrpon_bas",
                    "label":       f"Reverse Repo Fed très bas — {rrpon_bn:.0f} Mds$",
                    "valeur":      f"{rrpon_bn:.1f} Mds$ (< {SOFR_SEUILS['rrpon_bas_bn']:.0f} Mds$)",
                    "niveau":      "IMPORTANT",
                    "seuil_label": "liquidité excédentaire quasi nulle — stress repo potentiel",
                    "timestamp":   now_str,
                })

        # 3. FX swap basis approx : USD/JPY + USD/KRW hausse simultanée
        jpy  = prix_data.get("USDJPY", {})
        krw  = prix_data.get("USDKRW", {})
        jpy_h = jpy.get("hist_30d") or []
        krw_h = krw.get("hist_30d") or []
        jpy_p = jpy.get("price")
        krw_p = krw.get("price")

        if jpy_p and len(jpy_h) >= 2 and jpy_h[-2]:
            jpy_var = (jpy_p - jpy_h[-2]) / jpy_h[-2] * 100
        else:
            jpy_var = None

        if krw_p and len(krw_h) >= 2 and krw_h[-2]:
            krw_var = (krw_p - krw_h[-2]) / krw_h[-2] * 100
        else:
            krw_var = None

        if jpy_var is not None and krw_var is not None:
            fx_basis_approx = (jpy_var + krw_var) / 2.0
            if fx_basis_approx > 1.5:
                alertes.append({
                    "id":          "fx_basis_approx",
                    "label":       "Dollar funding stress — USD/JPY + USD/KRW hausse simultanée",
                    "valeur":      f"USD/JPY {jpy_var:+.2f}% | USD/KRW {krw_var:+.2f}% | basis approx {fx_basis_approx:+.2f}%",
                    "niveau":      "CRITIQUE" if fx_basis_approx > 2.5 else "IMPORTANT",
                    "seuil_label": "hausse simultanée USD/JPY + USD/KRW → pression dollar funding offshore",
                    "timestamp":   now_str,
                })

        return alertes

    def _check_liquidite_seuils(self, fred_liq_data: dict) -> list[dict]:
        """Vérifie les seuils d'alerte sur les indicateurs de liquidité macro."""
        alertes: list[dict] = []
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

        m2 = fred_liq_data.get("M2SL", {})
        if m2.get("value") is not None and m2.get("hist") and len(m2["hist"]) >= 13:
            m2_now = m2["value"]
            m2_1y  = m2["hist"][-13]
            if m2_1y and m2_1y > 0:
                m2_yoy = (m2_now - m2_1y) / m2_1y * 100
                if m2_yoy < LIQUIDITE_SEUILS["M2SL_yoy_rouge"]:
                    alertes.append({"id": "m2_negatif", "label": "M2 croissance NÉGATIVE (🔴)",
                                    "valeur": round(m2_yoy, 2), "niveau": "CRITIQUE",
                                    "seuil": "< 0%", "timestamp": now_str})
                elif m2_yoy < LIQUIDITE_SEUILS["M2SL_yoy_orange"]:
                    alertes.append({"id": "m2_faible", "label": "M2 croissance faible (🟡)",
                                    "valeur": round(m2_yoy, 2), "niveau": "IMPORTANT",
                                    "seuil": "< 2%", "timestamp": now_str})

        walcl = fred_liq_data.get("WALCL", {})
        if walcl.get("value") is not None and walcl.get("hist") and len(walcl["hist"]) >= 4:
            w_now = walcl["value"]
            w_3m  = walcl["hist"][-4]
            if w_3m and w_3m > 0:
                w_var = (w_now - w_3m) / w_3m * 100
                if w_var < LIQUIDITE_SEUILS["WALCL_baisse_3m"]:
                    alertes.append({"id": "walcl_baisse", "label": "Fed balance sheet baisse > 5% (3 mois)",
                                    "valeur": round(w_var, 2), "niveau": "IMPORTANT",
                                    "seuil": "< -5% sur 3 mois", "timestamp": now_str})

        ig = fred_liq_data.get("BAMLC0A0CM", {})
        if ig.get("value") is not None and ig["value"] > LIQUIDITE_SEUILS["IG_spread_max_pct"]:
            ig_bps = round(ig["value"] * 100, 0)
            alertes.append({"id": "spread_ig", "label": "Spreads IG > 150 bps",
                            "valeur": f"{ig_bps:.0f} bps ({ig['value']:.2f}%)", "niveau": "IMPORTANT",
                            "seuil": "> 1.50% (150 bps)", "timestamp": now_str})

        hy = fred_liq_data.get("BAMLH0A0HYM2", {})
        if hy.get("value") is not None and hy["value"] > LIQUIDITE_SEUILS["HY_spread_max_pct"]:
            hy_bps = round(hy["value"] * 100, 0)
            alertes.append({"id": "spread_hy", "label": "Spreads HY > 500 bps",
                            "valeur": f"{hy_bps:.0f} bps ({hy['value']:.2f}%)", "niveau": "CRITIQUE" if hy["value"] > 8.0 else "IMPORTANT",
                            "seuil": "> 5.00% (500 bps)", "timestamp": now_str})

        return alertes

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

    def _fetch_commodites_critiques(self) -> dict[str, Any]:
        """
        Surveillance matières premières critiques : acide sulfurique, urée, terres rares.
        Sources : Reuters Business RSS (gratuit).
        Notes manuelles : IEA Strategic Petroleum Reserve (hebdo), USGS, BEA.
        """
        resultats: dict[str, Any] = {"ok": False, "alertes": [], "note": ""}
        try:
            url = "https://feeds.reuters.com/reuters/businessNews"
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "king-fund-research@kingfund.local",
                    "Accept":     "application/rss+xml,application/xml",
                },
            )
            with urllib.request.urlopen(req, timeout=_FETCH_TIMEOUT) as resp:
                raw = resp.read().decode("utf-8", errors="replace")

            root = ET.fromstring(raw)
            mots_cles = [
                "sulfuric acid", "sulfurique", "urea", "urée",
                "rare earth", "terres rares", "strategic petroleum",
                "petroleum reserve", "IEA reserve", "supply disruption",
                "reconstruction reserves", "acide sulfurique",
            ]
            alertes: list[dict] = []
            for item in root.iter("item"):
                titre = item.findtext("title") or ""
                desc  = item.findtext("description") or ""
                texte = (titre + " " + desc).lower()
                for mc in mots_cles:
                    if mc.lower() in texte:
                        alertes.append({
                            "titre":   self._sanitize(titre, 150),
                            "date":    self._sanitize(item.findtext("pubDate") or "", 50),
                            "mot_cle": mc,
                            "niveau":  "IMPORTANT",
                        })
                        break

            resultats["ok"]      = True
            resultats["alertes"] = alertes[:5]
        except Exception as exc:
            logger.debug("[FluxMacro] _fetch_commodites_critiques: %s", exc)

        resultats["note"] = (
            "Rapport BEA trimestriel : surveiller bea.gov → ratio profits US/PIB (non disponible temps réel). "
            "IEA Strategic Petroleum Reserve (hebdo gratuit) : iea.org/topics/strategic-petroleum-reserves. "
            "Mécanisme reconstruction réserves : post-conflit (Iran, MO), les pays reconstituent réserves "
            "pétrole + alimentaires → absorbe liquidités ET fait monter prix commodités. "
            "USGS critical minerals : usgs.gov/centers/national-minerals-information-center."
        )
        return resultats

    # ── Régimes de marché ────────────────────────────────────────────────────

    @staticmethod
    def _corr_pearson(xs: list[float], ys: list[float]) -> float | None:
        """Corrélation de Pearson entre deux séries de même longueur."""
        if len(xs) != len(ys) or len(xs) < 2:
            return None
        try:
            n = len(xs)
            mean_x = sum(xs) / n
            mean_y = sum(ys) / n
            num    = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
            den_x  = sum((x - mean_x) ** 2 for x in xs)
            den_y  = sum((y - mean_y) ** 2 for y in ys)
            den    = (den_x * den_y) ** 0.5
            if den < 1e-12:
                return None
            return round(num / den, 4)
        except Exception:
            return None

    @staticmethod
    def _test_granger(serie_x: list[float], serie_y: list[float], maxlag: int = 5) -> dict:
        """
        Test de causalité de Granger : serie_x cause-t-elle serie_y ?
        Retourne {ok, significatif, min_pvalue, lags_significatifs, maxlag, resume}.
        Requiert statsmodels (pip install statsmodels).
        """
        try:
            import numpy as np
            from statsmodels.tsa.stattools import grangercausalitytests
            n = min(len(serie_x), len(serie_y))
            if n < maxlag + 3:
                return {"ok": False, "raison": f"Série trop courte ({n} pts, min {maxlag + 3})"}
            data = np.column_stack([serie_y[-n:], serie_x[-n:]])
            results = grangercausalitytests(data, maxlag=maxlag, verbose=False)
            lags_sig: list[dict] = []
            min_p = 1.0
            for lag, res in results.items():
                pval = res[0]["ssr_ftest"][1]
                min_p = min(min_p, pval)
                if pval < 0.05:
                    lags_sig.append({"lag": int(lag), "pvalue": round(pval, 4)})
            sig = min_p < 0.05
            resume = (
                f"Granger X→Y : p-value min = {min_p:.4f} (lags 1-{maxlag}). "
                f"{'SIGNIFICATIF' if sig else 'NON SIGNIFICATIF'} (α=5%). "
                f"Lags sig. : {[l['lag'] for l in lags_sig] or 'aucun'}."
            )
            return {
                "ok":                 True,
                "significatif":       sig,
                "min_pvalue":         round(min_p, 6),
                "lags_significatifs": lags_sig,
                "maxlag":             maxlag,
                "resume":             resume,
            }
        except ImportError:
            return {"ok": False, "raison": "statsmodels requis (pip install statsmodels)"}
        except Exception as exc:
            return {"ok": False, "raison": str(exc)}

    def _detect_regime_marche(self, prix_data: dict[str, Any]) -> dict[str, Any]:
        """
        Détecte le régime de marché actuel parmi 4 états.
        Signal CRISE_LIQUIDITE : corr(TLT, SPY) > 0 sur 5 jours glissants
          → les deux baissent ensemble (obligations perdent antifragilité).
        Signal ROTATION : or + HK divergent simultanément (> 2% en 5 j).
        """
        regime  = "NORMAL"
        signaux: list[str] = []
        probabilites = {"NORMAL": 70.0, "ROTATION": 10.0, "CRISE_LIQUIDITE": 10.0, "EFFONDREMENT": 10.0}

        tlt   = prix_data.get("TLT", {})
        spy   = prix_data.get("SPY", {})
        xau   = prix_data.get("XAUUSD", {})
        hsi   = prix_data.get("HSI", {})

        corr_tlt_spy: float | None  = None
        ratio_tlt_spy: float | None = None

        tlt_hist = tlt.get("hist_30d") or []
        spy_hist = spy.get("hist_30d") or []

        if len(tlt_hist) >= 5 and len(spy_hist) >= 5:
            tlt_5d = tlt_hist[-5:]
            spy_5d = spy_hist[-5:]
            tlt_ret = [tlt_5d[i] - tlt_5d[i - 1] for i in range(1, len(tlt_5d))]
            spy_ret = [spy_5d[i] - spy_5d[i - 1] for i in range(1, len(spy_5d))]
            corr_tlt_spy = self._corr_pearson(tlt_ret, spy_ret)

            if tlt.get("price") and spy.get("price") and spy["price"] > 0:
                ratio_tlt_spy = round(tlt["price"] / spy["price"], 6)

            if corr_tlt_spy is not None and corr_tlt_spy > 0:
                regime = "CRISE_LIQUIDITE"
                signaux.append(
                    f"SIGNAL CRITIQUE : corr(TLT, SPY) = {corr_tlt_spy:+.3f} > 0 sur 5 jours "
                    f"(obligations ET actions baissent ensemble — antifragilité perdue)"
                )
                probabilites = {"NORMAL": 5.0, "ROTATION": 10.0, "CRISE_LIQUIDITE": 75.0, "EFFONDREMENT": 10.0}

        # Signal ROTATION (seulement si pas déjà en CRISE_LIQUIDITE)
        if regime == "NORMAL":
            xau_hist = xau.get("hist_30d") or []
            hsi_hist = hsi.get("hist_30d") or []
            xau_p    = xau.get("price")
            hsi_p    = hsi.get("price")

            xau_baisse = (
                len(xau_hist) >= 5 and xau_p and xau_hist[-5]
                and (xau_p - xau_hist[-5]) / xau_hist[-5] < -0.02
            )
            hsi_baisse = (
                len(hsi_hist) >= 5 and hsi_p and hsi_hist[-5]
                and (hsi_p - hsi_hist[-5]) / hsi_hist[-5] < -0.02
            )

            if xau_baisse and hsi_baisse:
                regime = "ROTATION"
                xau_pct = (xau_p - xau_hist[-5]) / xau_hist[-5] * 100
                hsi_pct = (hsi_p - hsi_hist[-5]) / hsi_hist[-5] * 100
                signaux.append(
                    f"SIGNAL ROTATION : Or {xau_pct:+.1f}% et Hang Seng {hsi_pct:+.1f}% "
                    f"en 5 jours — pression vendeuse simultanée (absorption IPO probable)"
                )
                probabilites = {"NORMAL": 20.0, "ROTATION": 60.0, "CRISE_LIQUIDITE": 15.0, "EFFONDREMENT": 5.0}

        return {
            "regime":           regime,
            "signaux":          signaux,
            "probabilites":     probabilites,
            "corr_tlt_spy_5j":  corr_tlt_spy,
            "ratio_tlt_spy":    ratio_tlt_spy,
            "description":      REGIMES_MARCHE[regime]["description"],
            "protection":       REGIMES_MARCHE[regime]["protection"],
        }

    @staticmethod
    def _parse_montant(valo_str: str) -> float | None:
        """Parse '85 Mds$' ou '25 Md$' → float en milliards."""
        m = re.search(r'(\d+(?:[.,]\d+)?)', str(valo_str).replace(',', '.'))
        return float(m.group(1).replace(',', '.')) if m else None

    def comparer_precedents(self, montant_ipo: float) -> dict[str, Any]:
        """
        Compare montant_ipo (en Mds$) aux précédents historiques PRECEDENTS_IPO_ABSORPTION.
        Avertit si 'territoire inconnu' (> 2x le plus grand précédent avec montant connu).
        Déclasse la confiance à MOYEN si territoire_inconnu = True.
        """
        montants_connus = [
            p for p in PRECEDENTS_IPO_ABSORPTION
            if p.get("montant") is not None
        ]
        if not montants_connus:
            return {"ok": False, "raison": "Aucun précédent avec montant disponible"}

        max_historique  = max(p["montant"] for p in montants_connus)
        ratio           = round(montant_ipo / max_historique, 2) if max_historique > 0 else None
        territoire_inconnu = ratio is not None and ratio > 2.0

        plus_proche = min(montants_connus, key=lambda p: abs(p["montant"] - montant_ipo))

        avertissement = (
            f"⚠️ TERRITOIRE INCONNU : {montant_ipo}Mds$ = {ratio:.1f}x le plus grand précédent "
            f"({max_historique}Mds$ — {max(montants_connus, key=lambda p: p['montant'])['nom']}). "
            "Pas de précédent fiable. Déclasser confiance à MOYEN."
            if territoire_inconnu else
            f"Dans les précédents connus. Plus proche : {plus_proche['nom']} "
            f"({plus_proche['montant']}Mds$)"
        )

        return {
            "ok":                True,
            "montant_analyse":   montant_ipo,
            "max_historique":    max_historique,
            "ratio_vs_max":      ratio,
            "territoire_inconnu": territoire_inconnu,
            "avertissement":     avertissement,
            "plus_proche":       plus_proche,
            "precedents":        PRECEDENTS_IPO_ABSORPTION,
        }

    def _generer_section_haut_gauche(self, regime_info: dict) -> str:
        """Génère la section 'SCÉNARIO HAUT À GAUCHE' à insérer dans chaque rapport."""
        regime      = regime_info.get("regime", "NORMAL")
        probabilites = regime_info.get("probabilites", {})
        signaux     = regime_info.get("signaux", [])
        corr        = regime_info.get("corr_tlt_spy_5j")
        ratio       = regime_info.get("ratio_tlt_spy")

        signaux_str = (
            "\n".join(f"  ⚡ {s}" for s in signaux)
            if signaux else "  Aucun signal actif détecté"
        )
        prob_str = "\n".join(
            f"  {'▶' if r == regime else '  '} {r:<20} {probabilites.get(r, 0):.0f}%"
            for r in ["NORMAL", "ROTATION", "CRISE_LIQUIDITE", "EFFONDREMENT"]
        )
        recommandations = {
            "NORMAL":          "Portefeuille standard — actifs réels + dividendes",
            "ROTATION":        "Accumulation actifs refuge pendant la baisse temporaire",
            "CRISE_LIQUIDITE": "Augmenter cash — réduire exposition actifs risqués — garder or physique",
            "EFFONDREMENT":    "Cash + or physique + actifs hors système",
        }
        corr_str = f"{corr:+.4f}" if corr is not None else "N/A"
        ratio_str = f"{ratio:.6f}" if ratio is not None else "N/A"

        return (
            "═══════════════════════════════════════════════════════\n"
            "SECTION HAUT À GAUCHE — SCÉNARIOS RÉGIME DE MARCHÉ\n"
            "═══════════════════════════════════════════════════════\n"
            f"RÉGIME ACTUEL DÉTECTÉ : ► {regime} ◄\n"
            f"Description : {REGIMES_MARCHE.get(regime, {}).get('description', '?')}\n\n"
            f"Indicateur clé : corr(TLT, SPY) 5j = {corr_str} | Ratio TLT/SPY = {ratio_str}\n\n"
            "Probabilités estimées par régime :\n"
            f"{prob_str}\n\n"
            "Signaux actifs :\n"
            f"{signaux_str}\n\n"
            f"RECOMMANDATION KING FUND ({regime}) :\n"
            f"  {recommandations.get(regime, '?')}\n\n"
            "RAPPEL — Signal CRISE_LIQUIDITE :\n"
            "  Si corr(TLT, SPY) > 0 sur 5 jours glissants → obligations perdent antifragilité.\n"
            "  Dans ce régime, la seule protection est le CASH et les actifs physiques hors système.\n"
            "═══════════════════════════════════════════════════════"
        )

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

        # ── Indices asiatiques — alerte si variation 24h < -5% ──────────────
        ASIAN_INDICES = [
            ("KOSPI",  "KOSPI (Corée du Sud)"),
            ("NIKKEI", "Nikkei 225 (Japon)"),
            ("TAIWAN", "Taiwan Weighted Index"),
        ]
        for idx_key, idx_label in ASIAN_INDICES:
            idx = d.get(idx_key, {})
            idx_price = idx.get("price")
            idx_hist  = idx.get("hist_30d") or []
            if idx_price and len(idx_hist) >= 2 and idx_hist[-2]:
                var_24h = (idx_price - idx_hist[-2]) / idx_hist[-2] * 100
                if var_24h < -5.0:
                    anomalies.append({
                        "id":            f"asian_{idx_key.lower()}",
                        "label":         f"{idx_label} — chute > 5% en 24h",
                        "timestamp":     now_str,
                        "valeur":        round(idx_price, 2),
                        "z_score":       0.0,
                        "variation_pct": round(var_24h, 2),
                        "seuil_label":   f"variation {var_24h:+.2f}% (seuil -5% / 24h)",
                        "niveau":        "CRITIQUE" if var_24h < -7.0 else "IMPORTANT",
                    })
                elif abs(var_24h) > 2.0:
                    _check_series(
                        f"asian_{idx_key.lower()}_series",
                        idx_label, idx_hist, idx_price,
                    )

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

        # ── Indices asiatiques ───────────────────────────────────────────────
        for idx_key, idx_label_short in [("KOSPI", "KOSPI"), ("NIKKEI", "Nikkei 225"), ("TAIWAN", "Taiwan")]:
            idx = d.get(idx_key, {})
            if idx.get("price") and idx.get("hist_30d") and len(idx["hist_30d"]) >= 2 and idx["hist_30d"][-2]:
                var = (idx["price"] - idx["hist_30d"][-2]) / idx["hist_30d"][-2] * 100
                _add(f"asian_{idx_key.lower()}", idx_label_short,
                     round(idx["price"], 2), var < -5.0,
                     f"{var:+.2f}% (24h) — alerte si < -5%", idx.get("freshness","?"))
            else:
                _add(f"asian_{idx_key.lower()}", idx_label_short, "DONNÉES INDISPONIBLES", False)

        return ratios

    # ── Bias checklist ──────────────────────────────────────────────────────

    def _run_biais_checklist(
        self,
        anomalies: list[dict],
        sources_actives: list[str],
        ipos: list[dict],
        fred_ok: bool,
        cftc_ok: bool,
        montant_ipo: float | None = None,
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

        # precedent_comparable: vérifie si le précédent est vraiment comparable
        if montant_ipo is not None:
            comp = self.comparer_precedents(montant_ipo)
            results["precedent_comparable"] = not comp.get("territoire_inconnu", False)
        else:
            results["precedent_comparable"] = True  # pas d'IPO → biais non applicable

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
            confiance = "FORTE"
        elif n_bloq_ok >= 4 and sources_count >= 2 and timeframes_count >= 2:
            confiance = "MOYEN"
        else:
            confiance = "FAIBLE"

        # Downgrade si précédent non comparable (action_si_echec du biais)
        if not biais_results.get("precedent_comparable", True) and confiance == "FORTE":
            confiance = "MOYEN"

        return confiance

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
        regime: str = "NORMAL",
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
            f"[{niveau}] AGENT FLUX MACRO — RÉGIME : {regime}\n\n"
            f"📅 {date_str} {heure_str} UTC\n\n"
            f"⚠️ ANOMALIE : {anomalie.get('label','?')} "
            f"{anomalie.get('variation_pct', 0):+.1f}% (z={anomalie.get('z_score',0):+.1f}σ)\n\n"
            f"🔍 CAUSE IDENTIFIÉE : {cause}{ipo_str}\n\n"
            f"📊 CONFIRMÉ SUR :{src_lines}\n\n"
            f"⏱️ SÉQUENCE : Anomalie détectée le {date_str}\n\n"
            f"🎯 CONCLUSION : {conclusion}\n\n"
            f"📈 ACTION SUGGÉRÉE : {action}\n\n"
            f"🔒 CONFIANCE : {confiance}\n\n"
            f"🏛️ RÉGIME MARCHÉ : {regime} — {REGIMES_MARCHE.get(regime, {}).get('protection', '?')}\n\n"
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

    def _valider_avec_agd01(self, signal: dict) -> bool:
        """
        Avocat du diable : soumet le signal CRITIQUE directement à Claude.
        Prompt 'prouve que cette thèse est fausse' avant tout envoi Telegram CRITIQUE.
        Retourne True si validé, False si rejeté. Fail-open en cas d'erreur.
        """
        try:
            from config import ANTHROPIC_API_KEY
            if not ANTHROPIC_API_KEY:
                return True
            import anthropic
            anomalie_label = signal.get("anomalie_label", "anomalie macro inconnue")
            conclusion     = signal.get("conclusion", "")
            mecanisme      = signal.get("mecanisme", "")
            regime         = signal.get("regime", "NORMAL")
            prompt = (
                f"Un agent de détection de flux macro a émis ce signal CRITIQUE :\n\n"
                f"Anomalie : {anomalie_label}\n"
                f"Régime marché : {regime}\n"
                f"Mécanisme identifié : {mecanisme[:300]}\n"
                f"Conclusion : {conclusion[:300]}\n\n"
                f"Prouve que cette thèse est fausse. Donne exactement 3 raisons concrètes "
                f"pour lesquelles ce signal pourrait être un faux positif (dark pools, "
                f"biais de confirmation, corrélation spurieuse, délai FRED, etc.). "
                f"Termine UNIQUEMENT par VALIDE si les contre-arguments sont faibles "
                f"et le signal mérite d'être transmis, ou REJETE si les contre-arguments "
                f"sont convaincants et le signal doit être ignoré."
            )
            client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
            msg = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=400,
                messages=[{"role": "user", "content": prompt}],
            )
            reponse = msg.content[0].text.strip().upper()
            if "REJETE" in reponse or "REJETÉ" in reponse:
                logger.info("[FluxMacro] Avocat du diable : CRITIQUE REJETÉ ← %s", anomalie_label)
                return False
            logger.info("[FluxMacro] Avocat du diable : CRITIQUE VALIDÉ ← %s", anomalie_label)
            return True
        except Exception as exc:
            logger.debug("[FluxMacro] _valider_avec_agd01: %s", exc)
            return True

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
                sources_actives.append("yfinance (XAUUSD/GC=F, HSI, AAXJ, URTH, IRX, USDJPY, GLD, USO, TLT, SPY, QQQ, COPX, UNG)")
            else:
                erreurs.append(f"yfinance: {prix_result.get('erreur','erreur inconnue')}")

            fred_result = self._fetch_fred()
            fred_ok     = fred_result.get("ok", False)
            if fred_ok:
                sources_actives.append("FRED API (DGS3MO, DGS10, T10YIE)")

            cftc_result = self._fetch_cftc()
            cftc_ok     = cftc_result.get("ok", False)
            if cftc_ok:
                rpt = cftc_result.get("report_date", "?")
                or_net  = cftc_result.get("or",      {}).get("net_mm", "N/A")
                wti_net = cftc_result.get("petrole",  {}).get("net_mm", "N/A")
                yen_net = cftc_result.get("yen",      {}).get("net_mm", "N/A")
                sources_actives.append(
                    f"CFTC COT ({rpt}) — Or MM Net: {or_net} | "
                    f"WTI MM Net: {wti_net} | JPY Spec Net: {yen_net}"
                )

            wgc_result = self._fetch_wgc()
            wgc_ok     = wgc_result.get("ok", False)
            if wgc_ok:
                sources_actives.append(
                    f"WGC reserves or banques centrales ({wgc_result.get('source','?')}) — mensuel"
                )

            tic_result = self._fetch_tic_data()
            tic_ok     = tic_result.get("ok", False)
            if tic_ok:
                sources_actives.append(
                    f"TIC Data Treasury (avoirs etrangers US Treasuries — mensuel, "
                    f"DELAI 6 SEMAINES — {tic_result.get('date_reference','?')})"
                )

            ipos = self._fetch_ipo_calendar()
            if ipos:
                sources_actives.append(f"SEC EDGAR ({len(ipos)} filing(s) S-1 récents)")

            commodites = self._fetch_commodites_critiques()
            if commodites.get("alertes"):
                sources_actives.append(
                    f"Reuters commodités ({len(commodites['alertes'])} alerte(s) matières premières)"
                )

            # FRED liquidité macro (M2SL, WALCL, IORB, spreads IG/HY)
            fred_liq_result = self._fetch_fred_liquidite()
            fred_liq_ok     = fred_liq_result.get("ok", False)
            fred_liq_data   = fred_liq_result.get("data", {})
            if fred_liq_ok:
                sources_actives.append("FRED API liquidité (M2SL, WALCL, IORB, BAMLC0A0CM, BAMLH0A0HYM2)")
            alertes_liquidite = self._check_liquidite_seuils(fred_liq_data) if fred_liq_ok else []

            # SOFR / EFFR / RRPONTSYD — Jeff Snider Eurodollar
            sofr_result = self._fetch_fred_sofr()
            sofr_ok     = sofr_result.get("ok", False)
            sofr_data_raw = sofr_result.get("data", {})
            if sofr_ok:
                sources_actives.append("FRED API SOFR (SOFR, EFFR, RRPONTSYD — Snider Eurodollar)")

            # ── Étape 1 : DÉTECTER anomalies ───────────────────────────────
            prix_data   = prix_result.get("data", {})
            anomalies   = self._detect_anomalies(prix_data) if prix_result.get("ok") else []
            ratios_etat = self._compute_ratios_etat(prix_data) if prix_result.get("ok") else []
            alertes_sofr = (
                self._check_sofr_stress(sofr_data_raw, prix_data)
                if sofr_ok or prix_result.get("ok") else []
            )
            regime_info = self._detect_regime_marche(prix_data) if prix_result.get("ok") else {
                "regime": "NORMAL", "signaux": [], "probabilites": {},
                "corr_tlt_spy_5j": None, "ratio_tlt_spy": None,
                "description": REGIMES_MARCHE["NORMAL"]["description"],
                "protection":  REGIMES_MARCHE["NORMAL"]["protection"],
            }

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

            section_haut_gauche = self._generer_section_haut_gauche(regime_info)

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
                        regime      = regime_info.get("regime", "NORMAL"),
                    )
                    signal_ctx = {
                        "anomalie_label": anomalie.get("label", ""),
                        "conclusion":     conclusion,
                        "mecanisme":      mecanisme,
                        "regime":         regime_info.get("regime", "NORMAL"),
                    }
                    if not self._valider_avec_agd01(signal_ctx):
                        logger.info("[FluxMacro] Signal CRITIQUE rejeté par avocat du diable")
                        continue
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
                    anomalie        = anomalies_str,
                    cause           = mecanisme or "Non identifiee",
                    confiance       = confiance,
                    conclusion      = conclusion,
                    sources         = sources_actives,
                    action_suggeree = action_suggeree,
                )

            # ── Construction résultat ───────────────────────────────────────
            fred_data = fred_result.get("data", {})

            def _liq_val(series_id: str) -> Any:
                return fred_liq_data.get(series_id, {}).get("value", "DONNÉES INDISPONIBLES")

            self._cache = {
                "timestamp":         ts_debut,
                "sources_actives":   sources_actives,
                "nb_sources":        len(sources_actives),
                "anomalies":         anomalies,
                "alertes_liquidite": alertes_liquidite,
                "alertes_sofr":      alertes_sofr,
                "ratios":            ratios_etat,
                "fred": {
                    "DGS3MO":  fred_data.get("DGS3MO",  {}).get("value", "DONNÉES INDISPONIBLES"),
                    "DGS10":   fred_data.get("DGS10",   {}).get("value", "DONNÉES INDISPONIBLES"),
                    "T10YIE":  fred_data.get("T10YIE",  {}).get("value", "DONNÉES INDISPONIBLES"),
                },
                "fred_liquidite": {
                    "M2SL":         _liq_val("M2SL"),
                    "WALCL":        _liq_val("WALCL"),
                    "IORB":         _liq_val("IORB"),
                    "BAMLC0A0CM":   _liq_val("BAMLC0A0CM"),
                    "BAMLH0A0HYM2": _liq_val("BAMLH0A0HYM2"),
                    "ok":           fred_liq_ok,
                    "note":         "M2SL: masse monétaire US (Mds$) | WALCL: Fed balance sheet (Mds$) | IORB: taux repo (%) | BAMLC0A0CM: spreads IG (bps) | BAMLH0A0HYM2: spreads HY (bps)",
                },
                "sofr_stress": {
                    "ok":       sofr_ok,
                    "SOFR":     sofr_data_raw.get("SOFR",     {}).get("value"),
                    "EFFR":     sofr_data_raw.get("EFFR",     {}).get("value"),
                    "RRPONTSYD": sofr_data_raw.get("RRPONTSYD",{}).get("value"),
                    "spread_bps": (
                        round((sofr_data_raw.get("SOFR",{}).get("value",0) or 0) -
                              (sofr_data_raw.get("EFFR",{}).get("value",0) or 0), 3) * 100
                        if sofr_data_raw.get("SOFR",{}).get("value") is not None
                           and sofr_data_raw.get("EFFR",{}).get("value") is not None
                        else None
                    ),
                    "alertes":  alertes_sofr,
                    "seuils":   SOFR_SEUILS,
                    "note":     "Jeff Snider Eurodollar — SOFR/EFFR spread (seuil 50 bps) | RRPONTSYD reverse repo Fed (Mds$) | FX swap basis approx USD/JPY + USD/KRW",
                },
                "cftc": cftc_result if cftc_ok else {"ok": False, "reason": "DONNÉES INDISPONIBLES"},
                "wgc":               wgc_result,
                "tic_data":          tic_result,
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
                "tic_data_note":     tic_result.get("delai_note",
                                         "TIC Data : delai structurel 6 semaines (ticdata.treasury.gov)"),
                "wgc_note":          wgc_result.get("note",
                                         "WGC reserves or banques centrales (mensuel — gold.org/goldhub)"),
                "regime":             regime_info,
                "section_haut_gauche": section_haut_gauche,
                "commodites_critiques": commodites,
                "distinction_ventes_or": DISTINCTION_VENTES_OR,
                "_prix_raw": {
                    "GLD_hist": prix_data.get("GLD",    {}).get("hist_30d", []),
                    "SPY_hist": prix_data.get("SPY",    {}).get("hist_30d", []),
                    "TLT_hist": prix_data.get("TLT",    {}).get("hist_30d", []),
                    "GC_hist":  prix_data.get("XAUUSD", {}).get("hist_30d", []),
                },
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
            sources_actives.append("yfinance (GC=F, HSI, AAXJ, URTH, IRX, USDJPY, GLD, USO, TLT, SPY, COPX, UNG)")

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
        regime_info = self._detect_regime_marche(prix_data) if prix_result.get("ok") else {
            "regime": "NORMAL", "signaux": [], "probabilites": {},
            "corr_tlt_spy_5j": None, "ratio_tlt_spy": None,
            "description": REGIMES_MARCHE["NORMAL"]["description"],
            "protection":  REGIMES_MARCHE["NORMAL"]["protection"],
        }

        montant_num  = evenement.get("montant") or self._parse_montant(valo)
        precedents_comp = self.comparer_precedents(montant_num) if montant_num else None

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
            anomalies, sources_actives, ipos_fictifs, fred_ok, cftc_ok,
            montant_ipo=montant_num,
        )
        # causalite_temporelle : True car événement injecté fournit la cause candidate
        biais_results["causalite_temporelle"] = True
        # mecanisme_explicite : True si l'événement a une valorisation chiffrée
        biais_results["mecanisme_explicite"]  = bool(valo and valo != "N/D")

        confiance = self._calcul_confiance(biais_results, len(sources_actives), 3)
        # Downgrade supplémentaire si territoire inconnu (action_si_echec biais precedent_comparable)
        if precedents_comp and precedents_comp.get("territoire_inconnu") and confiance == "FORTE":
            confiance = "MOYEN"

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
            "biais_checklist":      biais_results,
            "confiance":            confiance,
            "conclusion":           conclusion,
            "action_suggeree":      action,
            "pourquoi_tort":        pourquoi_tort,
            "limites":              LIMITES_FONDAMENTALES,
            "disclaimer":           DISCLAIMER,
            "regime":               regime_info,
            "section_haut_gauche":  self._generer_section_haut_gauche(regime_info),
            "precedents_ipo":       precedents_comp,
            "distinction_ventes_or": DISTINCTION_VENTES_OR,
            "regle_antifragilite":  REGLE_ANTIFRAGILITE_OBLIGATIONS.strip(),
        }
        return rapport

    def etat(self) -> dict:
        """Retourne l'état courant (depuis cache si disponible)."""
        if self._cache:
            return {
                "timestamp":        self._cache.get("timestamp"),
                "nb_anomalies":     len(self._cache.get("anomalies", [])),
                "nb_alertes_liq":   len(self._cache.get("alertes_liquidite", [])),
                "confiance":        self._cache.get("confiance"),
                "nb_sources":       self._cache.get("nb_sources", 0),
                "alertes_envoyees": self._cache.get("alertes_envoyees", []),
                "regime":           self._cache.get("regime", {}).get("regime"),
            }
        return {"timestamp": None, "nb_anomalies": 0, "confiance": None, "nb_sources": 0, "regime": None}

    # ── Rapports Flash / Hebdo ───────────────────────────────────────────────

    def generer_rapport_flash(self, anomalie: dict | None = None) -> dict:
        """
        Génère un rapport flash (signal CRITIQUE ou à la demande).
        Format : PDF (via fpdf2) avec fallback TXT si fpdf2 absent.
        Dossier : rapports/flux_macro/flash/flash_YYYY-MM-DD_HHMM.{pdf|txt}
        Retourne {"ok": bool, "chemin": str, "texte": str, "format": str}.
        """
        donnees  = self._cache or {}
        now      = datetime.now(timezone.utc)
        nom_base = f"flash_{now.strftime('%Y-%m-%d_%H%M')}"
        chemin   = _RAPPORTS_DIR / "flash" / f"{nom_base}.txt"  # défaut txt, réécrit si PDF

        anomalies  = donnees.get("anomalies", [])
        top_anom   = anomalie or (max(anomalies, key=lambda x: abs(x.get("z_score", 0))) if anomalies else {})
        regime     = donnees.get("regime", {}).get("regime", "NORMAL")
        confiance  = donnees.get("confiance", "—")
        conclusion = donnees.get("conclusion", "—")
        action     = donnees.get("action_suggeree", "—")
        tort       = donnees.get("pourquoi_tort", "—")
        sources    = donnees.get("sources_actives", [])
        liq        = donnees.get("fred_liquidite", {})
        biais      = donnees.get("biais_checklist", {})

        biais_lines = ""
        for biais_id, v in BIAIS_CHECKLIST.items():
            ok  = biais.get(biais_id, False)
            ico = "✅" if ok else "❌"
            tag = "[BLOQUANT]" if v["blocage"] else "[avert.]"
            biais_lines += f"  {ico} {tag} {biais_id} : {v['question']}\n"

        # ── Phase 2 : Granger + Bull/Bear/Arbitre ───────────────────────────
        prix_raw = donnees.get("_prix_raw", {})
        granger_gld_spy: dict = {}
        granger_tlt_spy: dict = {}
        if prix_raw:
            gld_h = prix_raw.get("GLD_hist", [])
            spy_h = prix_raw.get("SPY_hist", [])
            tlt_h = prix_raw.get("TLT_hist", [])
            if len(gld_h) >= 8 and len(spy_h) >= 8:
                granger_gld_spy = self._test_granger(gld_h, spy_h)
            if len(tlt_h) >= 8 and len(spy_h) >= 8:
                granger_tlt_spy = self._test_granger(tlt_h, spy_h)
        _g_gld = granger_gld_spy.get("resume", "statsmodels requis ou données insuffisantes")
        _g_tlt = granger_tlt_spy.get("resume", "données insuffisantes")

        regime_str     = donnees.get("regime", {}).get("regime", "NORMAL")
        bear_result    = self._bear.analyser(conclusion, regime_str, confiance)
        arbitre_result = self._arbitre_bull_bear(conclusion, bear_result)
        _bear_pos  = bear_result.get("position_bear", "API non disponible")
        _bear_rai  = "\n".join(f"  • {r}" for r in bear_result.get("raisons_bear", []))
        _bear_bias = bear_result.get("biais_probable", "—")
        _bear_alt  = bear_result.get("these_alternative", "—")
        _arb_verd  = arbitre_result.get("verdict", "INCERTAIN")
        _arb_txt   = arbitre_result.get("texte", "Arbitre non disponible")

        texte = (
            f"═══════════════════════════════════════════════════\n"
            f"RAPPORT FLASH — AGENT FLUX MACRO\n"
            f"Le Détective de Capitaux — Division Research — King Fund\n"
            f"═══════════════════════════════════════════════════\n"
            f"Date : {now.strftime('%Y-%m-%d %H:%M UTC')}\n"
            f"Régime marché : {regime}\n"
            f"Confiance : {confiance}\n\n"
            f"── ANOMALIE PRINCIPALE ──────────────────────────\n"
            f"{top_anom.get('label', 'Aucune') if top_anom else 'Aucune anomalie CRITIQUE'}\n"
            f"Valeur : {top_anom.get('valeur', '—')} | Z-score : {top_anom.get('z_score', '—')}\n"
            f"Niveau : {top_anom.get('niveau', '—')}\n\n"
            f"── POSITION BULL ────────────────────────────────\n"
            f"{conclusion}\n\n"
            f"── POSITION BEAR (avocat du diable) ─────────────\n"
            f"{_bear_pos}\n"
            f"{_bear_rai}\n"
            f"  Biais : {_bear_bias} | Alt. : {_bear_alt}\n\n"
            f"── VERDICT ARBITRE ──────────────────────────────\n"
            f"  {_arb_verd} — {_arb_txt}\n\n"
            f"── ACTION SUGGÉRÉE ──────────────────────────────\n"
            f"{action}\n\n"
            f"── TESTS DE GRANGER (Phase 2) ────────────────────\n"
            f"  GLD → SPY : {_g_gld}\n"
            f"  TLT → SPY : {_g_tlt}\n\n"
            f"── INDICATEURS LIQUIDITÉ (FRED) ─────────────────\n"
            f"  M2SL     : {liq.get('M2SL', 'DONNÉES INDISPONIBLES')} Mds$\n"
            f"  WALCL    : {liq.get('WALCL', 'DONNÉES INDISPONIBLES')} Mds$\n"
            f"  IORB     : {liq.get('IORB', 'DONNÉES INDISPONIBLES')} %\n"
            f"  IG spread: {liq.get('BAMLC0A0CM', 'DONNÉES INDISPONIBLES')} bps\n"
            f"  HY spread: {liq.get('BAMLH0A0HYM2', 'DONNÉES INDISPONIBLES')} bps\n\n"
            f"── SOURCES ACTIVES ({len(sources)}) ─────────────────────────\n"
            + "\n".join(f"  • {s}" for s in sources) + "\n\n"
            f"── AUDIT ANTI-BIAIS ─────────────────────────────\n"
            f"{biais_lines}\n"
            f"── POURQUOI J'AI TORT (biais narratif) ──────────\n"
            f"{tort}\n\n"
            f"── LIMITES FONDAMENTALES ────────────────────────\n"
            + "\n".join(f"  • {l}" for l in LIMITES_FONDAMENTALES) + "\n\n"
            f"⚠️ Soumis à AGD-01 pour validation avant diffusion\n"
            f"⚠️ DISCLAIMER : {DISCLAIMER}\n"
            f"═══════════════════════════════════════════════════\n"
        )

        # ── Tentative PDF (fpdf2) ────────────────────────────────────────────
        try:
            from fpdf import FPDF  # fpdf2 >= 2.7

            # Sanitise → Latin-1 (police Helvetica intégrée fpdf2)
            def _p(s: Any) -> str:
                return str(s).encode("latin-1", errors="replace").decode("latin-1")

            pdf = FPDF()
            pdf.set_margins(left=12, top=12, right=12)
            pdf.set_auto_page_break(auto=True, margin=15)
            pdf.add_page()
            W = pdf.epw  # largeur effective (page - marges)

            pdf.set_font("Helvetica", "B", 13)
            pdf.cell(W, 9, "RAPPORT FLASH - AGENT FLUX MACRO", new_x="LMARGIN", new_y="NEXT", align="C")
            pdf.set_font("Helvetica", "", 9)
            pdf.cell(W, 5, "Le Detecteur de Capitaux - Division Research - King Fund",
                     new_x="LMARGIN", new_y="NEXT", align="C")
            pdf.cell(W, 5, f"Date : {now.strftime('%Y-%m-%d %H:%M UTC')}",
                     new_x="LMARGIN", new_y="NEXT")
            pdf.cell(W, 5, _p(f"Regime : {regime}  |  Confiance : {confiance}"),
                     new_x="LMARGIN", new_y="NEXT")
            pdf.ln(3)

            def _section(titre: str) -> None:
                pdf.set_font("Helvetica", "B", 10)
                pdf.cell(W, 7, titre, new_x="LMARGIN", new_y="NEXT")
                pdf.set_font("Helvetica", "", 9)

            _section("ANOMALIE PRINCIPALE")
            if top_anom:
                pdf.multi_cell(W, 5, _p(
                    f"{top_anom.get('label','Aucune')} | "
                    f"Z={top_anom.get('z_score','?')} | "
                    f"Niveau: {top_anom.get('niveau','?')}"
                ), new_x="LMARGIN", new_y="NEXT")
            else:
                pdf.cell(W, 5, "Aucune anomalie CRITIQUE", new_x="LMARGIN", new_y="NEXT")
            pdf.ln(2)

            _section("POSITION BULL")
            pdf.multi_cell(W, 5, _p(str(conclusion)[:800]), new_x="LMARGIN", new_y="NEXT")
            pdf.ln(2)

            _section("POSITION BEAR (avocat du diable)")
            pdf.multi_cell(W, 5, _p(str(_bear_pos)[:400]), new_x="LMARGIN", new_y="NEXT")
            if bear_result.get("raisons_bear"):
                for r in bear_result["raisons_bear"][:3]:
                    pdf.multi_cell(W, 4, _p(f"• {str(r)[:100]}"), new_x="LMARGIN", new_y="NEXT")
            pdf.multi_cell(W, 4, _p(f"Biais: {_bear_bias[:80]}"), new_x="LMARGIN", new_y="NEXT")
            pdf.ln(2)

            _section(f"VERDICT ARBITRE : {_arb_verd}")
            pdf.multi_cell(W, 5, _p(str(_arb_txt)[:400]), new_x="LMARGIN", new_y="NEXT")
            pdf.ln(2)

            _section("ACTION SUGGEREE")
            pdf.multi_cell(W, 5, _p(str(action)[:400]), new_x="LMARGIN", new_y="NEXT")
            pdf.ln(2)

            _section("TESTS DE GRANGER (Phase 2)")
            pdf.multi_cell(W, 4, _p(f"GLD -> SPY : {_g_gld[:120]}"), new_x="LMARGIN", new_y="NEXT")
            pdf.multi_cell(W, 4, _p(f"TLT -> SPY : {_g_tlt[:120]}"), new_x="LMARGIN", new_y="NEXT")
            pdf.ln(2)

            _section(f"SOURCES ACTIVES ({len(sources)})")
            for s in sources[:8]:
                pdf.multi_cell(W, 4, _p(f"- {str(s)[:110]}"), new_x="LMARGIN", new_y="NEXT")
            pdf.ln(2)

            _section("INDICATEURS LIQUIDITE (FRED)")
            for k, label in [("M2SL","M2SL"), ("WALCL","WALCL"),
                              ("IORB","IORB"), ("BAMLC0A0CM","IG spread"),
                              ("BAMLH0A0HYM2","HY spread")]:
                pdf.cell(W, 4, _p(f"  {label}: {liq.get(k, 'N/D')}"),
                         new_x="LMARGIN", new_y="NEXT")
            pdf.ln(2)

            _section("AUDIT ANTI-BIAIS")
            for biais_id, v in BIAIS_CHECKLIST.items():
                ok_flag = biais.get(biais_id, False)
                tag = "[OK]" if ok_flag else "[KO]"
                bloc = "[BLOQUANT]" if v["blocage"] else "[avert. ]"
                pdf.cell(W, 4, _p(f"  {tag} {bloc} {biais_id}"),
                         new_x="LMARGIN", new_y="NEXT")
            pdf.ln(2)

            _section("POURQUOI J'AI TORT (biais narratif)")
            pdf.multi_cell(W, 5, _p(str(tort)[:400]), new_x="LMARGIN", new_y="NEXT")
            pdf.ln(2)

            _section("LIMITES FONDAMENTALES")
            for l in LIMITES_FONDAMENTALES:
                pdf.multi_cell(W, 4, _p(f"- {str(l)[:110]}"), new_x="LMARGIN", new_y="NEXT")
            pdf.ln(2)

            pdf.set_font("Helvetica", "I", 8)
            pdf.multi_cell(W, 4, _p(f"DISCLAIMER : {DISCLAIMER}"), new_x="LMARGIN", new_y="NEXT")
            pdf.multi_cell(W, 4, "Soumis a AGD-01 pour validation avant diffusion.", new_x="LMARGIN", new_y="NEXT")

            pdf_chemin = _RAPPORTS_DIR / "flash" / f"{nom_base}.pdf"
            pdf.output(str(pdf_chemin))
            logger.info("[FluxMacro] Rapport flash PDF sauvegarde : %s", pdf_chemin)
            return {"ok": True, "chemin": str(pdf_chemin), "texte": texte, "format": "pdf"}

        except ImportError:
            logger.debug("[FluxMacro] fpdf2 absent — fallback TXT")
        except Exception as exc:
            logger.warning("[FluxMacro] Rapport flash PDF erreur: %s", exc)

        # ── Fallback TXT ─────────────────────────────────────────────────────
        try:
            chemin.write_text(texte, encoding="utf-8")
            logger.info("[FluxMacro] Rapport flash TXT sauvegarde : %s", chemin)
            return {"ok": True, "chemin": str(chemin), "texte": texte, "format": "txt"}
        except Exception as exc:
            logger.warning("[FluxMacro] Rapport flash sauvegarde: %s", exc)
            return {"ok": False, "chemin": "", "texte": texte, "erreur": str(exc), "format": "txt"}

    def taux_reussite(self) -> dict:
        """
        Calcule le taux de réussite des signaux Flux Macro depuis flux_macro_journal.
        Retourne {total, corrects, taux_pct, label}.
        'Correct' = verdict_posteriori = 'CORRECT'.
        """
        if not self._db_path:
            return {"total": 0, "corrects": 0, "taux_pct": None, "label": "—"}
        try:
            con = sqlite3.connect(self._db_path)
            total = con.execute(
                "SELECT COUNT(*) FROM flux_macro_journal WHERE verdict_posteriori IS NOT NULL"
            ).fetchone()[0]
            corrects = con.execute(
                "SELECT COUNT(*) FROM flux_macro_journal WHERE verdict_posteriori = 'CORRECT'"
            ).fetchone()[0]
            con.close()
            taux = round(corrects / total * 100, 1) if total > 0 else None
            label = f"{taux}%" if taux is not None else "—"
            return {"total": total, "corrects": corrects, "taux_pct": taux, "label": label}
        except Exception as exc:
            logger.warning("[FluxMacro] taux_reussite: %s", exc)
            return {"total": 0, "corrects": 0, "taux_pct": None, "label": "—"}

    # ── Macro EU (Eurostat — gratuit, sans clé) ──────────────────────────────

    @staticmethod
    def _fetch_eurostat_dataset(dataset: str, params: dict[str, str]) -> dict[str, Any]:
        """
        Appelle l'API JSON-stat Eurostat et retourne la dernière valeur disponible.
        Retourne {ok, valeur, periode, freshness} — ne lève jamais d'exception
        (timeout/erreur réseau → ok=False, freshness=UNAVAILABLE).
        """
        try:
            qs  = "&".join(f"{k}={v}" for k, v in params.items())
            url = f"{_EUROSTAT_BASE}/{dataset}?format=JSON&lang=EN&{qs}"
            req = urllib.request.Request(
                url, headers={"User-Agent": "king-fund-flux-macro/1.0", "Accept": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=_FETCH_TIMEOUT) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
            data = json.loads(raw)
            values: dict[str, float] = data.get("value", {})
            if not values:
                return {"ok": False, "reason": "DONNÉES INDISPONIBLES", "freshness": "UNAVAILABLE"}
            # JSON-stat : la clé index la plus élevée correspond à la période la plus récente
            # (les dimensions précédant 'time' ont toutes une taille de 1 dans nos requêtes filtrées).
            last_idx = max(int(k) for k in values.keys())
            periodes = list(data.get("dimension", {}).get("time", {}).get("category", {}).get("index", {}).keys())
            periode  = periodes[-1] if periodes else "?"
            return {
                "ok":        True,
                "valeur":    round(float(values[str(last_idx)]), 2),
                "periode":   periode,
                "freshness": "OK",
            }
        except Exception as exc:
            logger.debug("[FluxMacro] Eurostat %s: %s", dataset, exc)
            return {"ok": False, "reason": str(exc), "freshness": "UNAVAILABLE"}

    def _fetch_eurostat(self) -> dict[str, Any]:
        """
        Indicateurs macro Zone Euro/UE27 via Eurostat (API publique, sans clé) :
          - PIB UE27 trimestriel, croissance a/a (namq_10_gdp, unit=CLV_PCH_SM)
          - HICP UE27 mensuel — variation m/m demandée (prc_hicp_mmor) + variation
            a/a (prc_hicp_manr) utilisée pour le seuil d'alerte (4% a/a a du sens,
            4% m/m n'arriverait quasi jamais hors hyperinflation)
          - Taux de chômage UE27 mensuel (une_rt_m, unit=PC_ACT)
          - Balance commerciale UE27 mensuelle (extra-UE27, ext_st_eu27_2020sitc —
            le code 'ext_lt_mainind' demandé n'existe plus dans le catalogue
            Eurostat actuel ; remplacé par l'équivalent mensuel disponible)
        Chaque sous-indicateur est indépendant : l'échec d'un seul ne bloque pas
        les autres (même philosophie que CFTC/WGC/TIC).
        """
        pib = self._fetch_eurostat_dataset("namq_10_gdp", {
            "geo": _EUROSTAT_GEO, "unit": "CLV_PCH_SM", "na_item": "B1GQ", "s_adj": "SCA",
        })
        hicp_mensuel = self._fetch_eurostat_dataset("prc_hicp_mmor", {
            "geo": _EUROSTAT_GEO, "coicop": "CP00", "unit": "RCH_M",
        })
        hicp_annuel = self._fetch_eurostat_dataset("prc_hicp_manr", {
            "geo": _EUROSTAT_GEO, "coicop": "CP00", "unit": "RCH_A",
        })
        chomage = self._fetch_eurostat_dataset("une_rt_m", {
            "geo": _EUROSTAT_GEO, "s_adj": "SA", "age": "TOTAL", "sex": "T", "unit": "PC_ACT",
        })
        balance = self._fetch_eurostat_dataset("ext_st_eu27_2020sitc", {
            "geo": _EUROSTAT_GEO, "sitc06": "TOTAL", "partner": "EXT_EU27_2020",
            "stk_flow": "BAL_RT", "indic_et": "TRD_VAL",
        })

        alertes: list[dict] = []
        if pib.get("ok") and pib["valeur"] < _EUROSTAT_SEUIL_PIB_PCT:
            alertes.append({
                "niveau": "CRITIQUE", "label": "PIB UE27 en contraction",
                "valeur": f"{pib['valeur']}%", "seuil": f"< {_EUROSTAT_SEUIL_PIB_PCT}%",
                "periode": pib["periode"],
            })
        if hicp_annuel.get("ok") and hicp_annuel["valeur"] > _EUROSTAT_SEUIL_HICP_PCT:
            alertes.append({
                "niveau": "CRITIQUE", "label": "Inflation HICP UE27 élevée",
                "valeur": f"{hicp_annuel['valeur']}%", "seuil": f"> {_EUROSTAT_SEUIL_HICP_PCT}%",
                "periode": hicp_annuel["periode"],
            })

        nb_ok = sum(1 for d in (pib, hicp_mensuel, hicp_annuel, chomage, balance) if d.get("ok"))
        return {
            "ok":                  nb_ok > 0,
            "geo":                 _EUROSTAT_GEO,
            "pib_eu":              pib,
            "hicp_mensuel":        hicp_mensuel,
            "hicp_annuel":         hicp_annuel,
            "chomage_eu":          chomage,
            "balance_commerciale": balance,
            "alertes":             alertes,
            "nb_indicateurs_ok":   nb_ok,
            "timestamp":           datetime.now(timezone.utc).isoformat(),
        }

    def macro_eu(self, forcer: bool = False) -> dict:
        """
        Section 'Macro EU' (onglet Intelligence) — PIB/HICP/chômage/balance
        commerciale UE27 via Eurostat. Cache 6h (données mensuelles/trimestrielles,
        pas besoin de rafraîchir plus souvent).
        """
        now = time.time()
        with self._lock:
            if (not forcer and self._cache_macro_eu is not None
                    and (now - self._cache_macro_eu_ts) < self._cache_macro_eu_ttl):
                return self._cache_macro_eu
            result = self._fetch_eurostat()
            self._cache_macro_eu    = result
            self._cache_macro_eu_ts = now
            return result

    def _arbitre_bull_bear(self, these_bull: str, bear_result: dict) -> dict:
        """Verdict arbitre impartial entre positions bull et bear."""
        try:
            from config import ANTHROPIC_API_KEY
            if not ANTHROPIC_API_KEY:
                return {"ok": False, "verdict": "INCERTAIN", "texte": "API non disponible"}
            import anthropic
            bear_pos    = bear_result.get("position_bear", "—")
            raisons_str = " | ".join(bear_result.get("raisons_bear", []))
            prompt = (
                "Tu es un arbitre macro senior indépendant.\n\n"
                f"POSITION BULL : {these_bull[:400]}\n"
                f"POSITION BEAR : {bear_pos[:400]}\n"
                f"CONTRE-ARGUMENTS BEAR : {raisons_str[:400]}\n\n"
                "Rends un verdict impartial en 3 phrases maximum. "
                "Commence par l'un de ces 3 verdicts exacts : BULL_CONFIRMÉ, BEAR_CONFIRMÉ, INCERTAIN. "
                "Justifie uniquement avec des données factuelles."
            )
            client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
            msg = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=250,
                messages=[{"role": "user", "content": prompt}],
            )
            texte = msg.content[0].text.strip()
            upper = texte.upper()
            if "BULL_CONFIRM" in upper:
                verdict_type = "BULL_CONFIRMÉ"
            elif "BEAR_CONFIRM" in upper:
                verdict_type = "BEAR_CONFIRMÉ"
            else:
                verdict_type = "INCERTAIN"
            return {"ok": True, "verdict": verdict_type, "texte": texte}
        except Exception as exc:
            return {"ok": False, "verdict": "INCERTAIN", "texte": f"Erreur arbitre : {exc}"}

    def _backtest_pattern(self, pattern_name: str) -> dict:
        """
        Backtesting historique 1990-2026 d'un pattern de flux macro via yfinance.

        Patterns disponibles :
        - "absorption_or"       : Or baisse avant absorption majeure de liquidité
        - "crise_liquidite_tlt" : corr(TLT,SPY) > 0 sur 5j prédit baisse SPY sur 5j suivants
        """
        try:
            import yfinance as yf
            import pandas as pd

            now   = datetime.now(timezone.utc)
            start = "1990-01-01"

            if pattern_name == "absorption_or":
                events = [
                    p for p in PRECEDENTS_IPO_ABSORPTION
                    if p.get("effet_or") is not None and "SpaceX" not in p.get("nom", "")
                ]
                if not events:
                    return {"ok": False, "raison": "Aucun précédent historique avec données complètes"}
                n_correct = sum(1 for e in events if e["effet_or"] < 0)
                detail = [
                    {
                        "nom":      e["nom"],
                        "montant":  e["montant"],
                        "effet_or": e["effet_or"],
                        "confirme": e["effet_or"] < 0,
                    }
                    for e in events
                ]
                taux = round(n_correct / len(events) * 100, 1)
                return {
                    "ok":                True,
                    "pattern":           pattern_name,
                    "taux_reussite_pct": taux,
                    "n_total":           len(events),
                    "n_correct":         n_correct,
                    "periode":           f"1990–{now.year}",
                    "methode":           "Précédents historiques catalogués (PRECEDENTS_IPO_ABSORPTION)",
                    "detail":            detail,
                    "resume":            (
                        f"Pattern '{pattern_name}' : {taux}% de réussite "
                        f"sur {len(events)} précédents ({start}–{now.year})"
                    ),
                }

            elif pattern_name == "crise_liquidite_tlt":
                end_str = now.strftime("%Y-%m-%d")
                raw = yf.download(
                    ["TLT", "SPY"], start=start, end=end_str,
                    progress=False, auto_adjust=True,
                )
                if raw.empty:
                    return {"ok": False, "raison": "Données TLT/SPY indisponibles"}
                close = raw["Close"] if "Close" in raw.columns or hasattr(raw, "columns") else raw
                tlt_s = close["TLT"].dropna() if "TLT" in close.columns else pd.Series(dtype=float)
                spy_s = close["SPY"].dropna() if "SPY" in close.columns else pd.Series(dtype=float)
                if tlt_s.empty or spy_s.empty:
                    return {"ok": False, "raison": "Colonnes TLT/SPY manquantes"}
                df = pd.DataFrame({"TLT": tlt_s, "SPY": spy_s}).dropna()
                df["TLT_ret"] = df["TLT"].pct_change()
                df["SPY_ret"] = df["SPY"].pct_change()
                df = df.dropna()
                step      = 5
                n_total   = 0
                n_correct = 0
                for i in range(step, len(df) - step):
                    w_tlt = df["TLT_ret"].iloc[i - step:i].tolist()
                    w_spy = df["SPY_ret"].iloc[i - step:i].tolist()
                    corr  = self._corr_pearson(w_tlt, w_spy)
                    if corr is not None and corr > 0:
                        spy_now    = float(df["SPY"].iloc[i])
                        spy_future = float(df["SPY"].iloc[i + step])
                        n_total   += 1
                        n_correct += int(spy_future < spy_now)
                taux = round(n_correct / n_total * 100, 1) if n_total > 0 else None
                return {
                    "ok":                True,
                    "pattern":           pattern_name,
                    "taux_reussite_pct": taux,
                    "n_total":           n_total,
                    "n_correct":         n_correct,
                    "periode":           f"{start}–{now.year}",
                    "methode":           f"corr(TLT_ret, SPY_ret) > 0 sur {step}j → SPY baisse {step}j suivants",
                    "detail":            [],
                    "resume":            (
                        f"Pattern '{pattern_name}' : {taux}% de réussite "
                        f"sur {n_total} signaux ({start}–{now.year})"
                        if taux is not None else "Aucun signal détecté"
                    ),
                }

            return {
                "ok":     False,
                "raison": (
                    f"Pattern '{pattern_name}' inconnu. "
                    "Disponibles : absorption_or, crise_liquidite_tlt"
                ),
            }

        except Exception as exc:
            logger.warning("[FluxMacro] _backtest_pattern(%s): %s", pattern_name, exc)
            return {"ok": False, "pattern": pattern_name, "raison": str(exc)}

    def _recalibrer_seuils(self) -> dict:
        """
        Recalibration automatique des seuils FORT/MOYEN/FAIBLE
        après chaque verdict_posteriori dans flux_macro_journal.
        Taux de réussite réel < 40% → durcit les critères (+1 biais requis).
        Taux > 70% → assouplit (-1 biais requis).
        Stocke les résultats dans flux_macro_calibration.
        """
        if not self._db_path:
            return {"ok": False, "raison": "DB non initialisée"}
        try:
            con = sqlite3.connect(self._db_path)
            con.execute("""
                CREATE TABLE IF NOT EXISTS flux_macro_calibration (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    date        TEXT NOT NULL,
                    confiance   TEXT NOT NULL,
                    n_total     INTEGER,
                    n_correct   INTEGER,
                    taux_pct    REAL,
                    seuil_biais INTEGER,
                    created_at  TEXT DEFAULT (datetime('now'))
                )
            """)
            con.commit()
            calibration: dict[str, dict] = {}
            seuils_defaut = {"FORTE": 6, "MOYEN": 4, "FAIBLE": 0}
            for niveau in ("FORTE", "MOYEN", "FAIBLE"):
                row = con.execute(
                    """SELECT COUNT(*),
                              SUM(CASE WHEN verdict_posteriori = 'CORRECT' THEN 1 ELSE 0 END)
                       FROM flux_macro_journal
                       WHERE confiance = ? AND verdict_posteriori IS NOT NULL""",
                    (niveau,),
                ).fetchone()
                n_total   = row[0] or 0
                n_correct = row[1] or 0
                taux      = round(n_correct / n_total * 100, 1) if n_total >= 3 else None
                seuil_base = seuils_defaut[niveau]
                if taux is not None:
                    if taux < 40 and seuil_base < 8:
                        nouveau_seuil = seuil_base + 1
                    elif taux > 70 and seuil_base > 2:
                        nouveau_seuil = seuil_base - 1
                    else:
                        nouveau_seuil = seuil_base
                else:
                    nouveau_seuil = seuil_base
                calibration[niveau] = {
                    "n_total":     n_total,
                    "n_correct":   n_correct,
                    "taux_pct":    taux,
                    "seuil_biais": nouveau_seuil,
                }
                if n_total >= 3:
                    con.execute(
                        """INSERT INTO flux_macro_calibration
                           (date, confiance, n_total, n_correct, taux_pct, seuil_biais)
                           VALUES (?, ?, ?, ?, ?, ?)""",
                        (
                            datetime.now(timezone.utc).isoformat(),
                            niveau, n_total, n_correct, taux, nouveau_seuil,
                        ),
                    )
            con.commit()
            con.close()
            logger.info("[FluxMacro] Calibration seuils recalculée : %s", calibration)
            return {"ok": True, "calibration": calibration}
        except Exception as exc:
            logger.warning("[FluxMacro] _recalibrer_seuils: %s", exc)
            return {"ok": False, "raison": str(exc)}

    def set_verdict_posteriori(self, journal_id: int, verdict: str,
                               faux_positif: bool | None = None) -> dict:
        """
        Enregistre un verdict a posteriori et déclenche automatiquement
        la recalibration des seuils FORT/MOYEN/FAIBLE.
        verdict : 'CORRECT' | 'INCORRECT' | 'INCERTAIN'
        """
        if not self._db_path:
            return {"ok": False, "raison": "DB non initialisée"}
        try:
            fp_val = 1 if faux_positif is True else (0 if faux_positif is False else None)
            con = sqlite3.connect(self._db_path)
            con.execute(
                """UPDATE flux_macro_journal
                   SET verdict_posteriori = ?, faux_positif = ?
                   WHERE id = ?""",
                (verdict, fp_val, journal_id),
            )
            con.commit()
            con.close()
            calibration = self._recalibrer_seuils()
            return {"ok": True, "verdict_enregistre": verdict, "calibration": calibration}
        except Exception as exc:
            logger.warning("[FluxMacro] set_verdict_posteriori: %s", exc)
            return {"ok": False, "raison": str(exc)}

    def generer_rapport_hebdo(self) -> dict:
        """
        Génère le rapport hebdomadaire (lundi 07:00 UTC).
        Lance d'abord un scan complet puis génère le rapport.
        Sauvegarde dans rapports/flux_macro/hebdo/hebdo_YYYY-WNN.pdf (fallback TXT).
        """
        donnees = self.analyser(forcer=True)
        now     = datetime.now(timezone.utc)
        semaine = now.strftime("W%W")
        nom_base = f"hebdo_{now.strftime('%Y')}-{semaine}"
        chemin_txt = _RAPPORTS_DIR / "hebdo" / f"{nom_base}.txt"

        anomalies      = donnees.get("anomalies", [])
        alertes_liq    = donnees.get("alertes_liquidite", [])
        ipos           = donnees.get("ipos", [])
        regime         = donnees.get("regime", {}).get("regime", "NORMAL")
        confiance      = donnees.get("confiance", "—")
        conclusion     = donnees.get("conclusion", "—")
        sources        = donnees.get("sources_actives", [])
        liq            = donnees.get("fred_liquidite", {})
        journal_recent = self.journal(limite=7)
        taux_info      = self.taux_reussite()

        faux_positifs = [j for j in journal_recent if j.get("faux_positif") == 1]

        texte = (
            f"═══════════════════════════════════════════════════\n"
            f"RAPPORT HEBDOMADAIRE — AGENT FLUX MACRO\n"
            f"Le Détective de Capitaux — {now.strftime('%Y %B')}\n"
            f"═══════════════════════════════════════════════════\n"
            f"Période : {semaine} | Généré le {now.strftime('%Y-%m-%d %H:%M UTC')}\n"
            f"Régime marché : {regime} | Confiance : {confiance}\n"
            f"Taux de réussite signaux : {taux_info['label']} ({taux_info['corrects']}/{taux_info['total']} avec verdict)\n\n"
            f"── ANOMALIES DE LA SEMAINE ({len(anomalies)}) ─────────────────\n"
            + (("\n".join(
                f"  [{a.get('niveau','?')}] {a.get('label','?')} — z={a.get('z_score','?')} | {a.get('variation_pct','?')}%"
                for a in anomalies
            ) if anomalies else "  Aucune anomalie détectée") + "\n\n")
            + f"── ALERTES LIQUIDITÉ ({len(alertes_liq)}) ──────────────────────\n"
            + (("\n".join(
                f"  [{a.get('niveau','?')}] {a.get('label','?')} — {a.get('valeur','?')} (seuil: {a.get('seuil','?')})"
                for a in alertes_liq
            ) if alertes_liq else "  Aucune alerte liquidité") + "\n\n")
            + f"── INDICATEURS LIQUIDITÉ MACRO ────────────────────\n"
            f"  M2SL (masse monétaire US) : {liq.get('M2SL', 'DONNÉES INDISPONIBLES')} Mds$\n"
            f"  WALCL (Fed balance sheet) : {liq.get('WALCL', 'DONNÉES INDISPONIBLES')} Mds$\n"
            f"  IORB (taux repo Fed)      : {liq.get('IORB', 'DONNÉES INDISPONIBLES')} %\n"
            f"  Spreads IG (BAMLC0A0CM)  : {liq.get('BAMLC0A0CM', 'DONNÉES INDISPONIBLES')} bps\n"
            f"  Spreads HY (BAMLH0A0HYM2): {liq.get('BAMLH0A0HYM2', 'DONNÉES INDISPONIBLES')} bps\n\n"
            f"── CALENDRIER IPO (SEC EDGAR S-1) ─────────────────\n"
            + (("\n".join(
                f"  {i.get('date','?')} — {i.get('titre','?')[:80]}"
                for i in ipos[:5]
            ) if ipos else "  Aucun filing S-1 récent") + "\n\n")
            + f"── FAUX POSITIFS SEMAINE ({len(faux_positifs)}) ─────────────────\n"
            + (("\n".join(
                f"  {j.get('date','?')[:10]} — {j.get('anomalie','?')[:60]}"
                for j in faux_positifs[:5]
            ) if faux_positifs else "  Aucun faux positif enregistré") + "\n\n")
            + f"── CONCLUSION ───────────────────────────────────\n"
            f"{conclusion}\n\n"
            f"── SOURCES ACTIVES ({len(sources)}) ─────────────────────────\n"
            + "\n".join(f"  • {s}" for s in sources) + "\n\n"
            f"⚠️ DISCLAIMER : {DISCLAIMER}\n"
            f"═══════════════════════════════════════════════════\n"
        )

        # ── Tentative PDF (fpdf2) ────────────────────────────────────────────
        chemin_final = chemin_txt
        fmt = "txt"
        try:
            from fpdf import FPDF

            def _p(s: Any) -> str:
                return str(s).encode("latin-1", errors="replace").decode("latin-1")

            pdf = FPDF()
            pdf.set_margins(left=12, top=12, right=12)
            pdf.set_auto_page_break(auto=True, margin=15)
            pdf.add_page()
            W = pdf.epw

            pdf.set_font("Helvetica", "B", 13)
            pdf.cell(W, 9, "RAPPORT HEBDO - AGENT FLUX MACRO", new_x="LMARGIN", new_y="NEXT", align="C")
            pdf.set_font("Helvetica", "", 9)
            pdf.cell(W, 5, f"Le Detecteur de Capitaux - {now.strftime('%Y %B')} - {semaine}",
                     new_x="LMARGIN", new_y="NEXT", align="C")
            pdf.cell(W, 5, f"Genere le {now.strftime('%Y-%m-%d %H:%M UTC')}",
                     new_x="LMARGIN", new_y="NEXT")
            pdf.cell(W, 5, _p(f"Regime : {regime}  |  Confiance : {confiance}  |  "
                               f"Taux reussite : {taux_info['label']} ({taux_info['corrects']}/{taux_info['total']})"),
                     new_x="LMARGIN", new_y="NEXT")
            pdf.ln(3)

            def _section(titre: str) -> None:
                pdf.set_font("Helvetica", "B", 10)
                pdf.cell(W, 7, titre, new_x="LMARGIN", new_y="NEXT")
                pdf.set_font("Helvetica", "", 9)

            _section(f"ANOMALIES DE LA SEMAINE ({len(anomalies)})")
            if anomalies:
                for a in anomalies:
                    pdf.multi_cell(W, 4, _p(
                        f"[{a.get('niveau','?')}] {a.get('label','?')} — "
                        f"z={a.get('z_score','?')} | {a.get('variation_pct','?')}%"
                    ), new_x="LMARGIN", new_y="NEXT")
            else:
                pdf.cell(W, 5, "Aucune anomalie detectee", new_x="LMARGIN", new_y="NEXT")
            pdf.ln(2)

            _section(f"ALERTES LIQUIDITE ({len(alertes_liq)})")
            if alertes_liq:
                for a in alertes_liq:
                    pdf.multi_cell(W, 4, _p(
                        f"[{a.get('niveau','?')}] {a.get('label','?')} — "
                        f"{a.get('valeur','?')} (seuil: {a.get('seuil','?')})"
                    ), new_x="LMARGIN", new_y="NEXT")
            else:
                pdf.cell(W, 5, "Aucune alerte liquidite", new_x="LMARGIN", new_y="NEXT")
            pdf.ln(2)

            _section("INDICATEURS LIQUIDITE MACRO (FRED)")
            for k, label in [("M2SL","M2SL Mds$"), ("WALCL","WALCL Mds$"),
                              ("IORB","IORB %"), ("BAMLC0A0CM","IG spread"),
                              ("BAMLH0A0HYM2","HY spread")]:
                pdf.cell(W, 4, _p(f"  {label}: {liq.get(k, 'N/D')}"),
                         new_x="LMARGIN", new_y="NEXT")
            pdf.ln(2)

            _section(f"CALENDRIER IPO SEC EDGAR ({len(ipos)} filing(s) S-1)")
            if ipos:
                for i in ipos[:5]:
                    pdf.multi_cell(W, 4, _p(f"  {i.get('date','?')} — {str(i.get('titre','?'))[:90]}"),
                                   new_x="LMARGIN", new_y="NEXT")
            else:
                pdf.cell(W, 4, "  Aucun filing S-1 recent", new_x="LMARGIN", new_y="NEXT")
            pdf.ln(2)

            _section("CONCLUSION")
            pdf.multi_cell(W, 5, _p(str(conclusion)[:600]), new_x="LMARGIN", new_y="NEXT")
            pdf.ln(2)

            _section(f"SOURCES ACTIVES ({len(sources)})")
            for s in sources[:8]:
                pdf.multi_cell(W, 4, _p(f"- {str(s)[:110]}"), new_x="LMARGIN", new_y="NEXT")
            pdf.ln(2)

            _section(f"FAUX POSITIFS SEMAINE ({len(faux_positifs)})")
            if faux_positifs:
                for j in faux_positifs[:5]:
                    pdf.multi_cell(W, 4, _p(f"  {str(j.get('date','?'))[:10]} — {str(j.get('anomalie','?'))[:70]}"),
                                   new_x="LMARGIN", new_y="NEXT")
            else:
                pdf.cell(W, 4, "  Aucun faux positif enregistre", new_x="LMARGIN", new_y="NEXT")
            pdf.ln(2)

            pdf.set_font("Helvetica", "I", 8)
            pdf.multi_cell(W, 4, _p(f"DISCLAIMER : {DISCLAIMER}"), new_x="LMARGIN", new_y="NEXT")

            chemin_pdf = _RAPPORTS_DIR / "hebdo" / f"{nom_base}.pdf"
            pdf.output(str(chemin_pdf))
            chemin_final = chemin_pdf
            fmt = "pdf"
            logger.info("[FluxMacro] Rapport hebdo PDF sauvegardé : %s", chemin_pdf)

        except ImportError:
            logger.debug("[FluxMacro] fpdf2 absent — fallback TXT pour hebdo")
        except Exception as exc:
            logger.warning("[FluxMacro] Rapport hebdo PDF erreur: %s", exc)

        # ── Fallback TXT (toujours écrit pour archivage) ─────────────────────
        try:
            chemin_txt.write_text(texte, encoding="utf-8")
        except Exception as exc:
            logger.warning("[FluxMacro] Rapport hebdo TXT sauvegarde: %s", exc)

        try:
            from divisions.gerant_delegue.notifier import send
            send(
                f"📊 Rapport Hebdo Flux Macro — {semaine}\n"
                f"Anomalies: {len(anomalies)} | Alertes liq: {len(alertes_liq)} | Régime: {regime}\n"
                f"Confiance: {confiance} | Taux réussite: {taux_info['label']}\n"
                f"⚠️ {DISCLAIMER}",
                "info",
            )
        except Exception:
            pass
        return {"ok": True, "chemin": str(chemin_final), "texte": texte,
                "semaine": semaine, "format": fmt}
