"""
fxs_real.py — Séquence de test FXS réelle (1 slot / 1 gateway, 2 ports)
=======================================================================
Transcription FIDÈLE des scripts de production trouvés sur la carte SD du banc
(`script reel_fxs/` : TR_FXS{1,2}, CourantLigne_FXS{1,2}, Ring_FXS{1,2},
Trans{300,1000,3400}_FXS{1,2}). Un gateway possède 2 ports FXS testés sur le
MÊME ADC (ADS1115), multiplexés par GPIO. Le module lit les 4 mesures sur FXS1
PUIS FXS2 et renvoie un dict à clés PAR PORT, directement consommable par
`fxs_ai.analyze()` (un score d'anomalie par gateway).

Plateforme réelle (Raspberry Pi)
--------------------------------
- ADC : ADS1115 via Adafruit CircuitPython (`board`, `busio`, `adafruit_ads1x15`).
        TR + Courant -> canal A0 (P0) ; Sonnerie + Transmission -> A1 (P1).
- GPIO : pilotés par la commande shell `raspi-gpio set <pins> dh|dl|op`
         (dh = drive high, dl = drive low, op = output). PAS de RPi.GPIO.

Sélection de port et de fonction (déduite des scripts)
------------------------------------------------------
- GPIO 14 = sélecteur FXS2 (haut = FXS2, bas = FXS1).
- GPIO 17 = chemin de lecture FXS1 ; GPIO 16 = chemin de lecture FXS2.
- GPIO 18 = connexion/mesure DUT ; GPIO 10 = charge courant 470 Ω ;
  GPIO 25 = isolation de masse ; GPIO 12 = bascule Ve->Vs (transmission).
- Fréquence transmission encodée sur GPIO 22/23 (1000=22, 300=23, 3400=22+23).

Étalonnages (repris tels quels)
-------------------------------
- TR        : V_A0 × 100                       -> V
- Courant   : (V_A0 × K × 1000) / 470          -> mA   (K=98 FXS1, 100 FXS2)
- Sonnerie  : V_A1 × 120                        -> Vrms
- Transmission : −20·log10(Vs/Ve)              -> dB (atténuation)

⚠️ Les séquences GPIO sont transcrites 1:1 mais doivent être revalidées sur le
banc réel (un Pi). Sur Windows/PC le module bascule en MODE SIMULATION : aucune
commande matérielle n'est émise, les lectures ADC sont générées de façon
plausible pour exercer toute la chaîne logicielle + IA.
"""

import math
import time
import logging
import subprocess

import gateway_voice   # pilotage sonnerie du gateway par Telnet (scos-voice)

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
#  Détection plateforme : Pi (Adafruit dispo) vs simulation (PC)
# ─────────────────────────────────────────────────────────────
try:
    import board
    import busio
    import adafruit_ads1x15.ads1115 as ADS
    from adafruit_ads1x15.analog_in import AnalogIn
    ON_PI = True
except (ImportError, NotImplementedError):
    ON_PI = False

# Capteur de consommation : DFRobot INA219 (mesure tension/courant/puissance du
# gateway sous test, indépendant de l'ADS1115). La lib peut manquer même sur le
# Pi -> la conso bascule alors en simulation tandis que le reste reste réel.
try:
    from DFRobot_INA219 import INA219 as _INA219
    HAVE_INA219 = True
except (ImportError, NotImplementedError):
    HAVE_INA219 = False

# Le simulateur a besoin d'un hasard déterministe-par-appel mais variable :
# on utilise un compteur + un PRNG local (pas Math.random interdit côté Pi).
import random as _random

# ─────────────────────────────────────────────────────────────
#  LIMITES SAGEM (High/Low Limit de l'export ROW_DATA)
# ─────────────────────────────────────────────────────────────
TR_MIN, TR_MAX           = 44.0, 50.0     # V
CL_MIN, CL_MAX           = 33.0, 39.0     # mA   (par-port en mA, pas en A)
ALARM_MIN, ALARM_MAX     = 35.0, 41.0     # Vrms
TRANS_MIN, TRANS_MAX     = 8.1, 10.1      # dB   (1000 Hz)
CONSO_MIN, CONSO_MAX     = 7.0, 20.0      # W    (M_CONS_CONSUMPTION, ROW_DATA)

