"""
gateway_voice.py — Pilotage de la sonnerie FXS du gateway via Telnet
====================================================================
Au lieu de sonner manuellement, on commande la sonnerie directement sur le
gateway (le DUT) par Telnet, avec les commandes `scos-voice` :

    f5387 login: root
    Password: root
    root@f5387:~# scos-voice -b fxs init        (country DE)
    root@f5387:~# scos-voice -b fxs ring start
    root@f5387:~# scos-voice -b fxs ring stop

Implémentation Telnet sur SOCKET BRUT (pas telnetlib, retiré en Python 3.13) :
fonctionne aussi bien sur le PC (3.13) que sur le Pi (3.9). On gère la négociation
d'options Telnet (IAC) en la refusant, ce qui suffit pour un shell de login.

Utilisé par fxs_real.py pendant la phase SONNERIE : ring start avant les lectures,
ring stop après. Tolérant : si le gateway est injoignable, on logge un warning et
la mesure continue (sonnerie manuelle possible en repli).
"""

import json
import logging
import os
import socket
import time
import urllib.request

log = logging.getLogger(__name__)

# ── Mode DÉPORTÉ (sonnerie pilotée depuis le PC) ──
# Sur une station de test-final (TF), le Pi est EMBARQUÉ et figé dans le banc :
# c'est le matériel de mesure. Le DUT (gateway) change à chaque unité testée. On
# ne veut donc pas reconfigurer le Pi pour chaque gateway -> toute la connaissance
# du gateway (IP, login, pays, commandes scos-voice) vit côté PC (operator station),
# qui pilote la sonnerie. Le Pi se contente de demander « ring start / ring stop ».
# (Bénéfice secondaire : le lien réseau PC↔gateway est plus fiable que Pi↔gateway.)
#   - FXS_GW_URL non défini  -> Telnet LOCAL (comportement historique, inchangé).
#   - FXS_GW_URL=http://<ip-pc>:5050 -> proxy HTTP vers le serveur PC.
# fxs_real.py n'a RIEN à changer : start_ring()/stop_ring() gardent la même API.
GW_SERVER_URL   = os.environ.get("FXS_GW_URL", "").rstrip("/")
GW_HTTP_TIMEOUT = 12              # s — marge réseau PC (init gateway peut être lent)

# ── Configuration du gateway (DUT) ──
GW_HOST     = "192.168.5.1"
GW_PORT     = 23
GW_USER     = "root"
GW_PASSWORD = "root"             # mot de passe du gateway
GW_COUNTRY  = "DE"               # scos-voice -b fxs init utilise ce pays
GW_TIMEOUT  = 8                  # s — délai max d'attente de l'invite après une commande
GW_PROMPT   = b"~#"              # fin de l'invite shell (root@f5387:~#) — plus sûr que "#" seul
GW_SETTLE   = 0.4                # s — petite marge après chaque commande
POST_INIT_SETTLE = 2.0           # s — temps pour que la LIGNE s'établisse après `init`
                                 #     (sinon TR ≈ 0 V si on mesure trop tôt). À ajuster
                                 #     si la ligne met plus de temps à monter en tension.

# Constantes Telnet (RFC 854)
_IAC = 255
_DONT, _DO, _WONT, _WILL = 254, 253, 252, 251


class _Telnet:
    """Mini-client Telnet sur socket brut (write / read_until), gère l'IAC."""

    def __init__(self, host, port, timeout):
        self.timeout = timeout
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.buf = bytearray()          # données applicatives (IAC retiré)
        self._iac = bytearray()         # séquence IAC en cours de réception

    def write(self, data):
        self.sock.sendall(data)

    def _feed(self, data):
        # Machine à états : sépare le texte des commandes Telnet (IAC ...).
        for byte in data:
            if self._iac:
                self._iac.append(byte)
                if len(self._iac) == 2:
                    cmd = self._iac[1]
                    if cmd == _IAC:                 # IAC IAC -> octet 255 littéral
                        self.buf.append(_IAC); self._iac = bytearray()
                    elif cmd not in (_WILL, _WONT, _DO, _DONT):
                        self._iac = bytearray()     # commande sans option
                elif len(self._iac) == 3:
                    cmd, opt = self._iac[1], self._iac[2]
                    if cmd in (_DO, _DONT):         # on refuse de faire l'option
                        self.sock.sendall(bytes([_IAC, _WONT, opt]))
                    elif cmd in (_WILL, _WONT):     # on refuse que l'autre la fasse
                        self.sock.sendall(bytes([_IAC, _DONT, opt]))
                    self._iac = bytearray()
            elif byte == _IAC:
                self._iac = bytearray([_IAC])
            else:
                self.buf.append(byte)

    def read_until(self, expected, timeout=None):
        end = time.time() + (timeout if timeout is not None else self.timeout)
        while expected not in bytes(self.buf):
            remaining = end - time.time()
            if remaining <= 0:
                break
            self.sock.settimeout(remaining)
            try:
                chunk = self.sock.recv(2048)
            except (socket.timeout, OSError):
                break
            if not chunk:
                break
            self._feed(chunk)
        data = bytes(self.buf)
        idx = data.find(expected)
        if idx >= 0:
            cut = idx + len(expected)
            self.buf = bytearray(data[cut:])
            return data[:cut]
        self.buf = bytearray()
        return data

    def read_very_eager(self):
        self.sock.settimeout(0.0)
        try:
            while True:
                chunk = self.sock.recv(2048)
                if not chunk:
                    break
                self._feed(chunk)
        except (BlockingIOError, socket.timeout, OSError):
            pass
        out = bytes(self.buf); self.buf = bytearray()
        return out

    def close(self):
        try:
            self.sock.close()
        except Exception:
            pass


