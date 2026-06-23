#!/usr/bin/env python3
"""
train_on_pi.py — (PI) reconstruit le bundle modele IA avec la version sklearn du Pi
===================================================================================
Lit `fxs_train_normal.csv` (features des cartes NORMAL) et entraine un Isolation
Forest IDENTIQUE a make_ia.py, puis sauvegarde `fxs_iso.joblib`. Comme l'entrainement
ET l'inference (app.py) utilisent la MEME installation scikit-learn, le bundle se
charge sans probleme de version (contrairement au bundle 1.8 fait sur PC).

Usage (sur le Pi, apres avoir installe numpy/scikit-learn/joblib) :
    python3 train_on_pi.py

Dependances : numpy, scikit-learn, joblib (pas besoin de pandas).
"""
import csv
from pathlib import Path

import numpy as np
import joblib
from sklearn.ensemble import IsolationForest

BASE = Path(__file__).parent
CSV = BASE / "fxs_train_normal.csv"

FXS_COLS = [
    'M_FXS_RESTVOLTAGE_FXS1', 'M_FXS_RESTVOLTAGE_FXS2',
    'M_FXS_LIGNECURENT_FXS1', 'M_FXS_LIGNECURENT_FXS2',
    'M_FXS_ALARMVOLTAGE_FXS1', 'M_FXS_ALARMVOLTAGE_FXS2',
    'M_FXS_TRANS_FXS1_1000HZ', 'M_FXS_TRANS_FXS2_1000HZ',
]
FXS_LIMITS = {
    'M_FXS_RESTVOLTAGE_FXS1': (44.0, 50.0), 'M_FXS_RESTVOLTAGE_FXS2': (44.0, 50.0),
    'M_FXS_LIGNECURENT_FXS1': (33.0, 39.0), 'M_FXS_LIGNECURENT_FXS2': (33.0, 39.0),
    'M_FXS_ALARMVOLTAGE_FXS1': (35.0, 41.0), 'M_FXS_ALARMVOLTAGE_FXS2': (35.0, 41.0),
    'M_FXS_TRANS_FXS1_1000HZ': (8.1, 10.1), 'M_FXS_TRANS_FXS2_1000HZ': (8.1, 10.1),
}
FP_BUDGET = 0.05


def main():
    if not CSV.exists():
        raise SystemExit(f"Introuvable : {CSV} (uploadez fxs_train_normal.csv a cote de ce script)")

    # Lecture CSV -> X (sans pandas)
    rows = []
    with open(CSV, newline="") as f:
        reader = csv.reader(f)
        header = next(reader)
        idx = [header.index(c) for c in FXS_COLS]   # tolere un ordre de colonnes different
        for r in reader:
            rows.append([float(r[i]) for i in idx])
    X = np.asarray(rows, dtype=float)
    print(f"Donnees : {X.shape[0]} cartes NORMAL x {X.shape[1]} features")

    # Entrainement (memes hyper-parametres que make_ia.py)
    iso = IsolationForest(n_estimators=300, contamination="auto",
                          max_samples="auto", random_state=42, n_jobs=-1).fit(X)

    scores = iso.score_samples(X)
    threshold = float(np.percentile(scores, 100 * FP_BUDGET))

    profile = {
        "mean":   {c: float(X[:, i].mean()) for i, c in enumerate(FXS_COLS)},
        "std":    {c: float(X[:, i].std(ddof=1)) for i, c in enumerate(FXS_COLS)},
        "median": {c: float(np.median(X[:, i])) for i, c in enumerate(FXS_COLS)},
    }

    bundle = {
        "model": iso,
        "profile": profile,
        "threshold": threshold,
        "fxs_cols": FXS_COLS,
        "limits": FXS_LIMITS,
        "fp_budget": FP_BUDGET,
    }

    out = BASE / "fxs_iso.joblib"
    joblib.dump(bundle, out)
    import sklearn
    print(f"Bundle sauvegarde -> {out}")
    print(f"  scikit-learn : {sklearn.__version__}   seuil : {threshold:.4f}")
    pct = 100 * float((scores < threshold).mean())
    print(f"  controle : {pct:.1f}% des cartes NORMAL signalees (cible {FP_BUDGET*100:.0f}%)")


if __name__ == "__main__":
    main()