CL_SHUNT_OHM = 470.0
CL_GAIN = {"FXS1": 98.0, "FXS2": 100.0}   # constante d'étalonnage par port

# ─────────────────────────────────────────────────────────────
#  Séquences GPIO par (mesure, port) — transcrites des scripts
#  Chaque entrée = liste d'étapes (pins:str, level:'dh'|'dl'|'op', sleep:float)
# ─────────────────────────────────────────────────────────────
# Préambule commun TR : tout en sortie, tout bas.
_TR_PREP = [
    ("9,10,11,12,13,14,16,17,18,19,20,21,22,23,24,25", "op", 0.0),
    ("9,10,11,12,13,14,16,17,18,19,20,21,25", "dl", 0.3),
]
_TR_SELECT = {                       # puis on lève le chemin de mesure
    "FXS1": [("18", "dh", 0.3)],
    "FXS2": [("14,18", "dh", 0.3)],  # 14 = FXS2
}
_CL_SELECT = {                       # charge 470 Ω + mesure
    "FXS1": [("10,18", "dh", 0.3)],
    "FXS2": [("10,14,18", "dh", 0.3)],
}
_CL_CLEANUP = [("10,25", "dl", 0.3), ("11", "dh", 0.0)]
_RING = {
    "FXS1": [("9,10,12,13,14,16,20,25", "dl", 0.0), ("11,18,21", "dh", 0.0)],
    "FXS2": [("9,10,12,13,17,20,25", "dl", 0.0), ("11,14,18,21", "dh", 0.0)],
}
# Transmission : (cmd1 dl, cmd2 dh, cmd3 dh) par port et par fréquence.
# cmd2 encode la fréquence (22=1000, 23=300, 22+23=3400) + 14 si FXS2.
# cmd3 = chemin de lecture (17=FXS1, 16=FXS2) + 20,24.
_TRANS = {
    ("FXS1", 1000): ("10,11,12,14,16,17,20,18,21,22,23,24", "9,12,13,21,22,25",    "17,20,24"),
    ("FXS1", 300):  ("10,11,12,14,16,17,20,18,21,22,23,24", "9,12,13,21,23,25",    "17,20,24"),
    ("FXS1", 3400): ("10,11,12,14,16,17,20,18,21,22,23,24", "9,12,13,21,22,23,25", "17,20,24"),
    ("FXS2", 1000): ("10,11,12,16,17,20,18,21,22,23,24",    "9,12,13,14,21,22,25", "16,20,24"),
    ("FXS2", 300):  ("10,11,12,16,17,20,18,21,22,23,24",    "9,12,13,14,21,23,25", "16,20,24"),
    ("FXS2", 3400): ("10,11,12,16,17,20,18,21,22,23,24",    "9,12,13,14,21,22,23,25", "16,20,24"),
}
_TRANS_CLEANUP = ("20,21,24", "dl")
# Consommation (Conso.sh, version active) : on déconnecte le chemin de mesure DUT
# (18 bas) puis on isole la masse (25 haut) avant de lire l'INA219.
_CONSO_PREP = [("18", "dl", 0.1), ("25", "dh", 0.0)]


