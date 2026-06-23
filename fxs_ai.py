"""
fxs_ai.py — Inference IA du banc FXS (module en ligne)
=======================================================
Charge le bundle Isolation Forest (`fxs_iso.joblib`) une seule fois et
expose `analyze(results)` : à partir d'un dict de résultats du banc
(TESTF.run_test_sequence / fake_test_sequence) il produit un verdict IA
« typique / atypique (dérive) » + la mesure responsable (explicabilité).

But : compléter les seuils Sagem en signalant les cartes DANS LES LIMITES
mais atypiques (dérive précoce). Voir [[project_ai_scope]].

Mapping banc -> 8 features modèle
---------------------------------
Le banc mesure une ligne FXS et renvoie : tr (V), cl (A), alarm_rms (V RMS),
trans_1000 (dB). Le modèle attend 4 mesures × FXS1 & FXS2.
 - Conversion d'unité : cl est en AMPÈRES -> ×1000 pour des mA (limites 33-39).
 - Par port : on utilise les clés explicites par port si elles existent
   (tr_fxs1/tr_fxs2, ...). Sinon on duplique la ligne mesurée sur FXS1 ET FXS2
   (même carte, ports quasi identiques — vecteur reste dans la distribution
   d'entraînement). Quand la passe FXS2 réelle sera ajoutée au banc, il suffit
   de renseigner les clés *_fxs2 : aucune autre modification ici.
"""

import warnings
from pathlib import Path

# numpy/joblib (et sklearn via le bundle) peuvent manquer sur le banc (ex. Pi sans
# libopenblas, ou version Python incompatible). Dans ce cas l'IA est simplement
# DÉSACTIVÉE : `analyze()` renvoie « IA indisponible » et la mesure/le dashboard
# continuent normalement. On n'importe donc JAMAIS numpy au niveau module de façon
# bloquante.
try:
    import numpy as np
    import joblib
    _DEPS_OK = True
    _DEPS_ERR = ""
except Exception as _e:           # noqa: BLE001 — l'IA ne doit pas casser le banc
    np = None
    joblib = None
    _DEPS_OK = False
    _DEPS_ERR = str(_e)

# Le bundle a pu être entraîné sous une version sklearn différente ; on ne veut
# pas que l'avertissement pollue les logs du banc.
warnings.filterwarnings("ignore", category=UserWarning, module="sklearn")

BASE = Path(__file__).parent
# On préfère le bundle racine (régénéré par make_ia.py sur sklearn courant),
# avec repli sur models/.
_BUNDLE_PATHS = [BASE / "fxs_iso.joblib", BASE / "models" / "fxs_iso.joblib"]

# col modèle -> (clé par-port, échelle par-port, clé ligne-unique, échelle ligne-unique)
# - clé par-port : émise par fxs_real.py, déjà en UNITÉS MODÈLE (mA, V, Vrms, dB)
#   => échelle 1.0.
# - clé ligne-unique : repli legacy (ancien TESTF mono-ligne) où `cl` est en
#   AMPÈRES => ×1000 pour des mA. L'ordre n'importe pas : on assemble selon
#   bundle["fxs_cols"].
_MEASURE_MAP = {
    "M_FXS_RESTVOLTAGE_FXS1": ("tr_fxs1", 1.0, "tr", 1.0),
    "M_FXS_RESTVOLTAGE_FXS2": ("tr_fxs2", 1.0, "tr", 1.0),
    "M_FXS_LIGNECURENT_FXS1": ("cl_fxs1", 1.0, "cl", 1000.0),   # par-port déjà en mA ; legacy A->mA
    "M_FXS_LIGNECURENT_FXS2": ("cl_fxs2", 1.0, "cl", 1000.0),
    "M_FXS_ALARMVOLTAGE_FXS1": ("alarm_rms_fxs1", 1.0, "alarm_rms", 1.0),
    "M_FXS_ALARMVOLTAGE_FXS2": ("alarm_rms_fxs2", 1.0, "alarm_rms", 1.0),
    "M_FXS_TRANS_FXS1_1000HZ": ("trans_1000_fxs1", 1.0, "trans_1000", 1.0),
    "M_FXS_TRANS_FXS2_1000HZ": ("trans_1000_fxs2", 1.0, "trans_1000", 1.0),
}

# Libellés courts pour l'affichage du diagnostic.
_SHORT = {
    "M_FXS_RESTVOLTAGE_FXS1": "Tension repos FXS1", "M_FXS_RESTVOLTAGE_FXS2": "Tension repos FXS2",
    "M_FXS_LIGNECURENT_FXS1": "Courant ligne FXS1", "M_FXS_LIGNECURENT_FXS2": "Courant ligne FXS2",
    "M_FXS_ALARMVOLTAGE_FXS1": "Sonnerie FXS1", "M_FXS_ALARMVOLTAGE_FXS2": "Sonnerie FXS2",
    "M_FXS_TRANS_FXS1_1000HZ": "Transmission FXS1", "M_FXS_TRANS_FXS2_1000HZ": "Transmission FXS2",
}

