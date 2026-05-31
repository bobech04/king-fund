"""
Synchronise frontend/ → docs/ pour GitHub Pages.
Preserves docs/config.js (contient l'URL API utilisateur).

Usage:  python scripts/build_pages.py
"""

import shutil
from pathlib import Path

ROOT     = Path(__file__).parent.parent
FRONTEND = ROOT / "frontend"
DOCS     = ROOT / "docs"

PRESERVE = {"config.js", "manifest.json", "_config.yml"}

def sync():
    DOCS.mkdir(exist_ok=True)
    (DOCS / "assets").mkdir(exist_ok=True)

    # Copie index.html et app.js
    for name in ("index.html", "app.js"):
        src = FRONTEND / name
        dst = DOCS / name
        shutil.copy2(src, dst)
        print(f"  ✓ {name}")

    # Copie assets/ (sauf fichiers préservés)
    for src in (FRONTEND / "assets").iterdir():
        dst = DOCS / "assets" / src.name
        shutil.copy2(src, dst)
        print(f"  ✓ assets/{src.name}")

    print("\nDocs mis à jour. Fichiers préservés:", ", ".join(PRESERVE))
    print("Vérifiez docs/config.js pour l'URL de votre backend.")

if __name__ == "__main__":
    print("Synchronisation frontend/ → docs/")
    sync()
    print("\nGitHub Pages prêt. Poussez vers GitHub et activez Pages (branch: main, folder: /docs).")