# ─────────────────────────────────────────────────────────────
#  Pilotage bas niveau (réel sur Pi / simulé sur PC)
# ─────────────────────────────────────────────────────────────
class _Bench:
    def __init__(self, simulate=None):
        self.simulate = (not ON_PI) if simulate is None else simulate
        self._sim_state = {}        # mémorise les pins hauts pour le simulateur
        self._sim_ctx = None        # contexte mesure courant (simulateur uniquement)
        self._rng = _random.Random()   # PRNG local (graine OS -> varie à chaque run)
        self._ina = None
        if not self.simulate:
            self._i2c = busio.I2C(board.SCL, board.SDA)
            self._ads = ADS.ADS1115(self._i2c)
            # INA219 (conso) : optionnel — si la lib/capteur manque, la conso est
            # simulée et le reste des mesures continue en réel.
            if HAVE_INA219:
                try:
                    self._ina = _INA219(1, _INA219.INA219_I2C_ADDRESS4)
                    self._ina.begin()
                except Exception as e:           # noqa: BLE001
                    log.warning("INA219 indisponible (%s) -> conso simulee", e)
                    self._ina = None
        log.info("fxs_real en mode %s", "SIMULATION (PC)" if self.simulate else "REEL (Pi)")

    # -- GPIO ----------------------------------------------------
    def gpio(self, pins, level, sleep=0.0):
        if self.simulate:
            high = set(pins.split(",")) if level == "dh" else set()
            if level == "dh":
                self._sim_state.update({p: True for p in pins.split(",")})
            elif level == "dl":
                self._sim_state.update({p: False for p in pins.split(",")})
        else:
            subprocess.run(f"raspi-gpio set {pins} {level}", shell=True)
        # En simulation, pas de temps de stabilisation matériel -> exécution rapide.
        if sleep and not self.simulate:
            time.sleep(sleep)

    def _pin_high(self, pin):
        return bool(self._sim_state.get(str(pin), False))

    # -- ADC -----------------------------------------------------
    def read(self, channel, n=8, delay=0.005):
        """Tension moyenne sur un canal ADS1115 ('P0' ou 'P1')."""
        if self.simulate:
            return self._sim_read(channel)
        ch = ADS.P0 if channel == "P0" else ADS.P1
        chan = AnalogIn(self._ads, ch)
        total = 0.0
        for i in range(n):
            total += chan.voltage
            if i < n - 1:
                time.sleep(delay)
        return total / n

    # -- Conso (INA219) ------------------------------------------
    def read_power(self):
        """Puissance consommée par le gateway sous test (W). Réel via INA219
        (get_power_mW -> W) ; sinon simulée."""
        if self.simulate or self._ina is None:
            return self._sim_power()
        return self._ina.get_power_mW() / 1000.0

    def _sim_power(self):
        """Conso plausible ~12 W (bande 7-20 W). ~10% de cartes atypiques."""
        j = 1.0 + self._rng.uniform(-0.05, 0.05)
        drift = 1.0
        if self._rng.random() < 0.10:
            drift = 1.0 + self._rng.choice([-1, 1]) * self._rng.uniform(0.15, 0.35)
        return 12.0 * j * drift

    # -- Simulateur de lectures ---------------------------------
    def _sim_read(self, channel):
        """Renvoie une tension BRUTE telle que l'étalonnage du caller donne une
        valeur physique plausible. Utilise le contexte de mesure explicite
        (`self._sim_ctx`) posé par les fonctions measure_* — sans ambiguïté.
        ~10% des cartes simulées sont rendues atypiques pour exercer l'IA."""
        kind, port = (self._sim_ctx or ("tr", "FXS1"))
        j = lambda c: 1.0 + self._rng.uniform(-c, c)
        drift = 1.0
        if self._rng.random() < 0.10:                   # carte atypique occasionnelle
            drift = 1.0 + self._rng.choice([-1, 1]) * self._rng.uniform(0.06, 0.12)
        if kind == "tr":                                # ~47 V  (calib ×100)
            return (47.0 * j(0.015) * drift) / 100.0
        if kind == "cl":                                # ~36 mA (calib (V·K·1000)/470)
            ma = 36.0 * j(0.05) * drift
            return ma * CL_SHUNT_OHM / (CL_GAIN[port] * 1000.0)
        if kind == "ring":                              # ~38 Vrms (calib ×120)
            return (38.0 * j(0.03) * drift) / 120.0
        if kind == "trans_ve":                          # entrée de référence ~1 V
            self._sim_ve = 1.0 * j(0.01)
            return self._sim_ve
        if kind == "trans_vs":                          # sortie -> atténuation ~9.1 dB
            db = 9.1 * j(0.05) * drift
            return getattr(self, "_sim_ve", 1.0) * (10 ** (-db / 20.0))
        return 0.0


# ─────────────────────────────────────────────────────────────
#  Mesures par port (mirroir 1:1 des scripts)
# ─────────────────────────────────────────────────────────────
def measure_tr(b, port):
    for pins, lvl, slp in _TR_PREP:
        b.gpio(pins, lvl, slp)
    for pins, lvl, slp in _TR_SELECT[port]:
        b.gpio(pins, lvl, slp)
    b._sim_ctx = ("tr", port)
    v = b.read("P0")
    return v * 100.0                                   # -> V


