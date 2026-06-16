"""
Test manuel — Résilience Agent Flux Macro face à l'indisponibilité CFTC/WGC/TIC.

Simule un timeout forcé sur les 3 sources externes (CFTC, WGC/IMF, TIC Data)
et vérifie que :
  1. Chaque _fetch_*() individuel ne lève jamais d'exception (try/except interne).
  2. analyser(forcer=True) se termine sans planter, avec ok=False / "DONNÉES
     INDISPONIBLES" propre pour CFTC/TIC, et un fallback STATIC pour WGC.
  3. generer_rapport_flash() reste générable (PDF) même en mode totalement dégradé.

Usage : cd backend && python ../test_fallback_sources.py
"""
import socket
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "backend"))

import urllib.request

_orig_urlopen = urllib.request.urlopen
_TIMEOUT_HOSTS = ("cftc.gov", "imf.org", "ticdata.treasury.gov")


def _forced_timeout(req, *a, **kw):
    url = req.full_url if hasattr(req, "full_url") else str(req)
    if any(h in url for h in _TIMEOUT_HOSTS):
        raise socket.timeout(f"[TEST] timeout simulé pour {url[:70]}")
    return _orig_urlopen(req, *a, **kw)


def main() -> int:
    urllib.request.urlopen = _forced_timeout

    from divisions.research.agent_flux_macro import get_agent_flux_macro
    agent = get_agent_flux_macro()

    failures: list[str] = []

    print("=== 1. Fetchers individuels avec timeout forcé ===")
    for name, fn in (
        ("_fetch_cftc",     agent._fetch_cftc),
        ("_fetch_wgc",      agent._fetch_wgc),
        ("_fetch_tic_data", agent._fetch_tic_data),
    ):
        try:
            r = fn()
            print(f"  {name}: OK (pas de crash) — ok={r.get('ok')} freshness={r.get('freshness', '?')}")
        except Exception:
            failures.append(name)
            print(f"  {name}: CRASH !!!")
            traceback.print_exc()

    print("\n=== 2. analyser(forcer=True) end-to-end ===")
    try:
        result = agent.analyser(forcer=True)
        cftc_ok = result.get("cftc", {}).get("ok")
        tic_ok  = result.get("tic_data", {}).get("ok")
        print(f"  analyser(): OK (pas de crash) — confiance={result.get('confiance')} "
              f"nb_sources={result.get('nb_sources')}")
        print(f"  cftc.ok={cftc_ok} (attendu False) | tic_data.ok={tic_ok} (attendu False)")
        if cftc_ok or tic_ok:
            failures.append("analyser: cftc/tic devraient être ok=False sous timeout forcé")
    except Exception:
        failures.append("analyser")
        print("  analyser(): CRASH !!!")
        traceback.print_exc()

    print("\n=== 3. generer_rapport_flash() en mode dégradé ===")
    try:
        flash = agent.generer_rapport_flash()
        print(f"  rapport flash: OK — ok={flash.get('ok')} format={flash.get('format')}")
        if not flash.get("ok"):
            failures.append("generer_rapport_flash: ok=False")
    except Exception:
        failures.append("generer_rapport_flash")
        print("  rapport flash: CRASH !!!")
        traceback.print_exc()

    urllib.request.urlopen = _orig_urlopen

    print()
    if failures:
        print(f"ÉCHEC — {len(failures)} problème(s) : {failures}")
        return 1
    print("SUCCÈS — l'agent survit à l'indisponibilité totale CFTC/WGC/TIC sans planter.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
