# Sonnerie déportée sur le PC — Guide

> **But de ce document.** Expliquer **uniquement** la partie « sonnerie du gateway
> pilotée depuis le PC » : à quoi sert chaque nouveau fichier, comment ils
> communiquent, ce qu'on change / déplace sur le Pi, et comment lancer le tout
> étape par étape.

---

## 1. Pourquoi cette version

Sur une station de **test-final (TF)**, le **Raspberry Pi est embarqué et figé**
dans le banc : c'est le matériel de mesure (ADS1115 + GPIO), il ne bouge pas. Ce
qui change, c'est le **gateway sous test (DUT)** : une unité différente à chaque
test.

On ne veut donc **jamais reconfigurer le Pi** pour chaque gateway. La solution :
déporter **toute la commande de sonnerie** (`scos-voice` par Telnet) sur le **PC**
(poste opérateur). Le Pi se contente de demander *« fais sonner / arrête de
sonner »* ; c'est le PC qui parle réellement au gateway.

> Bénéfice secondaire : le lien réseau **PC ↔ gateway** est plus fiable que
> **Pi ↔ gateway**.

---

## 2. Vue d'ensemble (qui tourne où)

```
   ┌───────────────────────── Raspberry Pi (banc, FIGÉ) ─────────────────────────┐
   │                                                                              │
   │   app.py  (Flask/SocketIO, port 5000)                                        │
   │      │  appelle (in-process)                                                 │
   │      ▼                                                                        │
   │   fxs_real.py   ──── mesure ADS1115 + GPIO (sonnerie, TR/CL, transmission)   │
   │      │  pendant la phase SONNERIE appelle :                                   │
   │      ▼                                                                        │
   │   gateway_voice.py   (mode déporté : FXS_GW_URL défini)                       │
   │      │                                                                        │
   └──────┼────────────────────────────────────────────────────────────────────┘
          │  HTTP  POST /ring/start   POST /ring/stop
          ▼
   ┌───────────────────────── PC (poste opérateur) ─────────────────────────────┐
   │                                                                             │
   │   gateway_server.py   (Flask, port 5050)                                    │
   │      │  ouvre la session Telnet                                             │
   │      ▼                                                                       │
   │   gateway_voice.py   (mode local : moteur Telnet scos-voice)                │
   │      │                                                                       │
   └──────┼─────────────────────────────────────────────────────────────────────┘
          │  Telnet (port 23)  scos-voice -b fxs init / ring start / ring stop
          ▼
   ┌───────────────────────── Gateway / DUT (192.168.5.1) ──────────────────────┐
   │   Le téléphone FXS sonne. Le Pi lit la tension de sonnerie (Vrms).          │
   └─────────────────────────────────────────────────────────────────────────────┘
```

**Idée clé :** `gateway_voice.py` est **le même fichier** des deux côtés, mais il
se comporte différemment selon la variable d'environnement `FXS_GW_URL` :

| Côté    | `FXS_GW_URL`            | Comportement de `gateway_voice`                         |
|---------|-------------------------|---------------------------------------------------------|
| **Pi**  | défini (`http://PC:5050`) | **Proxy HTTP** : envoie la demande au PC                |
| **PC**  | non défini              | **Telnet local** : parle directement au gateway         |

---

## 3. Explication de chaque fichier

### 3.1. `gateway_voice.py` — *modifié* (tourne sur le Pi ET le PC)

Le « cerveau » de la sonnerie. Il a maintenant **deux modes**, choisis par la
variable d'environnement `FXS_GW_URL` :

- **Mode local** (`FXS_GW_URL` non défini) — comportement historique : ouvre une
  session **Telnet** vers le gateway (`192.168.5.1`) et envoie les commandes
  `scos-voice` (`init`, `ring start`, `ring stop`). C'est ce mode qui tourne **sur
  le PC**.
- **Mode déporté** (`FXS_GW_URL = http://<ip-pc>:5050`) — n'ouvre **aucun** Telnet ;
  il envoie une requête **HTTP** au PC (`POST /ring/start`, `POST /ring/stop`).
  C'est ce mode qui tourne **sur le Pi**.

API publique (inchangée, identique dans les deux modes) :