def measure_cl(b, port):
    for pins, lvl, slp in _CL_SELECT[port]:
        b.gpio(pins, lvl, slp)
    b._sim_ctx = ("cl", port)
    v = b.read("P0")
    ma = (v * CL_GAIN[port] * 1000.0) / CL_SHUNT_OHM   # -> mA
    for pins, lvl in [(_CL_CLEANUP[0][0], _CL_CLEANUP[0][1])]:
        b.gpio(pins, lvl, _CL_CLEANUP[0][2])
    b.gpio(_CL_CLEANUP[1][0], _CL_CLEANUP[1][1])
    return ma


def _ring_prepare(b, port):
    """Met le chemin GPIO en mode lecture sonnerie pour `port` (une fois)."""
    for pins, lvl, slp in _RING[port]:
        b.gpio(pins, lvl, slp)
    b._sim_ctx = ("ring", port)


def _ring_sample(b):
    """Une lecture de sonnerie (Vrms) sur le chemin déjà préparé."""
    return b.read("P1", n=5) * 120.0


def measure_ring(b, port):
    """Mesure sonnerie SIMPLE (une lecture) — utilisée par validate_fxs_real."""
    _ring_prepare(b, port)
    return _ring_sample(b)                              # -> Vrms


def measure_trans(b, port, freq):
    cmd1, cmd2, cmd3 = _TRANS[(port, freq)]
    b.gpio(cmd1, "dl", 0.3)
    b.gpio(cmd2, "dh", 0.3)
    b.gpio(cmd3, "dh", 1.2)
    b._sim_ctx = ("trans_ve", port)
    ve = b.read("P1", n=5) * 1000.0                    # mV (entrée)
    b.gpio("12", "dl", 1.2)                            # bascule Ve -> Vs
    b._sim_ctx = ("trans_vs", port)
    vs = b.read("P1", n=5) * 1000.0                    # mV (sortie)
    b.gpio(_TRANS_CLEANUP[0], _TRANS_CLEANUP[1])
    if ve <= 0 or vs <= 0:
        return float("nan")
    return -20.0 * math.log10(vs / ve) - 1.0           # -> dB (atténuation) − 1 dB de perte (FXS1 & FXS2)


def measure_conso(b):
    """Consommation du gateway (M_CONS_CONSUMPTION) via INA219 — mesure NIVEAU
    GATEWAY (pas par port). Transcrit Conso.sh : 18 bas, 25 haut, puis lecture."""
    for pins, lvl, slp in _CONSO_PREP:
        b.gpio(pins, lvl, slp)
    return b.read_power()                               # -> W


# ─────────────────────────────────────────────────────────────
#  Séquence complète d'un gateway (2 ports) -> dict par port
# ─────────────────────────────────────────────────────────────
# Sonnerie : le téléphone sonne par CADENCE (sonne un peu, s'arrête un peu). Une seule
# lecture peut tomber dans le silence -> valeur "vide" (~14 V). On échantillonne donc
# jusqu'à RING_SAMPLES fois (espacées de RING_SAMPLE_DELAY s) et on garde le PIC ; on
# s'arrête dès qu'on capte une vraie sonnerie (valeur dans la bande).
RING_SAMPLES = 10
RING_SAMPLE_DELAY = 1.0   # s entre deux lectures (couvre la cadence de sonnerie)


