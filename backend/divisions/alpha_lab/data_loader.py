"""
Alpha Lab — Data Loader
Télécharge et cache les données historiques longues sans pandas_datareader
(compatible Python 3.12+ où distutils est absent) :
  • Facteurs Kenneth French (1926+) : CSV zippé depuis tuck.dartmouth.edu
  • Shiller S&P500 CAPE (1871+) : XLS depuis Yale
  • Indices EU longs : CSV depuis Stooq (CAC40, DAX, EuroStoxx50)
Cache : database/history/{nom}.csv  (TTL 7 jours par défaut)
"""
from __future__ import annotations

import io
import logging
import time
import zipfile
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import requests

logger = logging.getLogger(__name__)

HISTORY_DIR = Path(__file__).resolve().parents[3] / "database" / "history"
HISTORY_DIR.mkdir(parents=True, exist_ok=True)

CACHE_TTL_DAYS   = 7
SHILLER_TTL_DAYS = 30

_HEADERS = {"User-Agent": "Mozilla/5.0 (AlphaLab/1.0; research)"}


def _cache_path(name: str) -> Path:
    return HISTORY_DIR / f"{name}.csv"


def _is_stale(path: Path, ttl_days: int = CACHE_TTL_DAYS) -> bool:
    if not path.exists():
        return True
    age = (time.time() - path.stat().st_mtime) / 86_400
    return age > ttl_days


# ---------------------------------------------------------------------------
# Kenneth French — téléchargement direct CSV zippé
# ---------------------------------------------------------------------------

_FF_URLS: dict[str, str] = {
    "ff3": "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/F-F_Research_Data_Factors_CSV.zip",
    "mom": "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/F-F_Momentum_Factor_CSV.zip",
    "ff5": "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/F-F_Research_Data_5_Factors_2x3_CSV.zip",
}

# Colonnes attendues par dataset (pour nettoyage)
_FF_EXPECTED_COLS: dict[str, list[str]] = {
    "ff3": ["Mkt-RF", "SMB", "HML", "RF"],
    "mom": ["Mom"],
    "ff5": ["Mkt-RF", "SMB", "HML", "RMW", "CMA", "RF"],
}


def _parse_french_csv(content: bytes, key: str) -> Optional[pd.DataFrame]:
    """
    Parse le CSV zippé Kenneth French.
    Format réel :
      ligne 0-3 : texte libre
      ligne 4   : ,Mkt-RF,SMB,HML,RF  ← première colonne vide (c'est l'index)
      ligne 5+  : 192607,2.89,...      ← données mensuelles YYYYMM
      ligne vide : séparateur
      suite      : données annuelles (ignorées)
    """
    try:
        text  = content.decode("latin-1")
        lines = text.splitlines()

        # 1. Trouver la première ligne de données mensuelles (YYYYMM = 6 chiffres)
        data_start = None
        for i, line in enumerate(lines):
            first = line.strip().split(",")[0].strip()
            if first.isdigit() and len(first) == 6:
                data_start = i
                break

        if data_start is None:
            logger.warning("Alpha Lab [French %s] bloc données non trouvé", key)
            return None

        # 2. Récupérer l'en-tête (ligne juste avant data_start)
        #    Format : ",Mkt-RF,SMB,HML,RF"  — première colonne vide = index
        header_raw = lines[data_start - 1] if data_start > 0 else ""
        header_parts = header_raw.split(",")
        # parts[0] est vide ; les suivants sont les noms de colonnes
        col_names = ["Date"] + [c.strip() for c in header_parts[1:] if c.strip()]

        # 3. Collecter les lignes de données mensuelles jusqu'à ligne vide
        data_lines: list[str] = []
        for line in lines[data_start:]:
            stripped = line.strip()
            if not stripped:
                break
            first = stripped.split(",")[0].strip()
            if not (first.isdigit() and len(first) == 6):
                break
            data_lines.append(stripped)

        if not data_lines:
            return None

        # 4. Construire et parser le DataFrame
        csv_text = ",".join(col_names) + "\n" + "\n".join(data_lines)
        df = pd.read_csv(io.StringIO(csv_text), index_col=0)
        df.columns = [c.strip() for c in df.columns]
        df.index   = pd.to_datetime(df.index.astype(str).str.zfill(6), format="%Y%m")
        df.index.name = "date"

        # centièmes de % → décimal
        df = df.apply(pd.to_numeric, errors="coerce") / 100.0

        # Normaliser le nom Mom (selon la version du fichier)
        if key == "mom" and "Mom" not in df.columns:
            df.columns = ["Mom"] + list(df.columns[1:])

        return df.dropna(how="all")

    except Exception as exc:
        logger.warning("Alpha Lab [French %s] parse error: %s", key, exc)
        return None