class GatewayVoice:
    """Session Telnet vers le gateway pour piloter la sonnerie FXS."""

    def __init__(self, host=GW_HOST, port=GW_PORT, user=GW_USER,
                 password=GW_PASSWORD, timeout=GW_TIMEOUT):
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.timeout = timeout
        self.tn = None

    # -- connexion / login --------------------------------------------------
    def connect(self):
        self.tn = _Telnet(self.host, self.port, self.timeout)
        self.tn.read_until(b"login:", self.timeout)
        self.tn.write(self.user.encode() + b"\n")
        self.tn.read_until(b"Password:", self.timeout)
        self.tn.write(self.password.encode() + b"\n")
        self.tn.read_until(GW_PROMPT, self.timeout)   # attend la 1ère invite
        time.sleep(GW_SETTLE)
        log.info("Gateway connecté : %s@%s", self.user, self.host)
        return self

    # -- commandes scos-voice ----------------------------------------------
    def _cmd(self, command, settle=GW_SETTLE):
        """Envoie une commande, ATTEND l'invite (root@...:~#), puis petite marge.
        On ne lance jamais la commande suivante avant d'avoir revu l'invite."""
        self.tn.read_very_eager()                     # vide le buffer résiduel
        self.tn.write(command.encode() + b"\n")
        out = self.tn.read_until(GW_PROMPT, self.timeout)   # bloque jusqu'à l'invite
        if settle:
            time.sleep(settle)
        return out

    def init(self):
        # init initialise le sous-système FXS ET énergise la ligne -> on attend que
        # la commande rende l'invite, PUIS on laisse la ligne s'établir (POST_INIT_
        # SETTLE) avant toute mesure (sinon TR ≈ 0 V). DOIT être appelé AU DÉBUT.
        self._cmd("scos-voice -b fxs init", settle=1.5)
        log.info("Gateway : scos-voice fxs init (%s)", GW_COUNTRY)
        time.sleep(POST_INIT_SETTLE)

    def ring_start(self):
        self._cmd("scos-voice -b fxs ring start")
        log.info("Gateway : RING START")

    def ring_stop(self):
        self._cmd("scos-voice -b fxs ring stop")
        log.info("Gateway : RING STOP")

    def p2p_start(self):
        # Met les 2 ports FXS en point-à-point (un port décroché) -> permet la
        # mesure de transmission/atténuation. À appeler AVANT la phase transmission.
        self._cmd("scos-voice -b fxs p2p start")
        log.info("Gateway : P2P START")

    def p2p_stop(self):
        # Fourni pour complétude ; non utilisé dans la séquence (le DUT est retiré
        # entre deux tests et le prochain `init` remet tout à zéro).
        self._cmd("scos-voice -b fxs p2p stop")
        log.info("Gateway : P2P STOP")

    def close(self):
        try:
            if self.tn:
                self.tn.close()
        except Exception:
            pass
        self.tn = None


class _RemoteRing:
    """Jeton renvoyé par start_ring() en mode déporté : truthy pour fxs_real
    (qui teste `if gw:`), mais ne porte aucune session Telnet — c'est le serveur
    PC qui détient la session réelle. stop_ring() le reconnaît et POSTe /ring/stop."""
    __slots__ = ()


def _post(path, payload=None):
    """POST JSON vers le serveur sonnerie PC (urllib, sans dépendance externe)."""
    data = json.dumps(payload or {}).encode()
    req = urllib.request.Request(
        GW_SERVER_URL + path, data=data,
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=GW_HTTP_TIMEOUT) as r:
        body = r.read().decode()
    return json.loads(body) if body else {}


# ── Telnet LOCAL (depuis cette machine) — comportement historique ──
def _start_ring_local(do_init=True):
    try:
        gw = GatewayVoice()
        gw.connect()
        if do_init:
            gw.init()
        gw.ring_start()
        return gw
    except Exception as e:  # noqa: BLE001 — ne jamais casser la mesure
        log.warning("Sonnerie auto gateway indisponible (%s) — sonnez manuellement", e)
        return None


def _stop_ring_local(gw):
    if gw is None:
        return
    try:
        gw.ring_stop()
    except Exception:
        pass
    gw.close()


