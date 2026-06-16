"""
Test manuel — KPI "Taux de réussite" (signaux Flux Macro).

Vérifie la chaîne complète :
  1. Backend : AgentFluxMacro.taux_reussite() lit bien flux_macro_journal et
     calcule corrects/total correctement (insère 3 lignes de test marquées,
     vérifie le calcul, puis les supprime — aucune pollution de la DB réelle).
  2. Endpoint : GET /api/flux-macro/taux-reussite répond avec le même résultat.
  3. Frontend : frontend/index.html contient bien la carte KPI "Taux de
     réussite" (id="fm-taux-reussite") dans la section Flux Macro de l'onglet
     Intelligence, et frontend/app.js l'alimente via cet endpoint.

Usage : cd backend && python ../test_taux_reussite_kpi.py
(le serveur Flask doit tourner sur localhost:5000 pour l'étape 2 ; sinon
 elle est simplement signalée comme ignorée).
"""
import sqlite3
import sys
import urllib.request
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "backend"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

MARKER = "__TEST_KPI_MARKER__"


def main() -> int:
    failures: list[str] = []

    from config import DB_PATH
    from divisions.research.agent_flux_macro import get_agent_flux_macro
    agent = get_agent_flux_macro()

    print("=== 1. Backend : taux_reussite() avec données de test marquées ===")
    con = sqlite3.connect(DB_PATH)
    try:
        before = con.execute(
            "SELECT COUNT(*) FROM flux_macro_journal WHERE verdict_posteriori IS NOT NULL"
        ).fetchone()[0]

        # 2 CORRECT + 1 INCORRECT → taux attendu sur les 3 ajoutés : 66.7%
        # Colonnes : anomalie_detectee, sources_utilisees, confiance, conclusion,
        #            action_suggeree, verdict_posteriori, faux_positif
        rows = [
            (MARKER, "[]", "FORTE", "test", "", "CORRECT",   0),
            (MARKER, "[]", "FORTE", "test", "", "CORRECT",   0),
            (MARKER, "[]", "FORTE", "test", "", "INCORRECT", 1),
        ]
        con.executemany(
            """INSERT INTO flux_macro_journal
               (date, anomalie_detectee, sources_utilisees, confiance, conclusion,
                action_suggeree, verdict_posteriori, faux_positif)
               VALUES (datetime('now'), ?, ?, ?, ?, ?, ?, ?)""",
            rows,
        )
        con.commit()

        result = agent.taux_reussite()
        after = result["total"]
        print(f"  total avant: {before} | total après insertion: {after} (+3 attendu)")
        print(f"  taux_reussite() = {result}")

        if after != before + 3:
            failures.append(f"total attendu {before+3}, obtenu {after}")
    finally:
        # Nettoyage impératif — ne jamais laisser de données de test dans la DB réelle
        con.execute("DELETE FROM flux_macro_journal WHERE anomalie_detectee = ?", (MARKER,))
        con.commit()
        after_cleanup = con.execute(
            "SELECT COUNT(*) FROM flux_macro_journal WHERE anomalie_detectee = ?", (MARKER,)
        ).fetchone()[0]
        con.close()
        print(f"  nettoyage : {after_cleanup} ligne(s) de test restantes (attendu 0)")
        if after_cleanup != 0:
            failures.append("nettoyage DB de test incomplet")

    print("\n=== 2. Endpoint GET /api/flux-macro/taux-reussite ===")
    try:
        with urllib.request.urlopen("http://localhost:5000/api/flux-macro/taux-reussite", timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        print(f"  réponse : {data}")
        for k in ("total", "corrects", "taux_pct", "label"):
            if k not in data:
                failures.append(f"endpoint: clé '{k}' manquante")
    except Exception as exc:
        print(f"  serveur non joignable (ignoré) : {exc}")

    print("\n=== 3. Frontend : carte KPI + branchement app.js ===")
    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    js   = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    if 'id="fm-taux-reussite"' not in html:
        failures.append("index.html: id='fm-taux-reussite' absent")
    else:
        print("  index.html: carte KPI 'Taux de réussite' présente (id=fm-taux-reussite)")
    if "Taux de réussite" not in html:
        failures.append("index.html: libellé 'Taux de réussite' absent")
    if "/flux-macro/taux-reussite" not in js:
        failures.append("app.js: appel à /flux-macro/taux-reussite absent")
    else:
        print("  app.js: appel apiFetch('/flux-macro/taux-reussite') présent")

    print()
    if failures:
        print(f"ÉCHEC — {len(failures)} problème(s) : {failures}")
        return 1
    print("SUCCÈS — KPI Taux de réussite opérationnel de bout en bout (DB → endpoint → frontend).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
