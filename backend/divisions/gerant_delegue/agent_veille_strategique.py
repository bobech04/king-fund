"""
Agent Veille Stratégique — Surveillance RSS macro
Sources  : Bruno Bertez (P1), Ray Dalio, CrossBorderCapital, InflationGuy
Thèmes   : énergie, PIB, dette, actifs réels, MMT, liquidité
Niveaux  : CRITIQUE → Telegram immédiat | IMPORTANT | INFO
Stockage : SQLite table veille_strategique
"""
from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import sys
import threading
import time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from divisions.gerant_delegue.notifier import alerte
from config import DB_PATH

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Sources RSS
# ---------------------------------------------------------------------------

SOURCES = [
    {"nom": "Bruno Bertez",       "url": "https://brunobertez.com/feed/",                      "priorite": 1},
    {"nom": "Ray Dalio",          "url": "https://raydalio.substack.com/feed",                 "priorite": 2},
    {"nom": "CrossBorderCapital", "url": "https://crossbordercapital.com/feed/",               "priorite": 2},
    {"nom": "InflationGuy",       "url": "https://inflationguy.blog/feed/",                    "priorite": 2},
]

# ---------------------------------------------------------------------------
# Thèmes et mots-clés de classification
# ---------------------------------------------------------------------------

_THEMES: dict[str, list[str]] = {
    "énergie":      ["énergie", "energie", "energy", "pétrole", "petrole",
                     "wti", "brent", "oil", "gaz", "gas", "nuclear", "nucléaire", "eia"],
    "PIB":          ["pib", "gdp", "croissance", "growth", "recession",
                     "récession", "productivity", "productivité", "output gap"],
    "dette":        ["dette", "debt", "déficit", "deficit", "emprunt",
                     "obligation", "bond", "sovereign", "souverain", "trésor",
                     "treasury", "leverage", "levier", "interest expense",
                     "charge d'intérêt", "refinancement"],
    "actifs réels": ["actifs réels", "real assets", "infrastructure",
                     "immobilier", "real estate", "commodité", "commodity",
                     "or physique", "gold", "inflation hedge", "tangible"],
    "MMT":          ["mmt", "modern monetary theory", "monnaie moderne",
                     "helicopter money", "monétisation", "monetization",
                     "fiscal dominance", "printing money"],
    "liquidité":    ["liquidité", "liquidity", "credit", "crédit",
                     "bank reserves", "réserves", "m2", "money supply",
                     "masse monétaire", "repo", "fed balance", "bce bilan",
                     "quantitative easing", "qe", "qt", "tightening", "easing",
                     "howell", "global liquidity", "cross-border capital"],
}

_CRITIQUE_KW = [
    "crash", "effondrement", "default", "défaut souverain", "bank run",
    "bank failure", "circuit breaker", "contagion", "systemic risk",
    "risque systémique", "liquidity crisis", "crise de liquidité",
    "credit crunch", "margin call", "emergency", "urgence", "crise systémique",
    "sovereign debt crisis", "faillite souveraine",
]

_IMPORTANT_KW_EXTRA = [
    "alerte", "warning", "attention", "risque", "risk", "danger",
    "pivot", "tournant", "renversement", "reversal",
]

_HEADERS = {"User-Agent": "king-fund-veille/1.0"}
_CACHE_TTL = 3600  # 1h


# ---------------------------------------------------------------------------
# Parsing RSS/Atom
# ---------------------------------------------------------------------------

def _fetch_rss(url: str) -> list[dict]:
    try:
        req = urllib.request.Request(url, headers=_HEADERS)
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read()
        root = ET.fromstring(raw)
        arts: list[dict] = []

        # RSS 2.0
        for item in root.iter("item"):
            titre = (item.findtext("title") or "").strip()
            lien  = (item.findtext("link")  or "").strip()
            desc  = (item.findtext("description") or "").strip()[:600]
            pub   = (item.findtext("pubDate") or "").strip()
            if titre:
                arts.append({"titre": titre, "url": lien, "publie_a": pub, "description": desc})

        # Atom 1.0 fallback
        if not arts:
            ns = "{http://www.w3.org/2005/Atom}"
            for entry in root.iter(f"{ns}entry"):
                titre = (entry.findtext(f"{ns}title") or "").strip()
                lien = ""
                for link in entry.findall(f"{ns}link"):
                    if link.get("rel", "alternate") in ("alternate", ""):
                        lien = link.get("href", "")
                        break
                if not lien:
                    el = entry.find(f"{ns}link")
                    lien = el.get("href", "") if el is not None else ""
                desc = (entry.findtext(f"{ns}summary") or "").strip()[:600]
                pub  = (entry.findtext(f"{ns}updated") or "").strip()
                if titre:
                    arts.append({"titre": titre, "url": lien, "publie_a": pub, "description": desc})

        return arts[:25]
    except Exception as exc:
        logger.debug("[VeilleRSS] %s → %s", url, exc)
        return []


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def _detecter_themes(texte: str) -> list[str]:
    t = texte.lower()
    return [th for th, kws in _THEMES.items() if any(kw in t for kw in kws)]


def _classer(titre: str, desc: str, themes: list[str], priorite: int) -> str:
    texte = (titre + " " + desc).lower()
    if any(kw in texte for kw in _CRITIQUE_KW):
        return "CRITIQUE"
    # Bertez (P1) avec ≥ 2 thèmes → CRITIQUE
    if priorite == 1 and len(themes) >= 2:
        return "CRITIQUE"
    if themes:
        # Si mot d'alerte en plus → CRITIQUE
        if any(kw in texte for kw in _IMPORTANT_KW_EXTRA) and priorite == 1:
            return "CRITIQUE"
        return "IMPORTANT"
    return "INFO"


