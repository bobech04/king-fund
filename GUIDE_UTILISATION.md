# Guide d'utilisation — King Fund
## Family Office · Tableau de bord personnel

---

## Sommaire

1. [Accéder au dashboard](#1-accéder-au-dashboard)
2. [Lire le Morning Brief](#2-lire-le-morning-brief)
3. [Répondre aux alertes Telegram](#3-répondre-aux-alertes-telegram)
4. [Valider ou refuser une décision AGD-01](#4-valider-ou-refuser-une-décision-agd-01)
5. [Suivre votre patrimoine et vos positions](#5-suivre-votre-patrimoine-et-vos-positions)
6. [Les rapports automatiques (hebdo, mensuel, annuel)](#6-les-rapports-automatiques)
7. [Repères rapides — quel onglet pour quoi](#7-repères-rapides)

---

## 1. Accéder au dashboard

### Sur votre ordinateur (réseau local)

1. Ouvrez un terminal dans le dossier `king-fund/backend` et lancez :
   ```
   python -X utf8 app.py
   ```
2. Ouvrez votre navigateur à l'adresse :
   ```
   http://localhost:5000
   ```
3. Entrez votre mot de passe (défini dans le fichier `.env`) et appuyez sur **Connexion**.

---

### Sur votre téléphone (même réseau Wi-Fi)

1. Trouvez l'adresse IP de votre ordinateur.  
   *(Windows : tapez `ipconfig` dans un terminal, notez l'adresse du type `192.168.1.X`)*
2. Sur votre téléphone, ouvrez le navigateur et tapez :
   ```
   http://192.168.1.X:5000
   ```
   *(remplacez X par votre numéro réel)*
3. Connectez-vous avec votre mot de passe.

> **Astuce mobile :** Appuyez sur **« Ajouter à l'écran d'accueil »** dans votre navigateur pour avoir une icône King Fund comme une vraie application.

---

### Depuis n'importe où (GitHub Pages)

Le dashboard est aussi disponible en ligne via GitHub Pages (accès sans serveur local, données en lecture seule).  
Pour qu'il se connecte à votre serveur, ajoutez `?api=http://192.168.1.X:5000/api` à la fin de l'URL GitHub Pages.

---

### Si le dashboard ne répond pas

Le watchdog surveille le serveur en permanence (toutes les 5 minutes). Si le serveur tombe, vous recevez automatiquement une alerte Telegram 🚨.  
Pour relancer : ouvrez un terminal et retapez `python -X utf8 app.py` depuis `backend/`.

---

## 2. Lire le Morning Brief

Le Morning Brief est un rapport automatique généré chaque matin à **06h30** par l'agent IA dédié (trader 19 — division Morning Brief).  
Il dresse un panorama de la journée à venir et indique la direction globale des marchés.

### Où le trouver

Cliquez sur l'onglet **🌅 Brief** dans la barre de navigation du bas.

### Comment l'interpréter

| Ce que vous voyez | Ce que ça veut dire | Que faire |
|---|---|---|
| **HAUSSIER** (fond vert) | Marchés orientés à la hausse. Conditions favorables aux achats. | Vous pouvez envisager des achats si le Comité confirme. |
| **BAISSIER** (fond rouge) | Marchés orientés à la baisse. Risque élevé. | Prudence. Évitez d'acheter. Renforcez l'or ou le cash. |
| **NEUTRE** (fond gris) | Pas de tendance claire. | Restez sur vos positions actuelles. |
| **Confiance 85%+** | Le système est très sûr de son analyse. | Fiez-vous au signal. |
| **Confiance < 50%** | Signal peu fiable ce matin. | Prenez-le avec précaution, vérifiez l'onglet Marchés. |

Le texte du Brief explique pourquoi : indices asiatiques (Nikkei, Hang Seng, Shanghai), décisions des banques centrales (FED, BCE, BOJ…), actualités financières importantes.

### Les indicateurs du Brief

- **Indices Asie** : donnent le ton avant l'ouverture européenne.
- **Banques centrales** : un sentiment "hawkish" (restrictif) signifie des taux qui montent → actions sous pression. Un sentiment "dovish" (accommodant) favorise les marchés.
- **Actualités** : filtrées par importance (CRITIQUE → IMPORTANT → INFO). Ne lisez que les CRITIQUES si vous êtes pressé.

> **En pratique :** Lisez le Brief chaque matin avant toute décision. Brief BAISSIER à 80% de confiance = pas d'achat aujourd'hui.

---

## 3. Répondre aux alertes Telegram

Le système vous envoie des alertes sur Telegram à différents niveaux d'urgence.  
Voici comment reconnaître chaque type et ce que vous devez faire.

---

### 🚨 Alerte CRITIQUE — Action immédiate requise

**Quand vous la recevez :**

```
🚨 BLACK SWAN HALT — VIX à 38
Tous les 30 traders sont mis en pause.
Reprise automatique quand VIX ≤ 30.
```
**Que faire :** Rien. C'est une protection automatique contre un krach. Les traders reprennent seuls quand le marché se calme.

---

```
🚨 COMITÉ : BUY CONFIRMÉ 3/3 — VPK.AS (Vopak)
Score Research : 8.2/10 | CIO : aligné | Fiscaliste : OK
Montant conseillé : 200€
```
**Que faire :** C'est le signal d'achat le plus fort possible. Ouvrez le dashboard → onglet **🧠 Intelligence** → section *Comité Sélection* pour voir les détails. Si vous avez le cash disponible, c'est le moment d'agir.

---

```
🚨 VPK.AS sous 44€ — seuil d'entrée atteint
Prix actuel : 43.20€
```
**Que faire :** Le prix d'un titre de votre watchlist est arrivé à un niveau d'achat intéressant. Consultez l'onglet **🧠 Intelligence** → *Alertes prix & Calendrier* pour les détails. Combinez avec le vote du Comité avant d'agir.

---

```
🚨 VEILLE STRATÉGIQUE — CRITIQUE
Source : Bruno Bertez
Thèmes : dette, actifs réels, liquidité
Titre : "Le marché obligataire est en train de se fracturer"
```
**Que faire :** Article d'une source stratégique signalant un risque systémique. Ouvrez l'onglet **🧠 Intelligence** → *Veille Stratégique*. Vérifiez si l'onglet **💧 Liquidité** montre un régime DANGER. Si oui, pas d'achats actions ce jour-là.

---

### ⚠️ Alerte WARNING — À consulter dans la journée

```
⚠️ COMITÉ : BUY CONDITIONNEL 2/3 — BIPC
Un expert a des réserves : Fiscaliste (complexité fiscale DZD)
```
**Que faire :** Pas d'urgence. Consultez le dashboard dans la journée. Vous pouvez acheter une petite part ou attendre le prochain vote (chaque soir à 23h00).

---

```
⚠️ Sentiment BCE hawkish élevé (score : 0.72)
Hausse de taux probable lors de la prochaine réunion
```
**Que faire :** Les obligations et les actions de croissance vont probablement baisser. Renforcez l'or si votre allocation le permet. Regardez l'onglet **💧 Liquidité** → état des banques centrales.

---

```
⚠️ Trader TRD-07 en zone d'élimination
Jour 15 — Portefeuille : 285€ (seuil : 300€)
```
**Que faire :** Informatif. Ce trader sera remplacé automatiquement. Vous n'avez rien à faire.

---

```
⚠️ Backup quotidien réussi
Fichier : king_fund_2026-06-12_04h00.db
```
**Que faire :** Bonne nouvelle, aucune action requise. Le backup automatique fonctionne.

---

### 🛑 VETO d'AGD-01 — Décision bloquée

```
🛑 VETO — AGD-01 (Dr Alexandre Redon)
Décision soumise : ACHAT TSLA 500€
Raison : décision émotionnelle — TSLA en hausse de 15% sur 3 jours,
valorisation 40% au-dessus de la valeur intrinsèque calculée.
Recommandation : attendre une consolidation à -10% minimum ou
cibler un titre Value à la place (ex : VPK.AS, score Graham 8.1/10).
```

**Que faire :**
1. Lisez attentivement la raison. AGD-01 a analysé votre décision et la juge irrationnelle ou risquée.
2. Dans la grande majorité des cas, le veto est justifié. Attendez.
3. Si vous souhaitez quand même procéder : ouvrez l'onglet **🧠 Intelligence** → *Veto émotionnel AGD-01* et forcez la décision. **Attention :** cela sera enregistré dans le Journal Audit avec votre décision et la date.

---

### 🏛️ Alerte COMITÉ — Résultat du vote du soir

Le Comité de Sélection se réunit chaque soir à **23h00** et vote sur les meilleures opportunités de la watchlist.  
Trois experts votent : **Research** (analyse fondamentale), **CIO** (contexte macro), **Fiscaliste** (impact fiscal).

```
🏛️ COMITÉ DE SÉLECTION — 12 juin 2026
─────────────────────────────────────
VPK.AS (Vopak)      : 3/3 OUI → BUY CONFIRMÉ ✅
  Research  8.2/10  : score Graham élevé, marge de sécurité 32%
  CIO               : aligné thèse macro (actifs réels, régime MMT_INFLATION)
  Fiscaliste        : Flat Tax 30% standard, traitement simple
  Montant conseillé : 200€

GTT.PA (GTT)        : 2/3 OUI → BUY CONDITIONNEL ⚠️
  Research  7.1/10  : score correct
  CIO               : réserves sur exposition EUR/USD élevée
  Fiscaliste        : OK

BIPC (Brookfield)   : 1/3 OUI → HOLD 🔵
─────────────────────────────────────
```

| Vote | Signification | Action recommandée |
|---|---|---|
| **3/3 OUI — BUY CONFIRMÉ** | Les 3 experts sont unanimes | Achetez si vous avez le cash disponible |
| **2/3 OUI — BUY CONDITIONNEL** | Un expert a des réserves | Petite position ou attendez le prochain vote |
| **1/3 OUI — HOLD** | Désaccord important | Ne faites rien pour l'instant |
| **0/3 — VETO** | Tous les experts s'y opposent | N'achetez pas |

> Le montant conseillé tient compte de votre budget, de votre allocation actuelle et du bonus SITG (bonus automatique si vos performances dépassent +10%/an).

---

### 💰 Alerte DIVIDENDE

```
💰 Dividende reçu — O (Realty Income) : 0.26$
Date de paiement : 15 juin 2026
Revenus passifs cumulés ce mois : 18.40€
```

Rien à faire, c'est de l'information. Votre portefeuille génère des revenus passifs automatiquement.

---

### 🎯 Alerte OBJECTIF DE PRIX atteint (suivi PRU)

```
🎯 Objectif atteint — VPK.AS
PRU : 41.20€ | Prix actuel : 49.80€ | PV latente : +20.9%
Objectif configuré : 48€
Envisagez une prise de bénéfice partielle.
```

**Que faire :** Consultez l'onglet **💎 Patrimoine** → *Suivi PRU*. Vous pouvez vendre une partie de la position si vous souhaitez sécuriser les gains.

---

### 🛑 Alerte STOP-LOSS atteint (suivi PRU)

```
🛑 Stop-loss atteint — DNB.OL
PRU : 295kr | Prix actuel : 278kr | MV latente : -5.8%
Stop configuré : 280kr
Décision requise : vendre ou maintenir la conviction ?
```

**Que faire :** C'est votre signal de sécurité. Soit vous vendez pour limiter la perte, soit vous maintenez si vous avez toujours confiance dans le titre à long terme. Consultez la dernière analyse du Comité sur ce titre.

---

### 📋 Rapport hebdomadaire AGD-01 (lundi matin)

Chaque **lundi à 08h00**, AGD-01 envoie un rapport complet sur Telegram.

Il contient :
- Performance de la semaine (vs CAC40, S&P500, MSCI World)
- Décisions prises et leur résultat
- État de la watchlist (signaux BUY/HOLD/SELL)
- Analyse Bertez (WTI + USD → régime macro)
- Projection de votre objectif retraite 2041

Lisez-le tranquillement le lundi matin avant de commencer la semaine.

---

## 4. Valider ou refuser une décision AGD-01

AGD-01 (Dr Alexandre Redon) est votre gérant délégué IA. Il agit comme un filtre anti-émotionnel avant vos décisions d'investissement.

### Demander l'avis d'AGD-01 sur votre propre décision

Si vous avez une idée d'achat ou de vente, demandez son avis avant d'agir :

1. Ouvrez l'onglet **🧠 Intelligence**.
2. Trouvez la section **Veto émotionnel AGD-01**.
3. Remplissez le formulaire :
   - **Ticker** : le code de l'action (ex : `AAPL`, `VPK.AS`)
   - **Action** : ACHAT ou VENTE
   - **Montant** : en euros
   - **Contexte** : pourquoi vous voulez le faire (ex : "il a monté de 10% cette semaine")
4. Appuyez sur **Évaluer**.
5. AGD-01 répond en quelques secondes.

### Comprendre la réponse

| Réponse | Ce que ça signifie |
|---|---|
| **VALIDE** ✅ | Décision rationnelle. Vous pouvez procéder. |
| **VETO** 🛑 | Décision jugée émotionnelle ou risquée. Lisez la recommandation avant d'insister. |

### Demander un vote du Comité sur un titre spécifique

Si vous voulez une analyse complète (pas juste un veto émotionnel) :

1. Onglet **🧠 Intelligence** → section **Comité Sélection**.
2. Tapez le ticker dans le champ et appuyez sur **Voter**.
3. Attendez quelques secondes — les 3 experts votent en temps réel.
4. Consultez le résultat (3/3, 2/3, etc.).

### Consulter l'historique des décisions

Toutes les décisions d'AGD-01 sont enregistrées dans le **Journal Audit** (onglet **🧠 Intelligence** → *Journal Audit AGD-01*).  
Chaque entrée est protégée par une empreinte cryptographique (symbole ⛓) : vous pouvez vérifier qu'aucune décision n'a été modifiée a posteriori.

| Badge | Signification |
|---|---|
| VALIDE ✅ | Décision approuvée |
| VETO 🛑 | Décision bloquée |
| RAPPORT 📋 | Rapport hebdomadaire envoyé |

---

## 5. Suivre votre patrimoine et vos positions

### Onglet 💎 Patrimoine

Accessible depuis la barre de navigation. Il regroupe tout ce qui concerne votre patrimoine personnel.

**Ce que vous y voyez :**

| Section | Description |
|---|---|
| **KPIs** | Total patrimoine, projection retraite 56 ans (2041), taux de progression |
| **Graphique projection** | Courbe de croissance jusqu'en 2041 (10%/an + 500€/mois) |
| **Camembert répartition** | Or physique, cash, actions, épargne dinars DZD |
| **Suivi des apports** | Chaque apport mensuel enregistré + bouton pour en ajouter |
| **Suivi PRU** | Prix de revient unitaire, PV/MV latentes, barre de progression vers objectif |
| **Fiscalité FSC-FRA-01** | Flat Tax 30% France, régime or physique (11.5%), Stellantis |
| **Fiscalité FSG-ALG-02** | Convention DZ-FR, rapatriement DZD (15 000€/an max), CERFA 3916 |

### Ajouter un apport mensuel

1. Onglet **💎 Patrimoine** → section *Suivi des apports*.
2. Appuyez sur **+ Ajouter un apport**.
3. Entrez le montant et une note (ex : "Salaire juin").
4. Appuyez sur **Valider**.

### Ajouter une transaction (achat/vente réel)

1. Onglet **💎 Patrimoine** → section *Suivi PRU*.
2. Appuyez sur **+ Nouvelle transaction**.
3. Remplissez : ticker, type (ACHAT/VENTE), quantité, prix unitaire, date.
4. Le PRU et les PV/MV latentes se recalculent automatiquement.

---

## 6. Les rapports automatiques

### Rapport hebdomadaire — Lundi 08h00

Envoyé automatiquement sur Telegram chaque lundi matin. Contient la performance de la semaine et l'analyse macro d'AGD-01.  
Pour le générer manuellement : onglet **🧠 Intelligence** → bouton *Générer rapport lundi*.

### Rapport mensuel — 1er du mois à 07h30

Envoyé sur Telegram le 1er de chaque mois. Contient le bilan complet du mois : NAV, performances, alpha vs indices, décisions AGD-01, projection retraite.  
Le PDF est disponible dans `rapports/mensuel/`.

### Rapport annuel — 31 décembre à 18h00

Envoyé sur Telegram le 31 décembre. Contient le bilan fiscal de l'année (PV imposables, Flat Tax, or, CERFA 3916 DZD) calculé depuis votre suivi PRU.  
Le PDF est disponible dans `rapports/annuel/`.

### Rapport Alpha Lab — 1er du mois à 07h00

Envoyé sur Telegram le 1er de chaque mois (avant le rapport mensuel). Contient la validation académique des signaux (Bertez, Morning Brief) : Sharpe IS/OOS, t-stat, verdict VALIDE / BRUIT / OVERFITTE.

---

## 7. Repères rapides

### Quel onglet pour quoi

| Onglet | À consulter quand… |
|---|---|
| 🏆 **Classement** | Tous les jours — qui mène la battle, qui est en difficulté |
| 🌅 **Morning Brief** | Chaque matin avant une décision — direction des marchés |
| 📊 **Post-Market** | Le soir — bilan de la journée, podium traders |
| ⚙️ **Scheduler** | Si un job semble ne pas tourner — état des 24 tâches automatiques |
| 🌍 **CIO Macro** | En cas de doute sur le contexte macro — indices, banques centrales, forex, crypto |
| 🚨 **Alertes** | Après une alerte Telegram — détail des alertes critiques/warnings en cours |
| 📈 **Investissement** | Avant un achat — watchlist Graham, screener mondial, signaux BUY |
| 💎 **Patrimoine** | Une fois par semaine — bilan patrimoine, apports, PRU, projection retraite |
| 💧 **Liquidité** | Si le marché semble agité — score Howell, régime macro mondial |
| 🧠 **Intelligence** | Après toute alerte Telegram importante — Comité, Veille Stratégique, Alpha Lab, Audit AGD-01 |

---

### Planning des événements automatiques

| Heure | Événement |
|---|---|
| **06h30** | Morning Brief généré (trader 19) |
| **08h00** (lundi) | Rapport hebdomadaire AGD-01 → Telegram |
| **H:05** (toutes les heures) | Veille Stratégique : scan RSS (Bertez, Dalio, Howell, InflationGuy) |
| **Toutes les 30 min** | Alertes prix surveillance (8h–20h) + Actualités CRITIQUE/IMPORTANT |
| **Toutes les 5 min** | Watchdog : vérification santé du serveur |
| **23h00** (quotidien) | Comité Sélection : vote sur le top 3 watchlist |
| **04h00** (quotidien) | Backup automatique base de données |
| **02h30** (quotidien) | Screener mondial : scan 120 titres |
| **1er du mois 07h00** | Rapport Alpha Lab → Telegram |
| **1er du mois 07h30** | Rapport mensuel PDF → Telegram |
| **31 décembre 18h00** | Rapport annuel fiscal PDF → Telegram |

---

### Les 6 niveaux de gravité d'une alerte Telegram

| Emoji | Niveau | Ce qu'il faut faire |
|---|---|---|
| 🚨 | **CRITIQUE** | Ouvrir le dashboard immédiatement |
| ⚠️ | **WARNING** | Consulter dans la journée |
| 🛑 | **VETO** | Lire la recommandation avant de décider |
| 🏛️ | **COMITÉ** | Consulter le résultat du vote |
| 💰 | **DIVIDENDE** | Information seulement, rien à faire |
| 📋 | **RAPPORT** | Lire le rapport hebdomadaire |

---

*Dernière mise à jour : juin 2026*