| Fonction              | Rôle                                                            |
|-----------------------|----------------------------------------------------------------|
| `start_ring(do_init)` | (init +) démarre la sonnerie. Renvoie un objet « session », ou `None` si injoignable. |
| `stop_ring(gw)`       | arrête la sonnerie et ferme la session (tolérant si `gw is None`). |

> **Pourquoi `fxs_real.py` n'a rien à changer :** il appelle toujours
> `gateway_voice.start_ring()` / `stop_ring()`. C'est `gateway_voice` qui décide,
> tout seul, s'il telnet en local ou s'il passe par le PC. Le reste du code ne voit
> aucune différence.

Configuration du gateway (vit dans **CE** fichier, **sur le PC**) :

```python
GW_HOST     = "192.168.5.1"   # IP du gateway (DUT)
GW_PORT     = 23              # Telnet
GW_USER     = "root"
GW_PASSWORD = "root"
GW_COUNTRY  = "DE"            # scos-voice -b fxs init
```

### 3.2. `gateway_server.py` — *nouveau* (tourne **uniquement sur le PC**)

Un petit serveur web (Flask) qui **reçoit les demandes du Pi** et les traduit en
commandes Telnet réelles, via `gateway_voice` en mode local.

Il garde **une seule session** Telnet à la fois (un banc = un gateway).

Endpoints :

| Méthode + URL        | Corps           | Effet                                              |
|----------------------|-----------------|----------------------------------------------------|
| `GET  /health`       | —               | `{"ok": true, "gateway": "192.168.5.1", "ringing": false}` |
| `POST /ring/start`   | `{"init": true}`| `scos-voice init` (option) + `ring start`          |
| `POST /ring/stop`    | —               | `ring stop` + ferme la session                     |

Port d'écoute : **5050**.

### 3.3. `fxs_real.py` — *NON modifié*

La séquence de mesure réelle. Pendant la phase SONNERIE, elle appelle
`gateway_voice.start_ring()` avant les lectures et `gateway_voice.stop_ring()`
après. **Aucune ligne n'a changé** : tout le mécanisme déporté est invisible pour
elle.

### 3.4. `app.py` — *NON modifié*

Le serveur Flask/SocketIO du tableau de bord (port **5000**, sur le Pi). Quand on
clique **START**, il lance `fxs_real.run_gateway_test(...)` dans un thread.

### 3.5. `fxs_app.service` — *modifié* (Pi)

Le service systemd qui lance `app.py` au démarrage du Pi. On y a ajouté (en
commentaire) la ligne pour activer le mode déporté :

```ini
#Environment=FXS_GW_URL=http://192.168.1.50:5050
```

À **décommenter** et mettre l'IP du PC.

### 3.6. `build_deploy.py` — *modifié*

`gateway_server.py` a été ajouté à la liste `RUNTIME`, donc il est copié dans
`deploy_premier_test/` et `deploy_test_final/` à chaque build.

---

## 4. Comment se passe la communication (un test complet)

```
1. Opérateur clique START sur le dashboard            (PC navigateur → Pi app.py:5000)
2. app.py lance fxs_real.run_gateway_test(...)         (sur le Pi)
3. Phase SONNERIE : fxs_real appelle start_ring()       (sur le Pi)
4. gateway_voice (Pi) voit FXS_GW_URL → POST /ring/start  ───HTTP──►  PC:5050
5. gateway_server (PC) → gateway_voice local → Telnet   ───Telnet──►  gateway 192.168.5.1
6. scos-voice ring start → le téléphone sonne
7. Le Pi lit la tension de sonnerie (Vrms) via l'ADS1115
8. fxs_real appelle stop_ring()                         (sur le Pi)
9. gateway_voice (Pi) → POST /ring/stop                  ───HTTP──►  PC:5050
10. gateway_server (PC) → Telnet ring stop + ferme la session
```

**Tolérance aux pannes :** si le PC ou le gateway est injoignable, `start_ring()`
renvoie `None`, un *warning* est loggé, et **la mesure continue** (sonnerie
manuelle possible en repli). Le banc ne plante jamais à cause de la sonnerie.

---

## 5. Quoi mettre / changer sur chaque machine

### Sur le PC (poste opérateur)

| Fichier              | Pourquoi                                  |
|----------------------|-------------------------------------------|
| `gateway_server.py`  | le serveur à lancer                       |
| `gateway_voice.py`   | moteur Telnet utilisé par le serveur      |
| `flask` (pip)        | dépendance du serveur                     |