def load_french_factors(force: bool = False) -> dict[str, pd.DataFrame]:
    """
    Charge facteurs Kenneth French mensuels depuis 1926.
    Retourne dict : 'ff3' (Mkt-RF,SMB,HML,RF), 'mom' (Mom), 'ff5' (RMW,CMA…).
    """
    results: dict[str, pd.DataFrame] = {}

    for key, url in _FF_URLS.items():
        path = _cache_path(f"french_{key.upper()}")

        if not force and not _is_stale(path):
            try:
                results[key] = pd.read_csv(path, index_col=0, parse_dates=True)
                logger.debug("Alpha Lab [French %s] cache hit", key)
                continue
            except Exception:
                pass

        try:
            resp = requests.get(url, headers=_HEADERS, timeout=40)
            resp.raise_for_status()

            with zipfile.ZipFile(BytesIO(resp.content)) as zf:
                csv_name = next(n for n in zf.namelist() if n.endswith(".CSV") or n.endswith(".csv"))
                raw_bytes = zf.read(csv_name)

            df = _parse_french_csv(raw_bytes, key)
            if df is not None and not df.empty:
                df.to_csv(path)
                results[key] = df
                logger.info("Alpha Lab [French %s] téléchargé — %d mois (%s → %s)",
                            key, len(df), df.index[0].date(), df.index[-1].date())
            else:
                logger.warning("Alpha Lab [French %s] DataFrame vide après parsing", key)

        except Exception as exc:
            logger.warning("Alpha Lab [French %s] échec téléchargement: %s", key, exc)
            if path.exists():
                try:
                    results[key] = pd.read_csv(path, index_col=0, parse_dates=True)
                    logger.info("Alpha Lab [French %s] fallback cache", key)
                except Exception:
                    pass

    return results


# ---------------------------------------------------------------------------
# Shiller S&P500 CAPE
# ---------------------------------------------------------------------------