# ── API publique (utilisée telle quelle par fxs_real, quel que soit le mode) ──
def start_ring(do_init=True):
    """(init +) ring start. Renvoie un objet truthy en cas de succès, ou None si
    le gateway/serveur est injoignable (la mesure continue sans sonnerie auto).

    Mode déporté (FXS_GW_URL défini) : délègue au serveur PC par HTTP.
    Mode local (par défaut) : Telnet direct vers le gateway."""
    if GW_SERVER_URL:
        try:
            _post("/ring/start", {"init": do_init})
            log.info("Sonnerie déclenchée via serveur PC (%s)", GW_SERVER_URL)
            return _RemoteRing()
        except Exception as e:  # noqa: BLE001 — ne jamais casser la mesure
            log.warning("Serveur sonnerie PC injoignable (%s) — sonnez manuellement", e)
            return None
    return _start_ring_local(do_init)


def stop_ring(gw):
    """ring stop + ferme la session (tolérant si gw est None)."""
    if gw is None:
        return
    if isinstance(gw, _RemoteRing):
        try:
            _post("/ring/stop")
        except Exception as e:  # noqa: BLE001
            log.warning("Arrêt sonnerie (serveur PC) échoué : %s", e)
        return
    _stop_ring_local(gw)


# ═══════════════════════════════════════════════════════════════════════════════
#  SESSION GATEWAY POUR TOUTE LA SÉQUENCE (init au début, ring/p2p en cours de route)
#  Utilisée par fxs_real : `open_session()` AU DÉBUT (ouvre Telnet + init -> ligne
#  énergisée), puis ring_on/ring_off autour de la sonnerie, p2p_on avant la
#  transmission, et `close_session()` à la fin. Une SEULE session Telnet pour tout
#  le test (côté PC, le serveur la détient ; côté local, c'est l'objet GatewayVoice).
# ═══════════════════════════════════════════════════════════════════════════════
class _RemoteGateway:
    """Handle DÉPORTÉ : chaque opération = un POST au serveur PC, qui détient la
    session Telnet ouverte pour toute la durée du test. Truthy pour fxs_real."""
    __slots__ = ()
    def ring_start(self): _post("/ring/start")
    def ring_stop(self):  _post("/ring/stop")
    def p2p_start(self):  _post("/p2p/start")
    def p2p_stop(self):   _post("/p2p/stop")
    def close(self):      _post("/session/close")


def gateway_health(timeout=4):
    """Mode déporté : interroge le serveur PC (/health). Renvoie le dict de statut
    ({'ok':True,'gateway':...}) ou None (non déporté, ou serveur PC injoignable).
    Sert à l'API /api/gateway pour que l'app mobile signale si la sonnerie marchera."""
    if not GW_SERVER_URL:
        return None
    try:
        with urllib.request.urlopen(GW_SERVER_URL + "/health", timeout=timeout) as r:
            return json.loads(r.read().decode() or "{}")
    except Exception:
        return None


def open_session(do_init=True):
    """Ouvre la session gateway pour TOUTE la séquence et fait `init` (énergise la
    ligne) AU DÉBUT. Renvoie un handle (ring_start/ring_stop/p2p_start/p2p_stop/
    close), ou None si injoignable -> la mesure continue sans pilotage gateway.

    Mode déporté (FXS_GW_URL) : ouvre la session sur le serveur PC.
    Mode local : ouvre la session Telnet depuis cette machine."""
    if GW_SERVER_URL:
        try:
            _post("/session/open", {"init": do_init})
            log.info("Session gateway ouverte via serveur PC (%s)", GW_SERVER_URL)
            return _RemoteGateway()
        except Exception as e:  # noqa: BLE001 — ne jamais casser la mesure
            log.warning("Serveur sonnerie PC injoignable (%s) — pilotage gateway manuel", e)
            return None
    try:
        gw = GatewayVoice()
        gw.connect()
        if do_init:
            gw.init()
        return gw
    except Exception as e:  # noqa: BLE001
        log.warning("Gateway injoignable (%s) — pilotage manuel", e)
        return None


def _safe(gw, op):
    """Appelle gw.<op>() sans jamais casser la mesure (tolérant si gw est None)."""
    if gw is None:
        return
    try:
        getattr(gw, op)()
    except Exception as e:  # noqa: BLE001
        log.warning("Gateway %s échoué : %s", op, e)


def ring_on(gw):       _safe(gw, "ring_start")
def ring_off(gw):      _safe(gw, "ring_stop")
def p2p_on(gw):        _safe(gw, "p2p_start")
def p2p_off(gw):       _safe(gw, "p2p_stop")
def close_session(gw): _safe(gw, "close")


if __name__ == "__main__":
    # Test manuel :  python gateway_voice.py   (PC)  /  python3 gateway_voice.py  (Pi)
    #   -> login + init + ring 3 s + stop. Le gateway doit être joignable (ping).
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    g = start_ring()
    if g:
        print("Sonnerie en cours 3 s...")
        time.sleep(3)
        stop_ring(g)
        print("Termine.")
    else:
        print("Gateway injoignable (verifie le reseau : ping 192.168.5.1).")