> Le PC **doit pouvoir joindre le gateway** : `ping 192.168.5.1` doit répondre.
> Sur le PC, **ne PAS** définir `FXS_GW_URL` (sinon il essaierait de se renvoyer la
> requête à lui-même au lieu de telnet).

### Sur le Pi (banc)

Rien de nouveau à coder : on déploie l'application comme d'habitude
(`deploy_test_final/`). La **seule chose à faire** est de définir la variable
d'environnement qui active le mode déporté :

```bash
export FXS_GW_URL=http://<IP_DU_PC>:5050
```

ou, de façon permanente, décommenter la ligne `Environment=FXS_GW_URL=...` dans
`fxs_app.service` (avec la bonne IP du PC).

> Le Pi n'a **pas besoin** de `gateway_server.py` (il est copié mais ne sert pas
> côté Pi). Le Pi n'a plus besoin de joindre `192.168.5.1` : c'est le PC qui s'en
> charge.

---

## 6. Lancement, étape par étape

### Étape 1 — PC : vérifier l'accès au gateway

```bash
ping 192.168.5.1          # doit répondre
```

### Étape 2 — PC : installer Flask (une seule fois)

```bash
pip install flask
```

### Étape 3 — PC : lancer le serveur de sonnerie

```bash
python gateway_server.py
```

Sortie attendue :

```
  Serveur sonnerie PC — gateway 192.168.5.1 — port 5050
  Pi : export FXS_GW_URL=http://<ip-pc>:5050
 * Running on all addresses (0.0.0.0)
 * Running on http://<IP_DU_PC>:5050
```

> Notez l'**IP du PC** affichée (`http://<IP_DU_PC>:5050`) : c'est elle qu'on met
> dans `FXS_GW_URL` côté Pi.

### Étape 4 — PC : tester le serveur (optionnel mais recommandé)

```bash
curl http://localhost:5050/health
# -> {"gateway":"192.168.5.1","ok":true,"ringing":false}
```

Test d'une vraie sonnerie de 3 s (le téléphone doit sonner) :

```bash
curl -X POST http://localhost:5050/ring/start -H "Content-Type: application/json" -d "{\"init\": true}"
# ... le téléphone sonne ...
curl -X POST http://localhost:5050/ring/stop
```

### Étape 5 — Pi : activer le mode déporté

```bash
export FXS_GW_URL=http://<IP_DU_PC>:5050
```

(remplacer `<IP_DU_PC>` par l'IP vue à l'étape 3).

### Étape 6 — Pi : lancer l'application

```bash
cd ~/fxs_app
python3 app.py
```

ou via systemd (si `FXS_GW_URL` est dans le `.service`) :

```bash
sudo systemctl restart fxs_app
journalctl -u fxs_app -f
```

### Étape 7 — Lancer un test

Ouvrir le dashboard (`http://<IP_DU_PI>:5000`), cliquer **START**.
Pendant la phase SONNERIE :

- **Logs du Pi** : `Sonnerie déclenchée via serveur PC (http://<IP_DU_PC>:5050)`
- **Logs du PC** : `127.0.0.1 ... "POST /ring/start" 200` + `Gateway : RING START`
- Le téléphone sonne, le Pi lit la tension de sonnerie.

---

## 7. Vérifications rapides (dépannage)

| Symptôme                                              | Cause probable / vérif                                   |
|-------------------------------------------------------|----------------------------------------------------------|
| Logs Pi : *« Serveur sonnerie PC injoignable »*       | Le serveur PC n'est pas lancé, ou mauvaise IP/port, ou pare-feu PC bloque le 5050. |
| Logs PC : *« Sonnerie auto gateway indisponible »*    | Le PC ne joint pas le gateway → `ping 192.168.5.1`.      |
| Le Pi telnet quand même en direct (pas via le PC)     | `FXS_GW_URL` non défini sur le Pi → `echo $FXS_GW_URL`.  |
| `/health` ne répond pas depuis le Pi                  | Pare-feu PC : autoriser le port **5050** en entrée.      |

---

## 8. Revenir au mode local (sans PC)

Ne **pas** définir `FXS_GW_URL` (ou le vider) sur le Pi : `gateway_voice` repasse
automatiquement en Telnet direct depuis le Pi (comportement historique). Aucun
autre changement nécessaire.
