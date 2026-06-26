# Dépendances à installer sur le PC opérateur (collègue)

> **Le Pi est le même, déjà configuré et partagé** : on n'installe / ne reconfigure
> **rien** sur le Pi (mesures + IA + dashboard restent dessus). Ce document liste
> uniquement ce qu'il faut installer sur **SON PC**.

---

## A. Contrôler le banc + sonnerie (OBLIGATOIRE)

| À installer | Comment |
|---|---|
| **Python 3.x** (3.10+) | python.org → cocher **« Add Python to PATH »** |
| **Flask** | `pip install flask` |

> `gateway_voice.py` n'utilise QUE la bibliothèque standard de Python
> (socket, urllib, json…) → rien d'autre à installer pour la sonnerie.

Contrôle du banc : ouvrir le navigateur sur **http://192.168.100.10:5000**
(dashboard servi par le Pi).

---

## B. Pont téléphones (UNIQUEMENT si des téléphones se connectent en Wi-Fi)

| À installer | Comment |
|---|---|
| **Node.js 20 LTS** | nodejs.org |

> `bridge.js` n'utilise que le module **intégré** `net` de Node → **aucun `npm install`**.

---

## C. App mobile Expo (pour exécuter / reconstruire l'app)

| À installer | Comment |
|---|---|
| **Node.js 20 LTS + npm** | nodejs.org |
| **Dépendances de l'app** | `cd fxs-mobile` puis **`npm install`** |
| **Expo CLI** | rien à installer : **`npx expo start`** (QR + Expo Go) |
| **Expo Go** (sur le téléphone) | Play Store / App Store |
| **EAS CLI** (APK autonome) | `npm install -g eas-cli` puis `eas build -p android` |

`npm install` installe (depuis `package.json`, Expo SDK 54 / React Native 0.81) :

```
expo ~54.0.0 · react 19.1.0 · react-native 0.81.5 · react-native-web ^0.21
expo-asset · expo-status-bar · @expo/metro-runtime · socket.io-client ^4.7
```

---

## ⛔ À NE PAS installer sur le PC (dépendances du **Pi** uniquement)

`flask-socketio` · `simple-websocket` · `numpy` · `joblib` · `scikit-learn` ·
`adafruit-circuitpython-ads1x15` · `adafruit-blinka`

→ ils tournent **sur le Pi** (mesures + IA). Le `requirements.txt` du dépôt est la
liste **du Pi**, pas du PC.

---

## Récapitulatif

| Il veut… | À installer sur son PC |
|---|---|
| Contrôler le banc (navigateur) + sonnerie | **Python + Flask** |
| Brancher des téléphones en Wi-Fi | **+ Node.js** (bridge.js) |
| Exécuter / reconstruire l'app mobile | **+ Node.js + `npm install`** dans `fxs-mobile` (+ EAS CLI pour l'APK) |
| Quoi que ce soit sur le Pi | **rien** — même Pi, déjà configuré |
