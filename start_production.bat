@echo off
REM King Fund — Serveur de production Windows (Waitress)
REM Usage : double-clic ou "start_production.bat" depuis la racine du projet
REM Pour le dev local, utiliser : cd backend && python app.py

cd /d "%~dp0backend"

echo [King Fund] Demarrage serveur Waitress (production)...
echo [King Fund] URL : http://localhost:5000
echo [King Fund] Ctrl+C pour arreter

REM "waitress-serve" depend du Scripts/ de Python etant dans le PATH (souvent absent
REM sur une install utilisateur fraiche). "python -m waitress" est equivalent et
REM fonctionne toujours avec l'interpreteur courant, sans dependre du PATH.
python -m waitress --host=0.0.0.0 --port=5000 --threads=4 app:app
