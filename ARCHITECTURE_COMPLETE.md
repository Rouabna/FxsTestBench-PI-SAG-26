# Banc de Test FXS — Architecture complète, communication & déploiement

> Document de référence **global** : qui est qui, quelle IP, qui parle à qui, par
> quel câble / quel Wi-Fi, comment tout démarre, et comment industrialiser
> l'application mobile (sans `npx expo start` + QR à chaque fois).
>
> Voir aussi : [SETUP.md](SETUP.md) (exploitation), [SONNERIE_DEPORTEE.md](SONNERIE_DEPORTEE.md)
> (pilotage gateway), [DEMARRAGE_AUTO.md](DEMARRAGE_AUTO.md) (démarrage auto), [GIT.md](GIT.md).

---

## 1. Les 4 acteurs (qui est qui)

| # | Acteur | Rôle | Programme | Où il tourne |
|---|--------|------|-----------|--------------|
| 1 | **Raspberry Pi** | Cerveau de **mesure** + serveur web/API | `app.py` (Flask + SocketIO) → appelle `fxs_real.py` (mesures ADS1115/GPIO) + `fxs_ai.py` (IA) | Embarqué et **figé** dans le banc |
| 2 | **PC** (poste opérateur) | 1) **Pilote le gateway** (sonnerie/p2p)  2) sert de **pont réseau** pour le téléphone | `gateway_server.py` (port 5050) + `bridge.js` (port 5000) | Poste de l'opérateur |
| 3 | **Gateway (DUT)** | L'**unité testée**. Change à chaque test. | Firmware `scos-voice` (commandé en Telnet) | Sur le banc, branché par câble |
| 4 | **Application** (UI) | Affiche les mesures, bouton **DÉMARRER** | Dashboard web (servi par le Pi) **ou** app mobile Expo (`fxs-mobile`) | Navigateur PC **ou** téléphone |

**Idée maîtresse :** sur une station de **test-final**, le **Pi ne bouge jamais**
(c'est l'instrument de mesure), mais le **gateway change à chaque unité**. On ne
veut donc pas reconfigurer le Pi par gateway → toute la connaissance du gateway
(IP, login, commandes) vit **sur le PC**. Le Pi demande juste « fais sonner ».

---

## 2. Le réseau — 3 segments séparés (le détail des IP)

Le PC est la **plaque tournante** : il possède **3 cartes réseau** et appartient
aux 3 réseaux à la fois. C'est lui qui relie tout.

```
                        ┌──────────────────────────── PC (3 cartes réseau) ────────────────────────────┐
                        │                                                                               │
  📱 Téléphone          │   Wi-Fi : 10.235.225.56        Ethernet : 192.168.100.50    Ethernet 2 :      │
  (Wi-Fi usine)  ◄─────►│        (DHCP, change)                (fixe)                  192.168.5.100     │
  10.235.225.x          │                                                                 (fixe)         │
                        │   bridge.js (port 5000)      gateway_server.py (port 5050)                     │
                        └───────┬───────────────────────────┬──────────────────────────────┬───────────┘
                                │ câble Ethernet direct      │ (même câble que ──►)          │ câble Ethernet direct
                                │ 192.168.100.0/24           │                               │ 192.168.5.0/24
                                ▼                            ▼                               ▼
                     🍓 Raspberry Pi (eth0)        (le Pi appelle le PC en       🔌 Gateway / DUT
                        192.168.100.10               HTTP sur :5050)                192.168.5.1
                        app.py (port 5000)                                          (scos-voice, Telnet :23)
```

### Tableau des IP (à réserver en **fixe**)

| Machine / interface | IP | Réseau | Rôle |
|---|---|---|---|
| **Pi** `eth0` | `192.168.100.10` | B (câble Pi↔PC) | dashboard + API + mesures |
| **PC** `Wi-Fi` | `10.235.225.56` ✅ **fixe** | A (Wi-Fi usine) | pont pour le téléphone |
| **PC** `Ethernet` | `192.168.100.50` | B (câble Pi↔PC) | reçoit le HTTP du Pi (5050) + relais bridge |
| **PC** `Ethernet 2` | `192.168.5.100` | C (câble PC↔gateway) | parle au gateway en Telnet |
| **Gateway (DUT)** | `192.168.5.1` | C (câble PC↔gateway) | cible des commandes `scos-voice` |

