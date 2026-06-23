# DEPLOY — Mise en service sur le banc de test FXS (Raspberry Pi)

But : faire tourner **notre application** (superviseur Flask + mesure par port + IA)
sur le banc de production, **sans toucher** aux scripts de prod, et en validant que
`fxs_real.py` lit le matériel aussi bien que les scripts d'origine.

> Rappel de cadrage : notre app **remplace le superviseur LabVIEW**. Les scripts
> `script reel_fxs/` restent la **référence** (oracle de validation), on n'y touche pas.

---

## Dossiers prêts à copier (générés par `build_deploy.py`)

Deux dossiers SD prêts à l'emploi sont **générés** depuis les sources — ne pas les
éditer à la main :

- **`deploy_premier_test/`** — premier test / validation (`DEMO_MODE=True`, inclut
  `validate_fxs_real.py`).
- **`deploy_test_final/`** — test final / prod (`DEMO_MODE=False`, inclut
  `fxs_app.service` + ce `DEPLOY.md`).

➡️ **Après TOUTE modification d'un fichier source** (`app.py`, `fxs_real.py`,
`fxs_ai.py`, `database.py`, dashboard, modèle…), **régénérer les dossiers** :

```bash
python build_deploy.py
```

Sinon les copies sur la carte SD sont périmées. Le script copie le cœur applicatif
+ assets + modèle, règle `DEMO_MODE` par dossier, et **préserve** les `LISEZMOI.md`.
(`build_deploy.py` est un outil de dev : il n'est pas copié sur la carte SD.)

---

## 0. Stratégie carte SD — TRAVAILLER SUR UN CLONE

- **NE PAS** utiliser une carte vierge avec juste nos fichiers : on perdrait
  l'environnement déjà configuré (I2C activé, libs Adafruit, `raspi-gpio`, config Pi).
- **NE PAS** installer nos dépendances sur la carte de PROD (risque de casser
  l'environnement de mesure existant en upgradant numpy/scikit-learn).
- ✅ **CLONER la carte SD de prod**, puis travailler sur le clone :
  1. Éteindre le Pi, sortir la carte de prod.
  2. Faire une **image** de la carte (Raspberry Pi Imager / Win32DiskImager / `dd`).
  3. Écrire l'image sur une **nouvelle carte** (taille ≥ l'originale).
  4. Démarrer le Pi sur le **clone** ; ranger l'originale comme **backup intact**.
  5. Ajouter `fxs_app/` au clone et installer les dépendances **sur le clone**.
- Étiqueter physiquement les cartes : `PROD (backup)` vs `APP (test)`.

---

## 1. Quoi uploader (dans un dossier séparé)

Créer `/home/pi/fxs_app/` (NE PAS écraser `script reel_fxs/`) :

```
fxs_app/
├── app.py                 # Superviseur Flask (REST + WebSocket)
├── fxs_real.py            # Mesure par port (transcription des scripts prod)
├── fxs_ai.py              # Scoring IA (Isolation Forest) + explicabilité
├── database.py            # Persistance SQLite
├── fxs_iso.joblib         # Bundle modèle entraîné
├── validate_fxs_real.py   # Validation auto fxs_real ↔ scripts prod (§4)
├── fxs_app.service        # Unité systemd (§5)
├── requirements.txt       # Dépendances pip (§2)
├── templates/
│   └── index.html         # Dashboard web
└── static/
    ├── css/style.css
    └── js/dashboard.js
```

Fichiers à NE PAS uploader : `TESTF.py`, `TEST4.py`, `make_ia.py`, le CSV dataset,
le dossier `fxs-mobile/` (l'app mobile tourne sur le téléphone, pas sur le Pi).

---

## 2. Dépendances Python (sur le clone)

Déjà présentes (utilisées par les scripts de prod) : `adafruit_ads1x15`, `board`,
`busio`, et la commande `raspi-gpio`. `fxs_real` utilise la **même** pile.

À installer en plus (fichier `requirements.txt` fourni) :
```bash
cd ~/fxs_app && python3 -m pip install -r requirements.txt
```
> ⚠️ Sur le Pi, `python` = **Python 2** : toujours utiliser **`python3`** et
> **`python3 -m pip`** (notre app est en Python 3 : f-strings, Adafruit CircuitPython…).

Contenu : `flask`, `flask-socketio`, `simple-websocket` (transport WebSocket requis
par l'app mobile), `numpy`, `joblib`, `scikit-learn`.

⚠️ **scikit-learn** peut être long à installer sur Pi et doit être proche de la
version **1.8.0** (celle du bundle) pour éviter l'avertissement de dépicklage.
Si c'est bloquant : **l'app fonctionne sans** — `fxs_ai` se dégrade proprement
(le dashboard affiche « IA indisponible ») et **toutes les mesures continuent**.
→ Faire marcher la mesure d'abord, ajouter l'IA ensuite.

---

## 3. Configuration

- **`app.py`** : `DEMO_MODE = True` lance le **simulateur** (utile pour vérifier
  l'UI sans matériel). Passer à **`DEMO_MODE = False`** pour la **mesure réelle**.
  En réel, `fxs_real` auto-détecte le Pi (ADS1115 + `raspi-gpio`).
- **App mobile** : `fxs-mobile/src/constants/config.js` →
  `API_URL = 'http://<IP_DU_PI>:5000'` (trouver l'IP via `hostname -I`).

### Sonnerie déportée sur le PC (station de test-final) — optionnel

Sur une station **TF**, le Pi est embarqué/figé dans le banc et le **gateway
(DUT) change à chaque unité testée**. Pour ne **jamais reconfigurer le Pi** par
gateway, on déporte la commande de sonnerie sur le **PC** (operator station) :
toute la connaissance du gateway (IP, login, pays, `scos-voice`) vit côté PC, et
le Pi se contente de demander « ring start / ring stop » en HTTP. `fxs_real.py`
n'a rien à changer. (Bénéfice secondaire : lien PC↔gateway plus fiable.)

```
Pi (fxs_real) ──HTTP──► PC (gateway_server.py) ──Telnet──► gateway 192.168.5.1
```

1. **PC** (doit pouvoir `ping 192.168.5.1`) : `python gateway_server.py`
   (écoute sur le port `5050`).
2. **Pi** : pointer vers le PC avant de lancer l'app —
   `export FXS_GW_URL=http://<IP_DU_PC>:5050` (ou décommenter la ligne
   `Environment=FXS_GW_URL=...` dans `fxs_app.service`).

Vérif : `curl http://<IP_DU_PC>:5050/health` → `{"ok": true, ...}`.
Tolérant : PC ou gateway injoignable → warning, la mesure continue (sonnerie
manuelle possible). `FXS_GW_URL` non défini = comportement historique (Telnet Pi).

---

## 4. ÉTAPE CRITIQUE — valider `fxs_real` contre les scripts de prod

`fxs_real` est une **copie fidèle** de la logique des scripts, mais jamais exécutée
sur le banc réel. Avant de lui faire confiance, comparer une fois, carte de
référence connue :

### a) Mesure par mesure (la plus directe)
```bash
# Valeur de référence (script de prod) :
cd ~/script\ reel_fxs && python3 TR_FXS1.py        # ex. -> 47.2 V

# Notre équivalent :
cd ~/fxs_app && python3 -c "import fxs_real,logging; logging.disable(99); \
b=fxs_real._Bench(simulate=False); print('TR_FXS1 =', fxs_real.measure_tr(b,'FXS1'))"
```
Répéter pour :
- `CourantLigne_FXS1.py` ↔ `fxs_real.measure_cl(b,'FXS1')` (mA)
- `Ring_FXS1.py` ↔ `fxs_real.measure_ring(b,'FXS1')` (Vrms)
- `Trans1000_FXS1.py` ↔ `fxs_real.measure_trans(b,'FXS1',1000)` (dB)
- … et les variantes **FXS2**.

### b) Gateway complet
```bash
cd ~/fxs_app && python3 fxs_real.py     # exécute 1 gateway (FXS1+FXS2), affiche le JSON
```

### b') Tout valider en une commande (RECOMMANDÉ)
```bash
cd ~/fxs_app && python3 validate_fxs_real.py --scripts-dir "/home/pi/script reel_fxs"
```
Exécute les **8 comparaisons** (TR/CL/Ring/Trans × FXS1/FXS2) entre `fxs_real` et
les scripts de prod, et affiche un tableau `fxs_real | prod | Δ | Δ% | verdict`.
Code de sortie 0 si tout est OK. (Hors banc : `--simulate` pour tester le harnais.)
Tolérances : `--tol 0.05` (V/mA/Vrms), `--abs-tol-db 0.5` (dB).

### c) Si une valeur diffère
Ajuster **dans `fxs_real.py`** (jamais dans les scripts de prod) :
- **Étalonnage** : `×100` (TR), `×120` (Ring), `K=98/100` & `/470` (CL),
  `−20·log10(Vs/Ve)` (Trans).
- **Temporisations** : les `time.sleep(...)` (copiés des scripts ; un settling trop
  court fausse la lecture).
Quand les valeurs **coïncident** avec les scripts → l'IA et les dashboards sont
déjà câblés, rien d'autre à faire.

---

## 5. Lancer l'application

```bash
cd ~/fxs_app
python3 app.py                # -> http://0.0.0.0:5000
```
- Dashboard web : `http://<IP_DU_PI>:5000`
- App mobile : ouvrir l'app (Expo) avec `API_URL` pointant sur le Pi.

(Optionnel) Démarrage auto via `systemd` — le fichier `fxs_app.service` est fourni :
```bash
sudo cp ~/fxs_app/fxs_app.service /etc/systemd/system/fxs_app.service
sudo systemctl daemon-reload
sudo systemctl enable --now fxs_app      # démarre + au boot
journalctl -u fxs_app -f                 # logs
sudo systemctl stop fxs_app              # AVANT de relancer LabVIEW (cf. §6)
```
(Si `raspi-gpio set` est refusé sous l'utilisateur `pi`, passer `User=root` dans le
fichier — voir le commentaire dedans.)

---

## 5 bis. App mobile — sur le TÉLÉPHONE, pas sur le Pi

Le banc (Pi) héberge le **backend + le dashboard WEB**. L'**app mobile** (`fxs-mobile/`,
Expo / React Native) tourne sur le **téléphone** et se connecte au Pi **par le réseau**.
Elle n'a donc **rien à faire sur la carte SD** — ne pas la copier dans `fxs_app/`.

```
   Raspberry Pi (carte SD)                     Téléphone
   ├── backend (app.py, fxs_real…)             └── fxs-mobile/ (app Expo)
   ├── dashboard WEB (templates/ + static/)         API_URL → IP du Pi
   └── sert http://<IP_DU_PI>:5000  ◄──────── connexion WiFi (même réseau)
```

Mise en route côté téléphone (depuis le poste de dev, **pas** le Pi) :
1. Éditer `fxs-mobile/src/constants/config.js` :
   `API_URL = 'http://<IP_DU_PI>:5000'` (IP du Pi via `hostname -I`).
2. `cd fxs-mobile && npx expo start` puis scanner le QR avec **Expo Go**
   (téléphone et Pi sur le **même réseau WiFi**).
3. (Option démo finale) générer un **APK** : `npx expo run:android` / build EAS.

> Le **dashboard web** (servi par le Pi) et l'**app mobile** affichent les mêmes
> données (mêmes API REST + WebSocket). Web = aucune install côté client ;
> mobile = app installable, pratique pour la démonstration.

---

## 6. Règles d'exploitation (IMPORTANT)

- **Ne jamais faire tourner LabVIEW (prod) et notre app EN MÊME TEMPS** : les deux
  pilotent les **mêmes GPIO + le même bus I2C**. Ils se battraient pour les pins/le
  bus et fausseraient les mesures. Lancer l'un **ou** l'autre.
- **Aucune LED matérielle** sur le banc : le « Mesures effectuées » des dashboards
  est un **témoin logiciel** (allumé = mesure faite), il ne pilote aucun GPIO.
- Permissions : si erreurs I2C/GPIO, vérifier que l'utilisateur est dans les
  groupes `i2c`/`gpio` (déjà OK sur la carte de prod clonée).

---

## 7. Récapitulatif — quoi changer / quoi ne pas toucher

| Action | Fichier | Toucher les scripts prod ? |
|---|---|---|
| Corriger une lecture / un étalonnage | `fxs_real.py` | ❌ Non |
| Ajuster les temporisations | `fxs_real.py` | ❌ Non |
| Activer la mesure réelle | `app.py` (`DEMO_MODE=False`) | ❌ Non |
| Pointer le mobile sur le Pi | `config.js` (`API_URL`) | ❌ Non |
| Référence de validation | `script reel_fxs/*` (lecture seule) | ❌ Non |

**En une phrase :** clone de la carte de prod → dossier `fxs_app/` séparé →
valider `fxs_real` contre les scripts → lancer `app.py`. Les scripts de prod
restent intacts, tout le réglable est dans **nos** fichiers.
