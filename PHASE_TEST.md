# PHASE_TEST.md — Plan de démarrage

## Durée : 2-3 mois en MODE=SIMULATION · Objectif : confiance suffisante pour MODE=RÉEL

> ## ⏳ Prolongation phase test — J30 → J60 (mise à jour 30/06/2026)
>
> **Nouvelle échéance : 30 juillet 2026** (au lieu de J30 initial).
>
> **Raison de la prolongation :**
> - Bugs critiques corrigés le 30/06/2026 — délai d'observation post-correction nécessaire
> - Raspberry Pi (hébergement cible) pas encore en place
> - Régime macro **CRISE_LIQUIDITE** actif — pas le contexte pour évaluer sereinement un passage MODE=RÉEL
>
> **Conditions Go/No-Go MODE=RÉEL (toutes requises) :**
> 1. Raspberry Pi stable **7 jours** consécutifs (hébergement cible en place et fiable)
> 2. Régime macro de retour à **SEREIN** (sortie confirmée de CRISE_LIQUIDITE)
> 3. **0 bug critique** pendant **30 jours** consécutifs
>
> Voir `CRITERES_SUCCES.md` pour le détail des critères qualitatifs inchangés.

---

## Avant J0 — Checklist pré-lancement (une seule fois)

### 1. Fichier `.env` complet

Ouvrir `backend/.env` et vérifier que chaque ligne est renseignée :

```env
SECRET_KEY=<une longue chaîne aléatoire>
WEB_PASSWORD=<ton mot de passe dashboard>
TELEGRAM_BOT_TOKEN=<token BotFather>
TELEGRAM_CHAT_ID=<ton chat ID>
ANTHROPIC_API_KEY=<clé Anthropic>
EIA_API_KEY=<clé EIA — gratuit sur eia.gov/opendata>
```

> Si une clé est manquante, l'agent correspondant fonctionnera en mode dégradé (fallback Yahoo Finance pour EIA, pas d'alertes sans Telegram).

---

### 2. Dépendances Python

```bash
cd backend
pip install -r requirements.txt
```

Vérifier que `fpdf2` est bien installé (pour les rapports PDF).

---

### 3. Base de données initiale

```bash
# Option rapide — catalogue seulement (recommandé pour commencer)
python database/init_history.py --mode crises-only

# Option complète (20-30 min, à faire une fois le système validé)
python database/init_history.py
```

---

### 4. Test Telegram

Lancer le backend une première fois et vérifier qu'un message arrive sur Telegram :

```bash
cd backend
python -X utf8 app.py
```

Chercher dans les logs : `[Telegram] ✅ démarrage` — si absent, vérifier `TELEGRAM_BOT_TOKEN` et `TELEGRAM_CHAT_ID`.

---

### 5. Accès mobile vérifié

Sur ton téléphone (même Wi-Fi) : ouvrir `http://192.168.1.X:5000` → page login visible → connexion réussie.

---

## J0 — Démarrage de la phase test

### Terminal 1 — Backend principal

```bash
cd Documents/king-fund/backend
python -X utf8 app.py
```

Garder ce terminal ouvert. Le serveur est prêt quand tu vois :
```
* Running on http://0.0.0.0:5000
[Scheduler] 24 jobs planifiés
[Engine] Tick 1 démarré — 30 traders actifs
```

### Terminal 2 — Watchdog (optionnel mais recommandé)

Dans un deuxième terminal :
```bash
cd Documents/king-fund
python watchdog.py http://localhost:5000
```

Le watchdog ping `/api/maintenance/health` toutes les 5 min et alerte Telegram si 3 échecs consécutifs.

---

### Vérifications J0 (dans les premières heures)

| Vérification | Où regarder | Attendu |
|---|---|---|
| 30 traders actifs | Dashboard → 🏆 Classement | 30 lignes, PnL en cours |
| Morning Brief généré | Dashboard → 🌅 Brief | Texte présent (si après 06h30) |
| Backup SQLite | Logs terminal | `[Backup] ✅` à 04h00 le lendemain |
| Alertes Telegram reçues | Ton Telegram | Au moins 1 message dans la journée |
| Signal Bertez | Dashboard → 🧠 Intelligence | Section Bertez : régime affiché |

---

## Routine quotidienne (5-10 min par jour)

### Matin (après 06h30)