def run_gateway_test(notify_callback=None, stop_check=None, simulate=None, slot=1,
                     ring_samples=RING_SAMPLES):
    """
    Teste un gateway complet (2 ports FXS1 + FXS2) et renvoie un dict par port,
    directement consommable par le dashboard et par fxs_ai.analyze().

    DÉROULÉ (3 phases de mesure + finalisation) :
      • Phase 1 — TENSION DE REPOS (TR) + COURANT DE LIGNE (CL), pour FXS1 puis FXS2.
                  Ligne au repos (pas de sonnerie) -> mesures vraies.
      • Phase 2 — SONNERIE : on déclenche la sonnerie sur le gateway (Telnet
                  scos-voice), puis on relit chaque port jusqu'à attraper la cadence
                  du téléphone, et on coupe la sonnerie.
      • Phase 3 — TRANSMISSION (atténuation 300/1000/3400 Hz), pour FXS1 puis FXS2.
      • Finalisation — clés héritées (compat), verdicts seuils, statut DONE.

    notify_callback(dict) : appelé après chaque (sous-)mesure -> temps réel web/mobile.
    stop_check()          : permet d'interrompre proprement entre deux mesures (STOP).
    simulate              : None = auto (réel sur Pi, sim sur PC) ; True/False forcé.
    """
    # ── Initialisation : banc (réel ou simulé) + état de résultats partagé ──
    b = _Bench(simulate=simulate)
    results = {
        "slot": slot, "status": "RUNNING", "step": 0, "total_steps": 9,
        "final": None, "pass_tr": None, "pass_cl": None,
        "pass_alarm": None, "pass_trans": None, "pass_conso": None,
        "ring_window_left": None,
    }

    def notify():
        # Pousse une copie de l'état courant vers le dashboard (SocketIO côté app).
        if notify_callback:
            notify_callback(dict(results))

    def stopped():
        # Vrai si l'utilisateur a demandé l'arrêt (bouton STOP) -> on abandonne.
        return bool(stop_check and stop_check())

    passes = {"tr": True, "cl": True, "alarm": True, "trans": True,  # ET des 2 ports
              "conso": True}                                         # conso = niveau gateway
    tr_ok = {}      # résultat TR par port (la sonnerie en dépend : ring ≈ TR/√2)
    step = 0        # compteur d'avancement (sur results["total_steps"])

    # ── Pilotage gateway : UNE session ouverte pour TOUT le test. `init` est fait
    #    ICI, AU DÉBUT, pour énergiser la ligne (sinon TR ≈ 0 V). Tolérant : gw=None
    #    si le gateway/serveur PC est injoignable (la mesure continue). En simulation,
    #    aucun pilotage gateway.
    gw = gateway_voice.open_session() if not b.simulate else None

    def gw_cleanup():
        # À appeler avant tout abandon/fin : coupe la sonnerie (au cas où) + ferme la
        # session Telnet. Pas de `p2p stop` : le DUT est retiré entre deux tests et le
        # prochain `init` remet tout à zéro.
        gateway_voice.ring_off(gw)
        gateway_voice.close_session(gw)

    # ═══════════════════════════════════════════════════════════════════════
    #  PHASE 1 — TENSION DE REPOS (TR) + COURANT DE LIGNE (CL), FXS1 puis FXS2
    #  Ligne au repos (aucune sonnerie en cours) : ce sont les vraies valeurs
    #  d'alimentation de la ligne. On mémorise le PASS/FAIL de TR par port
    #  (tr_ok) car la sonnerie en dépend (≈ TR/√2).
    # ═══════════════════════════════════════════════════════════════════════
    for port in ("FXS1", "FXS2"):
        p = port.lower()

        # 1a. Tension de repos (V, limites 44-50)
        if stopped(): gw_cleanup(); return _abort(results, notify)
        step += 1; results["step"] = step; results["status"] = f"TR_{port}"; notify()
        tr = measure_tr(b, port)
        results[f"tr_{p}"] = round(tr, 2)
        ok = TR_MIN <= tr <= TR_MAX; passes["tr"] &= ok
        tr_ok[port] = ok                     # mémorisé pour la phase sonnerie
        log.info("   %s TR = %.2f V -> %s", port, tr, "PASS" if ok else "FAIL")
        notify()

        # 1b. Courant de ligne (mA, limites 33-39)
        if stopped(): gw_cleanup(); return _abort(results, notify)
        step += 1; results["step"] = step; results["status"] = f"CL_{port}"; notify()
        cl = measure_cl(b, port)
        results[f"cl_{p}"] = round(cl, 2)
        ok = CL_MIN <= cl <= CL_MAX; passes["cl"] &= ok
        log.info("   %s CL = %.2f mA -> %s", port, cl, "PASS" if ok else "FAIL")
        notify()

    # ═══════════════════════════════════════════════════════════════════════
    #  PHASE 2 — SONNERIE (déclenchée APRÈS TR/CL des 2 ports)
    #  a) On déclenche la sonnerie sur le gateway par Telnet (scos-voice init +
    #     ring start). b) Le téléphone sonne par CADENCE (≈ 1 s on / 3 s off) : on
    #     relit chaque port jusqu'à `ring_samples` fois et on s'arrête au 1er essai
    #     DANS LA BANDE (PASS) ; sinon on garde la plus haute valeur -> FAIL.
    #     Réessais seulement si la TR du port est valide (sinon ring ≈ TR/√2 ne peut
    #     pas passer : 1 seule lecture). c) On coupe la sonnerie (ring stop).
    # ═══════════════════════════════════════════════════════════════════════
    if stopped(): gw_cleanup(); return _abort(results, notify)
    results["status"] = "RING_WAIT"
    log.info("   >>> SONNERIE : declenchement via gateway (scos-voice ring start) <<<")
    notify()

    # 2. Mesure de la sonnerie, PORT PAR PORT. Le gateway ne sonne qu'UNE rafale
    #    (~1,5 s) par `ring start`, PAS une cadence répétée : la tension n'apparaît
    #    qu'au tout début puis c'est le silence (~10 s) alors que `ring start` est
    #    encore actif. FXS1 (mesuré en 1er) consomme cette rafale -> on RÉ-DÉCLENCHE
    #    `ring start` AVANT CHAQUE port pour donner une rafale fraîche à FXS2.
    #    ATTENTION : AUCUN `ring stop` entre les ports (le toggle stop/start fige la
    #    sonnerie sur ce gateway). Un seul `ring stop`, à la fin (après FXS2).
    for port in ("FXS1", "FXS2"):
        p = port.lower()
        if stopped():
            gw_cleanup()                     # ne pas laisser la sonnerie active
            return _abort(results, notify)
        gateway_voice.ring_on(gw)            # rafale de sonnerie FRAÎCHE pour CE port (sans stop préalable)
        _ring_prepare(b, port)               # bascule le chemin GPIO sonnerie

        # Nb d'essais : 10 si TR OK, 1 sinon (sonnerie non valide quand TR hors limites).
        max_iter = ring_samples if tr_ok.get(port) else 1
        peak = 0.0                           # plus haute valeur vue (cas FAIL)
        caught = None                        # 1ère lecture dans la bande (cas PASS)
        reads = []                           # journal de tous les essais
        for i in range(max_iter):
            if stopped():
                gw_cleanup()
                return _abort(results, notify)
            v = _ring_sample(b)              # une lecture Vrms
            reads.append(round(v, 2))
            if v > peak:
                peak = v
            log.info("      %s sonnerie essai %2d/%d = %6.2f Vrms", port, i + 1, max_iter, v)
            if ALARM_MIN <= v <= ALARM_MAX:  # ring attrapé dans la bande -> PASS, on arrête
                caught = v
                results[f"alarm_rms_{p}"] = round(v, 2)
                notify()
                break
            results[f"alarm_rms_{p}"] = round(peak, 2)      # affiche le pic courant
            results["ring_window_left"] = max_iter - i - 1
            notify()
            if not b.simulate:
                time.sleep(RING_SAMPLE_DELAY)               # 1 s d'attente APRÈS CHAQUE essai (FXS1 & FXS2)

        # Valeur retenue + verdict : PASS si une lecture est tombée dans la bande.
        chosen = caught if caught is not None else peak
        ok = caught is not None
        results[f"alarm_rms_{p}"] = round(chosen, 2)
        passes["alarm"] &= ok
        cause = "" if tr_ok.get(port) else "  (TR hors limites -> sonnerie non valide)"
        log.info("   %s Sonnerie : essais=%s", port, reads)
        log.info("   %s Sonnerie CHOISIE = %.2f Vrms (%d essais) -> %s%s",
                 port, chosen, len(reads), "PASS" if ok else "FAIL", cause)

    # 2c. Coupe la sonnerie sur le gateway (ring stop). La session reste OUVERTE
    #     (on en a encore besoin pour le p2p de la transmission).
    gateway_voice.ring_off(gw)
    step += 2; results["step"] = step

    # ═══════════════════════════════════════════════════════════════════════
    #  PHASE 3 — TRANSMISSION (atténuation), FXS1 puis FXS2
    #  Pour chaque port : mesure 300/1000/3400 Hz. Le verdict PASS/FAIL porte sur
    #  le 1000 Hz (limites Sagem 8.1-10.1 dB) ; 300/3400 Hz sont mesurés pour info.
    #  PRÉALABLE : p2p start -> met les 2 ports en point-à-point (un port décroché),
    #  sinon la transmission ne peut pas être mesurée.
    # ═══════════════════════════════════════════════════════════════════════
    gateway_voice.p2p_on(gw)
    for port in ("FXS1", "FXS2"):
        p = port.lower()
        if stopped(): gw_cleanup(); return _abort(results, notify)
        step += 1; results["step"] = step; results["status"] = f"TRANS_{port}"; notify()
        for freq in (300, 1000, 3400):
            db = measure_trans(b, port, freq)
            results[f"trans_{freq}_{p}"] = round(db, 2)
            if freq == 1000:                 # seul le 1000 Hz décide du PASS/FAIL
                ok = TRANS_MIN <= db <= TRANS_MAX; passes["trans"] &= ok
                log.info("   %s Trans 1000Hz = %.2f dB -> %s", port, db, "PASS" if ok else "FAIL")
        notify()

    # ═══════════════════════════════════════════════════════════════════════
    #  PHASE 4 — CONSOMMATION GATEWAY (INA219, M_CONS_CONSUMPTION)
    #  Mesure NIVEAU GATEWAY (pas par port) : puissance totale consommée par le
    #  DUT. Verdict seuil ROW_DATA : 7-20 W. Transcrit Conso.sh (18 bas, 25 haut).
    # ═══════════════════════════════════════════════════════════════════════
    if stopped(): gw_cleanup(); return _abort(results, notify)
    step += 1; results["step"] = step; results["status"] = "CONSO"; notify()
    conso = measure_conso(b)
    results["conso_w"] = round(conso, 2)
    results["power"]   = round(conso, 2)          # remplit le champ legacy (W)
    ok = CONSO_MIN <= conso <= CONSO_MAX; passes["conso"] = ok
    log.info("   Consommation = %.2f W -> %s", conso, "PASS" if ok else "FAIL")
    notify()

    # Fin des mesures : on ferme la session gateway (pas de p2p stop — le DUT sera
    # retiré et le prochain test refera un init).
    gateway_voice.close_session(gw)

    # ═══════════════════════════════════════════════════════════════════════
    #  FINALISATION
    # ═══════════════════════════════════════════════════════════════════════
    # Clés héritées (mono-ligne = FXS1) pour la compat avec l'ancien dashboard.
    results.update({
        "tr": results.get("tr_fxs1"),
        "cl": (results.get("cl_fxs1") or 0) / 1000.0,   # legacy en Ampères
        "alarm_rms": results.get("alarm_rms_fxs1"),
        "trans_300": results.get("trans_300_fxs1"),
        "trans_1000": results.get("trans_1000_fxs1"),
        "trans_3400": results.get("trans_3400_fxs1"),
        # "power" déjà renseigné par la phase conso (W) — ne pas écraser.
    })

    # Verdicts seuils niveau gateway (ET des 2 ports) + résultat final + statut DONE.
    results["pass_tr"]    = passes["tr"]
    results["pass_cl"]    = passes["cl"]
    results["pass_alarm"] = passes["alarm"]
    results["pass_trans"] = passes["trans"]
    results["pass_conso"] = passes["conso"]
    results["final"]  = all(passes.values())   # PASS global si tout passe
    results["status"] = "DONE"
    results["step"]   = results["total_steps"]
    log.info("Gateway slot %s : %s", slot, "PASS" if results["final"] else "FAIL")
    notify()
    return results


def _abort(results, notify):
    results["status"] = "STOPPED"
    results["final"] = False
    notify()
    return results


# ─────────────────────────────────────────────────────────────
#  Exécution autonome (sur le Pi : python fxs_real.py)
# ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    res = run_gateway_test()
    import json
    print(json.dumps({k: v for k, v in res.items() if k != "slot"}, indent=2, default=str))