def _fp(titre: str, url: str) -> str:
    return hashlib.md5((titre + url)[:120].encode(), usedforsecurity=False).hexdigest()[:12]


# ---------------------------------------------------------------------------
# SQLite
# ---------------------------------------------------------------------------

def _init_db(db_path: Path) -> None:
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS veille_strategique (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            fp         TEXT UNIQUE,
            source     TEXT,
            titre      TEXT,
            url        TEXT,
            publie_a   TEXT,
            themes     TEXT,
            niveau     TEXT,
            created_at TEXT
        )
    """)
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Agent principal
# ---------------------------------------------------------------------------

class AgentVeilleStrategique:
    def __init__(self) -> None:
        self._lock      = threading.Lock()
        self._cache:    list[dict] = []
        self._cache_ts: float = 0.0
        self._alertes_envoyees: set[str] = set()
        self._db_init   = False

    def _ensure_db(self) -> None:
        if not self._db_init:
            _init_db(DB_PATH)
            self._db_init = True

    # ------------------------------------------------------------------

    def analyser(self, forcer: bool = False) -> list[dict]:
        now = time.monotonic()
        if not forcer and self._cache and (now - self._cache_ts) < _CACHE_TTL:
            return list(self._cache)

        self._ensure_db()
        tous: list[dict] = []

        conn = sqlite3.connect(str(DB_PATH))
        try:
            for src in SOURCES:
                arts = _fetch_rss(src["url"])
                for art in arts:
                    texte  = art["titre"] + " " + art.get("description", "")
                    themes = _detecter_themes(texte)
                    niveau = _classer(art["titre"], art.get("description", ""), themes, src["priorite"])
                    fp     = _fp(art["titre"], art["url"])

                    art.update({
                        "source":   src["nom"],
                        "priorite": src["priorite"],
                        "themes":   themes,
                        "niveau":   niveau,
                        "fp":       fp,
                    })
                    tous.append(art)

                    # Persist uniquement si nouveau
                    try:
                        conn.execute(
                            "INSERT OR IGNORE INTO veille_strategique "
                            "(fp, source, titre, url, publie_a, themes, niveau, created_at) "
                            "VALUES (?,?,?,?,?,?,?,?)",
                            (fp, src["nom"], art["titre"], art["url"],
                             art["publie_a"],
                             json.dumps(themes, ensure_ascii=False),
                             niveau,
                             datetime.now(timezone.utc).isoformat()),
                        )
                        if conn.execute("SELECT changes()").fetchone()[0] > 0:
                            # Nouveau → alerte si CRITIQUE
                            if niveau == "CRITIQUE":
                                self._alerter(art)
                    except Exception as exc:
                        logger.debug("[VeilleDB] insert: %s", exc)

            conn.commit()
        finally:
            conn.close()

        # Trier : CRITIQUE → IMPORTANT → INFO, puis par priorité source
        _ord = {"CRITIQUE": 0, "IMPORTANT": 1, "INFO": 2}
        tous.sort(key=lambda a: (_ord.get(a["niveau"], 3), a.get("priorite", 9)))

        nb_c = sum(1 for a in tous if a["niveau"] == "CRITIQUE")
        nb_i = sum(1 for a in tous if a["niveau"] == "IMPORTANT")
        logger.info(
            "[VeilleStrat] %d articles — CRITIQUE:%d IMPORTANT:%d INFO:%d",
            len(tous), nb_c, nb_i, len(tous) - nb_c - nb_i,
        )

        with self._lock:
            self._cache    = tous
            self._cache_ts = now

        return list(tous)

    # ------------------------------------------------------------------

    def _alerter(self, art: dict) -> None:
        fp = art.get("fp", "")
        if fp in self._alertes_envoyees:
            return
        self._alertes_envoyees.add(fp)
        themes_str = " · ".join(art.get("themes") or []) or "—"
        alerte(
            "VEILLE STRATÉGIQUE CRITIQUE",
            f"📡 <b>{art.get('source', '')}</b>\n"
            f"📰 {art.get('titre', '')}\n"
            f"Thèmes : {themes_str}\n"
            f"{art.get('url', '')}",
            niveau="critique",
        )

    # ------------------------------------------------------------------

    def etat(self) -> dict:
        cache = self._cache
        return {
            "nb_total":    len(cache),
            "nb_critique": sum(1 for a in cache if a["niveau"] == "CRITIQUE"),
            "nb_important":sum(1 for a in cache if a["niveau"] == "IMPORTANT"),
            "nb_info":     sum(1 for a in cache if a["niveau"] == "INFO"),
            "sources":     [s["nom"] for s in SOURCES],
            "derniere_maj": (
                datetime.fromtimestamp(self._cache_ts, tz=timezone.utc).isoformat()
                if self._cache_ts else None
            ),
        }

    def historique(self, limite: int = 100) -> list[dict]:
        self._ensure_db()
        try:
            conn = sqlite3.connect(str(DB_PATH))
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM veille_strategique ORDER BY created_at DESC LIMIT ?",
                (limite,),
            ).fetchall()
            conn.close()
            result = []
            for r in rows:
                d = dict(r)
                try:
                    d["themes"] = json.loads(d.get("themes") or "[]")
                except Exception:
                    d["themes"] = []
                result.append(d)
            return result
        except Exception as exc:
            logger.warning("[VeilleDB] historique: %s", exc)
            return []


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_instance: AgentVeilleStrategique | None = None
_lock = threading.Lock()


def get_agent_veille() -> AgentVeilleStrategique:
    global _instance
    if _instance is None:
        with _lock:
            if _instance is None:
                _instance = AgentVeilleStrategique()
    return _instance