- **Réseau A — Wi-Fi** : téléphone ↔ PC seulement. *(L'IP Wi-Fi du PC `10.235.225.56`
  est **fixée en statique** (2026-06-26) : passerelle/DNS `10.235.225.157`, DHCP désactivé.
  Elle ne change plus au reboot. Valable **uniquement** sur ce réseau `10.235.225.x` ;
  pour revenir en DHCP : `netsh interface ip set address name="Wi-Fi" dhcp` (admin).)*
- **Réseau B — câble direct Pi↔PC** (`192.168.100.0/24`) : Pi = `.10`, PC = `.50`.
  C'est par là que passe **tout** : l'UI (port 5000) **et** le pilotage gateway (port 5050).
- **Réseau C — câble direct PC↔gateway** (`192.168.5.0/24`) : PC = `.100`, gateway = `.1`.
  **Seul le PC** voit le gateway. Le Pi ne le voit **jamais**.

> **Pourquoi le Pi n'est pas sur le Wi-Fi ?** Stabilité industrielle : un câble
> direct ne se déconnecte pas, n'a pas de mot de passe Wi-Fi à gérer, IP fixe garantie.

---

## 3. Les 3 canaux de communication (qui parle à qui, et comment)

### Canal 1 — UI ⇄ Pi (afficher les mesures, cliquer DÉMARRER)

Deux chemins selon **d'où** on regarde :

**a) Depuis le navigateur du PC** (le plus simple — aucun pont nécessaire) :
```
Navigateur PC ──(câble B)──► Pi 192.168.100.10:5000  (app.py)
```
URL : **http://192.168.100.10:5000**

**b) Depuis le téléphone** (Wi-Fi) — le Pi n'est pas sur le Wi-Fi, donc le **PC sert de pont** :
```
📱 Téléphone (Wi-Fi) ──► PC 10.235.225.56:5000 ──[bridge.js relais TCP]──► Pi 192.168.100.10:5000
```
URL configurée dans l'app (`src/constants/config.js`) : **http://10.235.225.56:5000**

`bridge.js` est un **simple relais TCP** : il écoute le port 5000 sur **toutes** les
cartes du PC et transmet tel quel (HTTP polling **et** WebSocket socket.io) vers le
Pi. Sans lui, le téléphone ne peut **pas** atteindre le Pi.

Protocole de ce canal : **REST** (`GET /api/status`, `/api/history`, `POST /api/start`,
`/api/stop`, `/api/reset`) **+ Socket.IO** (push temps réel `test_update`).

### Canal 2 — Pi ⇄ PC (pilotage du gateway)

Pendant la phase sonnerie/transmission, le Pi a besoin de faire sonner le gateway.
Il ne parle pas au gateway directement : il **demande au PC** en HTTP.

```
Pi (gateway_voice, FXS_GW_URL=http://192.168.100.50:5050)
   ──HTTP POST /session/open, /ring/start, /ring/stop, /p2p/start, /session/close──►
PC gateway_server.py (port 5050)
```

Ce qui déclenche ce mode : la variable d'environnement **`FXS_GW_URL`** (dans `.env`
et dans `fxs_app.service`). Si elle est absente → le Pi telnete le gateway lui-même
(mode « local », historique).

### Canal 3 — PC ⇄ Gateway (commandes réelles)

Le PC ouvre **une seule** session Telnet vers le gateway pour toute la durée d'un test :

```
PC gateway_server.py ──(câble C)──► Telnet 192.168.5.1:23
   → root/root → scos-voice -b fxs init / ring start / ring stop / p2p start
```

### Vue d'ensemble (un test complet, bout en bout)

```
1. Opérateur clique DÉMARRER          (📱 ou navigateur PC)
2. → POST /api/start                   ──► Pi app.py:5000
3. app.py lance fxs_real (thread)       (sur le Pi)
4. Phase SONNERIE : fxs_real → gateway_voice → POST /ring/start
                                        ──HTTP──► PC:5050
5. PC gateway_server → gateway_voice local → Telnet ring start
                                        ──Telnet──► gateway 192.168.5.1
6. Le téléphone FXS sonne ; le Pi lit la tension de sonnerie (ADS1115)
7. fxs_real pousse chaque mesure        ──Socket.IO test_update──► UI (temps réel)
8. Fin : verdict seuils + IA, enregistrement SQLite (fxs_tests.db sur le Pi)
```

