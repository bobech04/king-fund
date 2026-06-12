# 👑 King Fund — Family Office IA

Moteur de battle trading autonome. **30 traders IA** partent chacun de **500 €** et visent **10 000 €** en 30 jours — avec un Gérant Délégué (AGD-01), un Comité de Sélection, et un suivi patrimonial complet.

---

## Démarrage rapide

```bash
# 1. Dépendances
pip install flask flask-cors flask-sock apscheduler pytz yfinance fpdf2

# 2. Lancer le backend (depuis la racine du projet)
python -X utf8 backend/app.py

# 3. Ouvrir dans le navigateur
http://localhost:5000
```

> Le mot de passe est défini dans `backend/.env` → `WEB_PASSWORD=...`

---

## Architecture

```
king-fund/
├── backend/
│   ├── app.py                        # Flask — REST + WebSocket
│   ├── engine.py                     # Moteur de tick, 30 traders, SQLite
│   ├── traders/trader_01..30.py      # 30 traders IA concrets
│   ├── divisions/
│   │   ├── gerant_delegue/           # AGD-01, Comité Sélection, alertes prix
│   │   ├── investissement/           # Watchlist Graham, screener mondial, WACC
│   │   ├── middle_office/            # Desk liquidité, DSPX, corrélations
│   │   ├── banques_centrales/        # 20 banques centrales, sentiment RSS
│   │   ├── cio/                      # Allocation macro, régime MMT/RISK_OFF
│   │   ├── alpha_lab/                # Backtests signaux, facteurs académiques
│   │   └── rapports/                 # PDF investisseur, mensuel, annuel
│   └── data/
│       ├── market.py                 # Yahoo Finance (cache, rate-limit)
│       ├── patrimoine.py             # Actifs, projection retraite 2041
│       └── suivi_pru.py              # Prix de revient unitaire, alertes
├── frontend/
│   ├── index.html                    # SPA mobile-first, 10 onglets
│   └── assets/style.css             # Thème Bloomberg dark, responsive 375px
├── docs/                             # GitHub Pages (sync auto via CI)
├── database/king_fund.db             # SQLite — trades, snapshots, éliminations
└── watchdog.py                       # Surveillance santé, Telegram si crash
```

---

## Divisions & traders

| Division | Couleur | Traders | Stratégie |
|---|---|---|---|
| Investissement | 🟡 or | 01,05,08,13,16,20,24,25,27,28,30 | Fondamentaux Graham/Buffett |
| Banque Centrale | 🔵 bleu | 04,07,17,23,29 | Macro FRED, taux directeurs |
| Expert Tech | 🟢 vert | 02,06,10,14,22 | Actualités + momentum MSFT/NVDA/GOOGL |
| Expert Crypto | 🟣 violet | 03,11,15,21,26 | BTC/ETH on-chain |
| Expert Commerce | 🟠 orange | 09,12,18 | AMZN/META, retail + social |
| Morning Brief | 🩷 rose | 19 | Outlook Claude API quotidien |

---

## Dashboard — 10 onglets

| Onglet | Contenu |
|---|---|
| 📊 Bord | Vue globale : NAV, top performers, signal Bertez, Black Swan |
| 🛡 Protection | Surveillance risques, VIX, Black Swan, gouvernance |
| 📈 Croissance | Classement 30 traders, divisions, graphique performances |
| 📋 Fiscalité | Flat Tax 30%, DZD rapatriement, Stellantis, CERFA 3916 |
| 🧠 Intelligence | AGD-01, Comité Sélection, watchlist, audit, Alpha Lab |
| 🎯 Retraite | Projection 2041, apports mensuels, PRU positions réelles |
| 🌍 Marchés | Indices Asie/Europe/US, Forex, Crypto, banques centrales |
| 🏭 Secteurs | Performances sectorielles, allocation macro CIO |
| 💧 Liquidité | Score liquidité mondial (Howell), desk agents, signal bus |
| 🌅 Brief | Morning Brief 06h30 : direction marché + confiance Claude |

---

## Alertes Telegram

Le système envoie des notifications en temps réel :

| Icône | Niveau | Déclencheur |
|---|---|---|
| 🚨 | Critique | Black Swan (VIX ≥ 35), seuil prix atteint, BUY 3/3 Comité |
| ⚠️ | Warning | BUY conditionnel 2/3, sentiment CB hawkish élevé |
| 🛑 | Veto | AGD-01 bloque une décision émotionnelle |
| 🏛️ | Comité | Résultat du vote de sélection nocturne (23h00) |
| 📋 | Rapport | Rapport hebdomadaire lundi 08h00, mensuel 1er du mois |
| 💰 | Dividende | Détection coupe dividende ou paiement reçu |

---

## Accès mobile

Le dashboard est **mobile-first** et optimisé pour les écrans 375px.

**Sur votre téléphone (Wi-Fi local) :**
```
http://192.168.1.X:5000
```

**Via GitHub Pages** (lecture seule si backend déconnecté) :
```
https://bobech04.github.io/king-fund/?api=http://192.168.1.X:5000/api
```

> Appuyez sur **« Ajouter à l'écran d'accueil »** pour une icône PWA.

---

## Guide d'utilisation

Pour une utilisation au quotidien sans connaissances techniques :

**→ [GUIDE_UTILISATION.md](GUIDE_UTILISATION.md)**

Couvre : Morning Brief, alertes Telegram, validation décisions AGD-01, accès local et mobile.

---

## Commandes utiles

```bash
# Vérifier la santé du système
curl http://localhost:5000/api/maintenance/health

# Lancer le watchdog (surveille l'app, alerte Telegram si crash)
python watchdog.py

# Synchroniser frontend → docs (GitHub Pages)
python scripts/build_pages.py

# Générer un rapport investisseur PDF manuellement
curl -X POST http://localhost:5000/api/rapports/investisseur/generer
```

---

## Variables d'environnement (`backend/.env`)

```env
WEB_PASSWORD=...           # Mot de passe du dashboard
ANTHROPIC_API_KEY=...      # Claude API (Morning Brief, AGD-01, Comité)
TELEGRAM_BOT_TOKEN=...     # Alertes Telegram
TELEGRAM_CHAT_ID=...       # Chat ID destination
EIA_API_KEY=...            # Prix WTI réel (Agent Bertez) — gratuit eia.gov
```
