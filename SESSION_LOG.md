# Journal de session — modifications & corrections

Date : 2026-06-22. Voir aussi [SETUP.md](SETUP.md) (exploitation) et
[CHANGES_CONSO.md](CHANGES_CONSO.md) (détail mesure consommation).

Ce document liste **ce qui a été changé** et **les problèmes rencontrés puis corrigés**
pendant la mise au point du banc.

---

## A. Modifications de code

### 1. Transmission — perte de 1 dB (FXS1 & FXS2)
- **Fichier** : `fxs_real.py` → `measure_trans()`
- La valeur mesurée se voit retrancher **1 dB** (`x − 1`) AVANT l'analyse du verdict
  (limites 1000 Hz : 8,1–10,1 dB).
- Forme finale (one-liner) :
  ```python
  return -20.0 * math.log10(vs / ve) - 1.0   # -> dB (atténuation) − 1 dB de perte (FXS1 & FXS2)
  ```
- Historique : d'abord FXS1 seul, puis demandé aussi sur FXS2 → appliqué aux deux.

### 2. Sonnerie — ré-armement par port (correctif clé)
- **Fichier** : `fxs_real.py` → phase SONNERIE de `run_gateway_test()`
- **Problème** : le gateway ne sonne qu'**une rafale** (~1,5 s) par `ring start`, pas une
  cadence répétée. FXS1 (mesuré en 1er) consommait la rafale ; FXS2 ne voyait que le silence
  → FAIL injustifié.
- **Tentatives** :
  1. ❌ Re-déclencher `ring start` **+ `ring stop`** par port → le toggle stop/start **fige
     la sonnerie** : les DEUX ports échouaient. (annulé)
  2. ❌ Espacer les lectures de 1 s → inutile (rien à rattraper, pas de cadence).
  3. ✅ **Re-déclencher `ring start` avant CHAQUE port, SANS `ring stop` entre eux** ; un seul
     `ring stop` à la fin (après FXS2). → FXS1 **et** FXS2 passent.
- Détail : `ring_on(gw)` est désormais **dans** la boucle des ports ; le `ring_off(gw)` reste
  unique, après la boucle. Ajout aussi d'une attente de 1 s après chaque essai.

### 3. Chargement automatique de `.env`
- **Fichiers** : `app.py` (fonction `_load_dotenv()` exécutée AVANT l'import de
  `gateway_voice`) + nouveau fichier **`.env`**.
- **But** : ne plus avoir à faire `export FXS_GW_URL=...` à la main. `app.py` lit `.env`
  (`FXS_GW_URL=http://192.168.100.50:5050`) dans son propre process.
- `os.environ.setdefault` → un `export` explicite garde la priorité.
- ⚠️ `python3 fxs_real.py` (standalone) ne charge **pas** `.env` ; pour ce cas, la variable
  a été aussi mise dans `~/.bashrc` sur le Pi.

### 4. Démarrage automatique des services
- **Pi** : `fxs_app.service` (systemd) — chemins corrigés vers `/home/pi/deploy_test_final`,
  `FXS_GW_URL` intégré. Activé : `sudo systemctl enable --now fxs_app`.
- **PC** : `run_gateway_server.bat` (utilise `C:\Python313\python.exe`) + raccourci dans le
  dossier **Startup** de Windows → lance `gateway_server.py` à l'ouverture de session.

### 5. Mesure de consommation — RESTAURÉE (2026-06-22)
- Voir [CHANGES_CONSO.md](CHANGES_CONSO.md). Après le revert de `fxs_real.py`, la conso
  manquait dans ce fichier (mais existait dans `database.py`, `app.py`, UI) → carte vide.
- **Restaurée dans `fxs_real.py`** : détection INA219 (`HAVE_INA219`), `CONSO_MIN/MAX = 7/20 W`,
  `_CONSO_PREP`, `read_power()`/`_sim_power()`, `measure_conso()`, **Phase 4** dans
  `run_gateway_test` (remplit `conso_w` + `power`, verdict `pass_conso`), `total_steps = 9`.
- Tous les fichiers sont de nouveau **cohérents** ; la carte « 5. Consommation » se remplit.

---

### 7. Analyse IA — évaluation honnête + amélioration A+D (2026-06-23)

**Évaluation honnête du modèle actuel (Isolation Forest, 8 features) :**
- C'est un **détecteur d'anomalie / d'atypicité au moment du test**, PAS un prédicteur de
  panne future : aucun modèle temporel/de tendance.
- Il **ignore la consommation** et les 300/3400 Hz (modèle figé à 8 features ; il faudrait
  réentraîner pour les inclure).
- FXS2 est souvent **imputé/dupliqué** depuis FXS1 → signal plus faible.
- Verdict quasi binaire (`score < seuil`), sans gradation de sévérité ni validation
  précision/rappel.

**Amélioration implémentée (A + D) — COMPLÉMENT déterministe, le modèle n'est PAS modifié
ni réentraîné (`fxs_iso.joblib` inchangé) :**
- **A — Marge-au-seuil** (`fxs_ai.margins_to_limit`) : distance (%) de chaque mesure à son
  seuil le plus proche (50% = centre de bande, 0% = sur le seuil, <0 = hors bande). 100%
  arithmétique, aucune ML.