**Tolérance aux pannes :** si le PC (5050) ou le gateway est injoignable, la mesure
**continue** (warning loggé, sonnerie manuelle possible). Le banc ne plante jamais
à cause de la sonnerie.

---

## 4. Réponses directes à tes questions

### « Faut-il que le téléphone soit sur le même Wi-Fi ? »
**Oui** — le téléphone doit être sur le **même Wi-Fi que le PC** (réseau A).
Le Pi et le gateway, eux, ne sont **pas** sur le Wi-Fi : ils sont sur des câbles
dédiés. Le PC est le seul à être sur les trois réseaux et fait le pont.

### « Peut-on commander à distance depuis le téléphone ? »
**Oui, mais uniquement dans la portée du Wi-Fi de l'usine** (même réseau local que
le PC). Le bouton DÉMARRER de l'app envoie `POST /api/start` → PC (bridge) → Pi.
Pour un vrai pilotage **hors site** (Internet), il faudrait en plus un VPN ou une
redirection de port — **non configuré** aujourd'hui (et déconseillé sur un banc
industriel pour des raisons de sécurité).

### « Comment ça s'ouvre / le serveur se connecte tout seul quand le PC s'allume ? »
Tout est **automatique** (voir [DEMARRAGE_AUTO.md](DEMARRAGE_AUTO.md)) :
- **PC** : deux raccourcis dans le **dossier Démarrage Windows** (`Win+R` → `shell:startup`)
  démarrent seuls à l'ouverture de session :
  - `run_gateway_server.bat` (→ `gateway_server.py`, port 5050) — `GatewayServer.lnk`. ✅
  - `run_bridge.bat` (→ `bridge.js`, port 5000, relais Wi-Fi → Pi) — `FxsBridge.lnk`. ✅ *(ajouté 2026-06-26)*
- **Pi** : `app.py` est un **service systemd `fxs_app`** : il démarre au boot du Pi
  et **redémarre automatiquement** en cas de crash (`Restart=on-failure`).
- **Gateway** : rien à lancer ; c'est le DUT branché, piloté à la demande.
- **Application** : l'opérateur l'ouvre lui-même (page web ou app) → DÉMARRER.

Donc : **PC allumé + Pi allumé = banc prêt**, sans taper une commande.

---

## 5. Web vs Mobile — deux interfaces, même backend

| | Dashboard **Web** | Application **Mobile** |
|---|---|---|
| Code | `templates/index.html` (servi par le Pi) | `fxs-mobile/` (Expo / React Native) |
| Où on l'ouvre | Navigateur du PC | Téléphone (ou navigateur via Expo web) |
| URL / cible | `http://192.168.100.10:5000` (direct Pi) | `http://10.235.225.56:5000` (PC bridge → Pi) |
| Pont nécessaire ? | **Non** (PC sur le câble B) | **Oui** (`bridge.js` sur le PC) |
| Backend | **Le même** `app.py` sur le Pi | **Le même** `app.py` sur le Pi |

Les deux affichent les **mêmes données** (mêmes API REST + Socket.IO). Le web est
le plus simple et fiable ; le mobile est un confort (se déplacer avec le téléphone).

---

## 6. Industrialiser l'app mobile — sortir de `npx expo start` + QR

**Le problème.** Aujourd'hui l'app se lance avec `npx expo start` puis scan du QR
dans Expo Go : il faut un terminal ouvert (le « Metro bundler ») en permanence et
re-scanner. **Pas acceptable en production.** Trois solutions, de la plus simple à
la plus « propre » :

### Option A — Ne pas utiliser le mobile du tout (recommandé pour démarrer)
Le **dashboard web** (`http://192.168.100.10:5000`) couvre 100 % du besoin et n'a
**aucune** de ces contraintes : il est servi par le Pi, toujours disponible, on
ouvre juste le navigateur. C'est l'interface « toujours allumée » par défaut.