# Libellés des verdicts seuils (pour nommer la cause d'un ECHEC).
_PASS_LABELS = {
    "pass_tr": "Tension de repos", "pass_cl": "Courant de ligne",
    "pass_alarm": "Sonnerie", "pass_trans": "Transmission",
    "pass_conso": "Consommation",
}

# Limites par mesure (lo, hi, libellé) pour la MARGE-AU-SEUIL.
# COMPLEMENT DETERMINISTE : aucune influence sur le modèle Isolation Forest.
_LIMITS = {
    "tr_fxs1": (44.0, 50.0, "Tension repos FXS1"),
    "tr_fxs2": (44.0, 50.0, "Tension repos FXS2"),
    "cl_fxs1": (33.0, 39.0, "Courant ligne FXS1"),
    "cl_fxs2": (33.0, 39.0, "Courant ligne FXS2"),
    "alarm_rms_fxs1": (35.0, 41.0, "Sonnerie FXS1"),
    "alarm_rms_fxs2": (35.0, 41.0, "Sonnerie FXS2"),
    "trans_1000_fxs1": (8.1, 10.1, "Transmission FXS1"),
    "trans_1000_fxs2": (8.1, 10.1, "Transmission FXS2"),
    "conso_w": (7.0, 20.0, "Consommation"),
}
# Seuils de sévérité sur la marge (en % de la largeur de bande ; 50% = plein centre).
_ALERT_MARGIN = 8.0    # < 8%  -> ALERTE  (très proche du seuil, risque imminent)
_WATCH_MARGIN = 18.0   # < 18% -> A SURVEILLER


def margins_to_limit(results):
    """Marge de chaque mesure présente à son seuil le plus proche, en % de la
    largeur de bande. 50% = centre de bande, 0% = pile sur un seuil, <0 = hors bande.
    100% déterministe (pas de ML) — complète l'Isolation Forest sans le modifier."""
    out = {}
    for key, (lo, hi, label) in _LIMITS.items():
        v = results.get(key)
        if v is None:
            continue
        try:
            v = float(v)
        except (TypeError, ValueError):
            continue
        width = hi - lo
        if width <= 0:
            continue
        out[label] = round(min(v - lo, hi - v) / width * 100.0, 1)
    return out

_bundle = None


def load(force=False):
    """Charge (et met en cache) le bundle modèle. Lève si deps/fichier absents."""
    global _bundle
    if not _DEPS_OK:
        raise RuntimeError(f"dependances IA indisponibles (numpy/joblib) : {_DEPS_ERR}")
    if _bundle is not None and not force:
        return _bundle
    for p in _BUNDLE_PATHS:
        if p.exists():
            _bundle = joblib.load(p)
            _bundle["_path"] = str(p)
            return _bundle
    raise FileNotFoundError(
        f"Bundle IA introuvable ({', '.join(str(p) for p in _BUNDLE_PATHS)}). "
        "Lancer make_ia.py pour le (re)générer."
    )


def _feature_value(results, port_key, port_scale, single_key, single_scale):
    """Valeur d'une feature : clé par-port (unités modèle) si dispo, sinon
    repli sur la ligne unique legacy (avec sa propre conversion)."""
    v = results.get(port_key)
    if v is not None:
        try:
            return float(v) * port_scale
        except (TypeError, ValueError):
            return None
    v = results.get(single_key)
    if v is None:
        return None
    try:
        return float(v) * single_scale
    except (TypeError, ValueError):
        return None


def build_features(results):
    """results (dict du banc) -> dict {col_modèle: valeur ou None}."""
    feats = {}
    for col, (port_key, port_scale, single_key, single_scale) in _MEASURE_MAP.items():
        feats[col] = _feature_value(results, port_key, port_scale, single_key, single_scale)
    return feats