1. Lire le **Morning Brief** (onglet 🌅 Brief) — direction du jour, confiance %.
2. Vérifier les **alertes Telegram** reçues depuis la nuit — traiter les CRITIQUE en premier.
3. Si Comité soir précédent a voté → voir le résultat dans onglet 🧠 Intelligence.

### Soirée (optionnel)

4. Parcourir **Post-Market** (onglet 📊) — podium du jour, performance par secteur.
5. Jeter un œil au **Scheduler** (onglet ⚙️) — tous les jobs en vert ?

---

## Revue hebdomadaire (lundi matin, 15 min)

Le rapport AGD-01 arrive automatiquement sur Telegram à **08h00**.

Lire et noter dans un carnet (ou fichier texte) :
- Performance semaine vs CAC40/S&P500
- Les 3 recommandations BUY/SELL — semblaient-elles raisonnables ?
- Un véto AGD-01 a-t-il évité une erreur ou raté quelque chose ?
- Le régime macro (MMT_INFLATION, RISK_ON…) était-il cohérent avec l'actualité ?

> Pas de calcul statistique. Juste : "est-ce que ça m'a semblé sensé cette semaine ?"

---

## Revue mensuelle (1er du mois, 30 min)

Le rapport mensuel PDF arrive automatiquement sur Telegram à **07h30**.

Vérifier point par point les critères de `CRITERES_SUCCES.md` :

**Opérationnel :**
- [ ] Crashes bloquants ce mois ? (si oui → noter le contexte exact)
- [ ] Alertes Telegram : ni trop ni trop peu ?
- [ ] Dashboard accessible depuis le mobile / Algérie ?
- [ ] Backup quotidien OK ? (vérifier `database/backups/` — 30 fichiers max)

**Cohérence macro :**
- [ ] Le signal Bertez a-t-il changé de régime ce mois ? Était-ce cohérent ?
- [ ] L'Alpha Lab a-t-il validé ou invalidé un signal ?

**Investissement :**
- [ ] Le Comité a-t-il proposé au moins un BUY intéressant ?
- [ ] Un agent est-il resté totalement silencieux ? → passer en mode silencieux si oui.

---

## Si quelque chose se casse

### Crash backend (serveur mort)

```bash
cd Documents/king-fund/backend
python -X utf8 app.py
```

Les données SQLite sont intactes — les traders reprennent là où ils en étaient.

### Trader bloqué / comportement bizarre

```bash
# Logs du trader en question
grep "TRD-07" logs/king_fund_YYYY-MM-DD.log
```

Si un groupe entier (A/B/C) dérive → investiguer le code avant d'éliminer.

### Telegram silencieux depuis plus de 24h

Vérifier `/api/maintenance/health` dans le navigateur → champ `telegram_ok`.  
Si `false` : vérifier que le token/chat_id sont corrects dans `.env`.

### Dashboard inaccessible depuis mobile

1. Vérifier que le backend tourne (terminal).
2. Vérifier l'IP locale (`ipconfig` → adresse 192.168.x.x).
3. En dernier recours : GitHub Pages `?api=http://IP:5000/api`.

---

## Fin de phase — Décision GO / NO-GO

À l'issue de la phase test (échéance **30 juillet 2026**, prolongée depuis J30 → J60 — voir encadré en tête de document), relire `CRITERES_SUCCES.md` de haut en bas.

**Conditions Go/No-Go MODE=RÉEL (toutes requises depuis la prolongation du 30/06/2026) :**
1. Raspberry Pi stable 7 jours consécutifs
2. Régime macro repassé à SEREIN (sortie de CRISE_LIQUIDITE)
3. 0 bug critique pendant 30 jours consécutifs

Si les 3 conditions ci-dessus sont remplies, la seule vraie question reste la **section 6** de `CRITERES_SUCCES.md` :

> *Comprends-tu ce que fait le système à tout moment ?*  
> *Fais-tu confiance pour basculer MODE=RÉEL avec de l'argent qui compte pour ta retraite ?*

Si **OUI** sur les deux → passer en MODE=RÉEL (modifier `config.py` ou `.env` selon l'implémentation).

Si **NON** (ou si une des 3 conditions ci-dessus échoue) → noter précisément ce qui manque en confiance (un agent ? une alerte ? une incompréhension ?) et traiter ce point avant de basculer. Pas de délai imposé au-delà du 30/07/2026.

---

*Créé le 12 juin 2026 — Prolongé le 30 juin 2026 (J30 → J60, échéance 30 juillet 2026)*