### Option B — APK Android autonome (la vraie réponse « app installée »)
On compile **une fois** un vrai APK installable, qui s'ouvre comme n'importe quelle
app : **plus de QR, plus de terminal, plus de Metro**.

```bash
cd D:\ing-pfe-bancTest\fxs-mobile
npm install -g eas-cli
eas login                       # compte Expo (gratuit)
eas build -p android --profile preview   # construit un APK dans le cloud Expo
# → télécharger l'APK, l'installer sur le(s) téléphone(s)
```

Points d'attention pour l'APK :
- L'URL backend est **figée à la compilation** (`src/constants/config.js`). Donc il
  **faut une IP fixe** côté PC (voir §7). Si l'IP change, l'APK ne trouve plus le Pi.
- Le PC doit toujours faire tourner **`bridge.js`** (relais Wi-Fi → Pi).
- Alternative sans serveur Expo cloud : `npx expo run:android` (build local, nécessite
  Android Studio).

### Option C — Build web statique de l'app mobile, servi en permanence
L'app Expo peut être exportée en **site web statique** (`npx expo export`, dossier
`dist/` déjà présent) et servie par un petit serveur (ou même par le Pi). On ouvre
alors l'app mobile dans un **navigateur** via une URL, sans Expo Go ni QR. Compromis
entre A et B.

> **Recommandation industrielle :** **Option A** (web) pour l'usage quotidien fixe,
> **+ Option B** (APK) si on veut vraiment l'app sur des téléphones d'opérateurs.
> Pré-requis (✅ tous deux faits) : **IP Wi-Fi fixe au PC** et **`bridge.js` en
> démarrage automatique**.

---

## 7. Checklist « toujours prêt en usine » (à faire une fois)

1. **IP fixes** sur les 3 cartes du PC + le Pi. ✅ **IP Wi-Fi du PC fixée** (2026-06-26) :
   `10.235.225.56/24` statique, passerelle/DNS `10.235.225.157`, DHCP désactivé
   (adaptateur « Wi-Fi », MAC `74-12-B3-93-F5-77`). `config.js` et `bridge.js` pointent
   déjà sur cette adresse, rien d'autre à reporter. *(Alternative : réservation DHCP par
   MAC sur le routeur `10.235.225.157` — mêmes effets, sans désactiver DHCP côté PC.)*
2. **Démarrage auto du PC — 2 services** (tous deux ✅, raccourcis dans `shell:startup`) :
   - `gateway_server.py` : `run_gateway_server.bat` → `GatewayServer.lnk` (port 5050).
   - `bridge.js` : `run_bridge.bat` → `FxsBridge.lnk` (port 5000). ✅ *(ajouté 2026-06-26)*
3. **Démarrage auto du Pi** : ✅ service systemd `fxs_app` (`enable --now`).
4. **App mobile** : construire un **APK** (Option B) et l'installer, ou s'en tenir au
   **dashboard web** (Option A).
5. **Vérifier** après reboot complet : `curl http://192.168.100.10:5000/api/gateway`
   → doit renvoyer `"mode":"remote","reachable":true`.

---

## 8. Démarrage manuel (si besoin de tout relancer à la main)

```bash
# --- PC ---
#   1) serveur gateway (Telnet vers le DUT)
"C:\Python313\python.exe" D:\ing-pfe-bancTest\deploy_test_final\gateway_server.py   # port 5050
#   2) pont pour le téléphone
node D:\ing-pfe-bancTest\fxs-mobile\bridge.js                                       # port 5000 → Pi

# --- Pi ---
sudo systemctl restart fxs_app        # app.py (port 5000) ; ou : python3 app.py
journalctl -u fxs_app -f              # logs en direct

# --- App mobile (dev uniquement) ---
cd D:\ing-pfe-bancTest\fxs-mobile && npx expo start      # puis scan QR (Expo Go)
#   ou web :  npm run web
```

URLs de contrôle :
- Dashboard : **http://192.168.100.10:5000** (PC) — l'app mobile vise `http://10.235.225.56:5000`
- Santé gateway : **http://192.168.100.50:5050/health**
- Mode pilotage : **http://192.168.100.10:5000/api/gateway**