def analyze(results):
    """
    Score une carte et renvoie un verdict IA explicable.

    Retourne un dict à clés `ai_*` (préfixées pour fusion directe dans l'état
    du banc / la base). En cas d'échec (bundle absent, etc.) renvoie un verdict
    neutre plutôt que de lever — le banc ne doit jamais planter à cause de l'IA.
    """
    try:
        b = load()
    except Exception as e:  # noqa: BLE001 — l'IA ne doit pas casser le banc
        return _unavailable(str(e))

    cols = b["fxs_cols"]
    median = b["profile"]["median"]      # dict {col: val}
    model = b["model"]
    threshold = float(b["threshold"])

    feats = build_features(results)
    imputed = [c for c in cols if feats.get(c) is None]
    x = np.array([[feats[c] if feats[c] is not None else float(median[c]) for c in cols]],
                 dtype=float)

    score = float(model.score_samples(x)[0])
    atypical = bool(score < threshold)

    # --- Explicabilité : contribution par mesure (re-score patché à la médiane)
    contrib = {}
    for i, c in enumerate(cols):
        patched = x.copy()
        patched[0, i] = float(median[c])
        new_score = float(model.score_samples(patched)[0])
        contrib[c] = max(new_score - score, 0.0)   # >0 => mesure aggravante
    total = sum(contrib.values()) or 1.0
    culprit = max(cols, key=lambda c: contrib[c])
    culprit_pct = int(round(100 * contrib[culprit] / total))

    final = results.get("final")
    if atypical and final is True:
        verdict = "ATYPIQUE - dans les limites mais a surveiller (derive)"
    elif atypical:
        verdict = "ATYPIQUE"
    else:
        verdict = "TYPIQUE"

    culprit_label = _SHORT.get(culprit, culprit)
    failed = [lbl for key, lbl in _PASS_LABELS.items() if results.get(key) is False]

    # === COMPLEMENT DETERMINISTE (n'impacte PAS le modèle Isolation Forest) ===
    # A) Marge-au-seuil : la mesure la PLUS PROCHE de son seuil (la plus à risque).
    margins = margins_to_limit(results)
    if margins:
        min_label = min(margins, key=margins.get)
        min_margin = margins[min_label]
    else:
        min_label, min_margin = None, None

    # D) Sévérité : OK / WATCH / ALERT / FAIL (combine seuils + marge + IA).
    #    - FAIL  : hors seuils (déterministe, l'IA n'ajoute rien).
    #    - ALERT : passe mais une mesure est TRÈS proche du seuil (risque imminent).
    #    - WATCH : passe mais marge faible OU atypique (à surveiller).
    #    - OK    : passe, marges confortables, typique.
    if final is False:
        severity, ai_relevant = "FAIL", False
    elif min_margin is not None and min_margin < _ALERT_MARGIN:
        severity, ai_relevant = "ALERT", True
    elif (min_margin is not None and min_margin < _WATCH_MARGIN) or atypical:
        severity, ai_relevant = "WATCH", True
    else:
        severity, ai_relevant = "OK", True

    # Recommandation maintenance (texte) selon la sévérité.
    if severity == "FAIL":
        cause = ", ".join(failed) if failed else "mesure hors limites"
        recommendation = (
            f"Carte en ECHEC ({cause}) : cause deterministe par les seuils. "
            f"L'analyse IA n'apporte rien de plus ici — controler/reparer la mesure en defaut."
        )
    elif severity == "ALERT":
        drift = f" + derive IA sur {culprit_label}" if atypical else ""
        recommendation = (
            f"ALERTE : {min_label} tres proche du seuil (marge {min_margin}% de la bande){drift}. "
            f"Risque de defaillance imminent — maintenance recommandee AVANT mise en service."
        )
    elif severity == "WATCH":
        if atypical and min_margin is not None and min_margin < _WATCH_MARGIN:
            recommendation = (
                f"A SURVEILLER : {min_label} a {min_margin}% du seuil ET derive IA sur "
                f"{culprit_label} (~{culprit_pct}%). Planifier une maintenance preventive."
            )
        elif atypical:
            recommendation = (
                f"A SURVEILLER : conforme aux seuils mais atypique (derive IA sur "
                f"{culprit_label}, ~{culprit_pct}%). Surveiller cette mesure."
            )
        else:
            recommendation = (
                f"A SURVEILLER : {min_label} se rapproche du seuil (marge {min_margin}%). "
                f"Conforme, mais a controler aux prochains tests."
            )
    else:  # OK
        m = f" (marge mini {min_margin}% sur {min_label})" if min_margin is not None else ""
        recommendation = f"Conforme, marges confortables{m} — aucune action requise (RAS)."

    return {
        "ai_available": True,
        "ai_score": round(score, 3),
        "ai_threshold": round(threshold, 3),
        "ai_atypical": atypical,
        "ai_verdict": verdict,
        "ai_culprit": culprit_label,
        "ai_culprit_pct": culprit_pct,
        "ai_relevant": ai_relevant,        # True = carte PASS (l'IA est utile ici)
        "ai_severity": severity,           # OK / WATCH / ALERT / FAIL
        "ai_min_margin": min_margin,       # % de marge de la mesure la plus à risque
        "ai_min_margin_measure": min_label,
        "ai_margins": margins,             # {libellé: marge %} (toutes les mesures)
        "ai_recommendation": recommendation,
        "ai_imputed": imputed,   # features non mesurées (FXS2 dupliqué/imputé)
    }


def _unavailable(reason):
    return {
        "ai_available": False,
        "ai_score": None,
        "ai_threshold": None,
        "ai_atypical": None,
        "ai_verdict": "IA indisponible",
        "ai_culprit": None,
        "ai_culprit_pct": None,
        "ai_relevant": None,
        "ai_severity": None,
        "ai_min_margin": None,
        "ai_min_margin_measure": None,
        "ai_margins": {},
        "ai_recommendation": None,
        "ai_imputed": [],
        "ai_error": reason,
    }