- **D — Sévérité** : `ai_severity` ∈ {OK, WATCH, ALERT, FAIL}, combinant seuils + marge + IA.
  Seuils réglables : `_ALERT_MARGIN = 8.0`, `_WATCH_MARGIN = 18.0` (% de bande).
- Nouveaux champs `ai_*` : `ai_severity`, `ai_min_margin`, `ai_min_margin_measure`,
  `ai_margins`, + (déjà ajoutés) `ai_relevant`, `ai_recommendation`.
- Recommandation maintenance désormais pilotée par la sévérité (ex. « ALERTE : Tension repos
  FXS1 très proche du seuil (marge 5%) → risque imminent »).
- **Persistés en base** : `ai_recommendation`, `ai_relevant`, `ai_severity`, `ai_min_margin`
  (colonnes ajoutées + migration). L'IA ne s'affiche en détail que pour les cartes **PASS**
  (sur ECHEC, la cause est déterministe par les seuils → score/cause masqués).
- **UI** : carte IA pilotée par la sévérité (couleur OK/WATCH/ALERT/FAIL) + ligne « marge
  mini au seuil », dans l'app React (`AICard`) et le dashboard Flask. Historique (React +
  Flask) affiche verdict + recommandation.

**Reste pour une VRAIE prédiction dans le temps (non fait) :**
- **C — Suivi par numéro de série** : stocker les mesures d'une unité au fil des re-tests et
  détecter une tendance vers le seuil (pente → limite). Seule option réellement *prédictive* ;
  c'est un projet à part (nécessite le tracking par série).
- **B — Réentraîner** avec `conso_w` + 300/3400 Hz pour lever les angles morts du modèle.

---

## B. Réseau & infrastructure

### 6. IP statique du Pi (correctif d'accès au dashboard)
- **Problème** : le Pi avait une IP **APIPA `169.254.179.72`** (pas de bail DHCP), sur un
  autre sous-réseau que le PC (`192.168.100.0/24`). Le Pi joignait le PC (il initie), mais le
  **PC ne pouvait pas joindre le Pi** → dashboard inaccessible depuis le navigateur.
- **Fix** : IP statique **`192.168.100.10/24`** sur `eth0` du Pi (même sous-réseau que le PC).
  - Test immédiat : `sudo ip addr add 192.168.100.10/24 dev eth0`
  - Permanent : NetworkManager (`nmtui` / `nmcli`) ou `/etc/dhcpcd.conf`.
- Dashboard désormais : **http://192.168.100.10:5000**.

---

## C. Problèmes rencontrés & corrigés (récapitulatif)

| # | Problème | Cause | Correction |
|---|---|---|---|
| 1 | Serveur PC « ne démarre pas » | mauvais interpréteur Python (3.11/Store sans Flask) | utiliser `C:\Python313\python.exe` |
| 2 | `Address already in use :5000` | un `app.py` déjà lancé | `pkill -f app.py` / `systemctl` |
| 3 | Sonnerie KO `No route to host` | `python3 fxs_real.py` sans `FXS_GW_URL` → mode local, Pi telnet direct le gateway | lancer via `app.py` ; `.env` + `~/.bashrc` |
| 4 | `502 BAD GATEWAY` sur `/session/open` | PC ne joignait pas (momentanément) le gateway `192.168.5.1` | vérifier lien PC↔gateway (`ping`, `python gateway_voice.py`) |
| 5 | Dashboard inaccessible | Pi en IP APIPA `169.254.x.x` | IP statique `192.168.100.10` |
| 6 | `heredoc` qui ne se ferme pas (`> ^C`) | `EOF` collé avec des espaces devant | méthode `printf` insensible à l'indentation |
| 7 | Sonnerie FXS2 KO puis les DEUX KO | rafale unique consommée par FXS1 ; puis toggle `ring stop/start` fige la sonnerie | re-`ring start` par port **sans** `ring stop` entre eux |
| 8 | Modif de code sans effet sur le Pi | service systemd garde l'ancien module en mémoire | `sudo systemctl restart fxs_app` (+ `rm -rf __pycache__`) |

---

## D. Points d'attention pour la suite

- **Synchronisation PC → Pi** : le Pi a sa **propre copie** des fichiers. Toute modif côté PC
  doit être recopiée (`scp`) ou refaite sur le Pi, puis `systemctl restart fxs_app`.
- **Base de données** : sur le Pi uniquement (`fxs_tests.db`). Pas de sauvegarde hors-Pi.
- **Consommation** : restaurée dans `fxs_real.py` (voir A.5) — cohérente partout.
- **IA** : complément déterministe A+D ajouté (voir A.7). Reste optionnel : **C** (suivi par
  n° de série = vraie prédiction temporelle) et **B** (réentraîner avec conso + 300/3400 Hz).
  Le modèle Isolation Forest reste figé à 8 features (A+D ne le modifient pas).