def load_shiller_sp500(force: bool = False) -> Optional[pd.DataFrame]:
    """Charge données Shiller S&P500 CAPE 1871+ depuis Yale."""
    path = _cache_path("shiller_sp500")

    if not force and not _is_stale(path, ttl_days=SHILLER_TTL_DAYS):
        try:
            df = pd.read_csv(path, index_col=0, parse_dates=True)
            logger.debug("Alpha Lab [Shiller] cache hit")
            return df
        except Exception:
            pass

    url = "http://www.econ.yale.edu/~shiller/data/ie_data.xls"
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=40)
        resp.raise_for_status()

        raw = pd.read_excel(BytesIO(resp.content), sheet_name="Data", skiprows=7, engine="xlrd")
        raw = raw.dropna(subset=[raw.columns[0]]).copy()
        date_num = pd.to_numeric(raw.iloc[:, 0], errors="coerce")
        raw = raw[date_num.notna()].copy()
        date_num = date_num[date_num.notna()]

        def _to_ts(v: float) -> pd.Timestamp:
            year  = int(v)
            month = round((v - year) * 100)
            month = max(1, min(12, month)) if month > 0 else 1
            return pd.Timestamp(year=year, month=month, day=1)

        raw.index = date_num.map(_to_ts)
        raw = raw[raw.index.notna()]

        cols = list(raw.columns)
        rename = {}
        if len(cols) > 1: rename[cols[1]] = "price"
        if len(cols) > 2: rename[cols[2]] = "dividend"
        if len(cols) > 3: rename[cols[3]] = "earnings"
        if len(cols) > 4: rename[cols[4]] = "cpi"
        if len(cols) > 6: rename[cols[6]] = "gs10"
        if len(cols) > 8: rename[cols[8]] = "cape"

        df = raw[[c for c in rename if c in raw.columns]].rename(columns=rename)
        df = df.apply(pd.to_numeric, errors="coerce").dropna(how="all")
        df.to_csv(path)
        logger.info("Alpha Lab [Shiller] téléchargé — %d obs (%s → %s)",
                    len(df), df.index[0].date(), df.index[-1].date())
        return df

    except Exception as exc:
        logger.warning("Alpha Lab [Shiller] échec: %s", exc)

    if path.exists():
        try:
            return pd.read_csv(path, index_col=0, parse_dates=True)
        except Exception:
            pass
    return None


# ---------------------------------------------------------------------------
# Indices EU longs — Stooq CSV direct
# ---------------------------------------------------------------------------

_EU_TICKERS: dict[str, str] = {
    "cac40":       "^FCHI",      # CAC 40 — Yahoo Finance
    "dax":         "^GDAXI",     # DAX
    "eurostoxx50": "^STOXX50E",  # Euro Stoxx 50
}


def load_eu_indices(force: bool = False) -> dict[str, pd.DataFrame]:
    """
    Charge indices EU longs via yfinance (depuis 1990 si disponible).
    Tickers Yahoo Finance : ^FCHI (CAC40), ^GDAXI (DAX), ^STOXX50E (EuroStoxx50).
    """
    import yfinance as yf

    results: dict[str, pd.DataFrame] = {}

    for name, ticker in _EU_TICKERS.items():
        path = _cache_path(f"eu_{name}")

        if not force and not _is_stale(path):
            try:
                results[name] = pd.read_csv(path, index_col=0, parse_dates=True)
                logger.debug("Alpha Lab [EU %s] cache hit", name)
                continue
            except Exception:
                pass

        try:
            df = yf.download(ticker, start="1990-01-01", progress=False, auto_adjust=True)
            if df.empty:
                raise ValueError("DataFrame vide")
            # Aplatir colonnes MultiIndex si présent
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            df = df.sort_index()
            df.to_csv(path)
            results[name] = df
            logger.info("Alpha Lab [EU %s] téléchargé — %d jours (%s → %s)",
                        name, len(df), df.index[0].date(), df.index[-1].date())
        except Exception as exc:
            logger.warning("Alpha Lab [EU %s] échec: %s", name, exc)
            if path.exists():
                try:
                    results[name] = pd.read_csv(path, index_col=0, parse_dates=True)
                except Exception:
                    pass

    return results


# ---------------------------------------------------------------------------
# Point d'entrée global
# ---------------------------------------------------------------------------

def load_all(force: bool = False) -> dict:
    """Charge tous les datasets. ~30–60 s la première fois, instantané ensuite."""
    t0 = time.time()
    french  = load_french_factors(force=force)
    shiller = load_shiller_sp500(force=force)
    eu      = load_eu_indices(force=force)

    logger.info(
        "Alpha Lab [DataLoader] terminé en %.1fs — FF:%d mois | Shiller:%s obs | EU:%d barres",
        time.time() - t0,
        sum(len(v) for v in french.values()),
        len(shiller) if shiller is not None else 0,
        sum(len(v) for v in eu.values()),
    )
    return {"french": french, "shiller": shiller, "eu": eu}
