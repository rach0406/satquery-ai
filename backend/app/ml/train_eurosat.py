"""Remote-sensing domain adaptation: train the scene-classification head.

Run:

    python -m app.ml.train_eurosat --limit-per-class 800

The script downloads **EuroSAT** (Helber et al., 2019) - 27,000 labelled
Sentinel-2 patches over 10 land-use classes - extracts the remote-sensing
feature representation from :mod:`app.ml.features`, fits a gradient-boosted
classifier, and writes the model plus a full evaluation report (held-out
accuracy, per-class precision/recall/F1 and the confusion matrix) to
``data/models/``.

The reported accuracy is measured on a stratified held-out split that the
model never sees during fitting. The API serves those measured numbers
verbatim; nothing about model performance is ever asserted from memory.

Citation:
    P. Helber, B. Bischke, A. Dengel, D. Borth. "EuroSAT: A Novel Dataset and
    Deep Learning Benchmark for Land Use and Land Cover Classification."
    IEEE JSTARS, 2019.
"""
from __future__ import annotations

import argparse
import io
import json
import pickle
import random
import sys
import time
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.config import settings          # noqa: E402
from app.ml.features import extract_batch, feature_names  # noqa: E402

EUROSAT_URLS = (
    "https://zenodo.org/records/7711810/files/EuroSAT_RGB.zip",
    "https://madm.dfki.de/files/sentinel/EuroSAT.zip",
)

CLASS_DESCRIPTIONS = {
    "AnnualCrop": "annual cropland - seasonal agricultural fields",
    "Forest": "closed-canopy forest",
    "HerbaceousVegetation": "herbaceous vegetation / shrubland",
    "Highway": "highway and major road corridors",
    "Industrial": "industrial buildings and facilities",
    "Pasture": "pasture and grazing land",
    "PermanentCrop": "permanent crops - orchards, vineyards, plantations",
    "Residential": "residential built-up area",
    "River": "river channels",
    "SeaLake": "sea, lake and large open water",
}

#: Maps EuroSAT labels onto the coarse classes the segmenter also uses, so
#: the classifier and the index-based segmentation speak the same language.
COARSE_MAP = {
    "AnnualCrop": "sparse_vegetation",
    "Forest": "dense_vegetation",
    "HerbaceousVegetation": "sparse_vegetation",
    "Highway": "built_up",
    "Industrial": "built_up",
    "Pasture": "sparse_vegetation",
    "PermanentCrop": "dense_vegetation",
    "Residential": "built_up",
    "River": "water",
    "SeaLake": "water",
}

MODEL_FILE = "eurosat_rs_classifier.pkl"
REPORT_FILE = "eurosat_rs_classifier.report.json"


def download(dest: Path) -> Path:
    if dest.exists() and dest.stat().st_size > 50_000_000:
        print(f"[data] using cached archive {dest} ({dest.stat().st_size / 1e6:.0f} MB)")
        return dest
    last: Exception | None = None
    for url in EUROSAT_URLS:
        try:
            print(f"[data] downloading EuroSAT from {url}")
            req = urllib.request.Request(url, headers={"User-Agent": "SatQueryAI/1.0"})
            with urllib.request.urlopen(req, timeout=180) as r, open(dest, "wb") as f:
                total = int(r.headers.get("Content-Length", 0))
                got = 0
                while chunk := r.read(1 << 20):
                    f.write(chunk)
                    got += len(chunk)
                    if total:
                        pct = got / total * 100
                        print(f"\r[data]   {got / 1e6:6.1f} / {total / 1e6:.0f} MB ({pct:5.1f}%)",
                              end="", flush=True)
                print()
            return dest
        except Exception as exc:
            last = exc
            print(f"\n[data] failed: {exc}")
    raise RuntimeError(f"Could not download EuroSAT from any mirror: {last}")


def load_patches(zip_path: Path, limit_per_class: int, seed: int = 42
                 ) -> tuple[np.ndarray, np.ndarray, list[str]]:
    rng = random.Random(seed)
    with zipfile.ZipFile(zip_path) as zf:
        members = [n for n in zf.namelist() if n.lower().endswith(".jpg")]
        by_class: dict[str, list[str]] = {}
        for name in members:
            parts = [p for p in name.split("/") if p]
            if len(parts) < 2:
                continue
            label = parts[-2]
            if label not in CLASS_DESCRIPTIONS:
                continue
            by_class.setdefault(label, []).append(name)

        if not by_class:
            raise RuntimeError("No EuroSAT class folders found inside the archive.")

        classes = sorted(by_class)
        print(f"[data] {len(members)} images, {len(classes)} classes: "
              + ", ".join(f"{c}={len(by_class[c])}" for c in classes))

        X_img: list[np.ndarray] = []
        y: list[int] = []
        for ci, c in enumerate(classes):
            files = by_class[c]
            rng.shuffle(files)
            take = files[:limit_per_class]
            for fn in take:
                with zf.open(fn) as fh:
                    img = Image.open(io.BytesIO(fh.read())).convert("RGB")
                X_img.append(np.asarray(img, dtype=np.uint8))
                y.append(ci)
            print(f"[data]   {c:24s} loaded {len(take)}")
    return np.stack(X_img), np.asarray(y), classes


def main() -> int:
    ap = argparse.ArgumentParser(description="Adapt the scene classifier to remote-sensing imagery.")
    ap.add_argument("--limit-per-class", type=int, default=800,
                    help="Patches per class (2700 available). 800 keeps training under ~3 min.")
    ap.add_argument("--test-size", type=float, default=0.25)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--archive", type=Path, default=None)
    args = ap.parse_args()

    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.metrics import (accuracy_score, classification_report,
                                 confusion_matrix, f1_score)
    from sklearn.model_selection import train_test_split
    from sklearn.preprocessing import StandardScaler

    settings.ensure_dirs()
    archive = args.archive or (settings.data_dir / "EuroSAT_RGB.zip")
    download(archive)

    t0 = time.time()
    X_img, y, classes = load_patches(archive, args.limit_per_class, args.seed)
    print(f"[feat] extracting remote-sensing features from {len(X_img)} patches ...")
    X = extract_batch(X_img)
    print(f"[feat] feature matrix {X.shape} in {time.time() - t0:.1f}s")

    X_tr, X_te, y_tr, y_te = train_test_split(
        X, y, test_size=args.test_size, random_state=args.seed, stratify=y
    )
    scaler = StandardScaler().fit(X_tr)
    X_tr_s, X_te_s = scaler.transform(X_tr), scaler.transform(X_te)

    print(f"[fit ] training on {len(X_tr)} patches, holding out {len(X_te)} ...")
    t1 = time.time()
    clf = HistGradientBoostingClassifier(
        max_iter=400, learning_rate=0.1, max_depth=None, max_leaf_nodes=48,
        l2_regularization=1.0, early_stopping=True, validation_fraction=0.12,
        random_state=args.seed,
    )
    clf.fit(X_tr_s, y_tr)
    fit_s = time.time() - t1

    y_pred = clf.predict(X_te_s)
    acc = float(accuracy_score(y_te, y_pred))
    f1m = float(f1_score(y_te, y_pred, average="macro"))
    cm = confusion_matrix(y_te, y_pred).tolist()
    rep = classification_report(y_te, y_pred, target_names=classes, output_dict=True, zero_division=0)

    print(f"[eval] held-out accuracy {acc * 100:.2f}%  macro-F1 {f1m:.3f}  (fit {fit_s:.1f}s)")
    print(classification_report(y_te, y_pred, target_names=classes, zero_division=0))

    model_path = settings.models_dir / MODEL_FILE
    with open(model_path, "wb") as f:
        pickle.dump({
            "scaler": scaler,
            "classifier": clf,
            "classes": classes,
            "coarse_map": COARSE_MAP,
            "class_descriptions": CLASS_DESCRIPTIONS,
            "feature_names": feature_names(),
            "patch_size": 64,
        }, f)

    report = {
        "model": "eurosat_rs_classifier",
        "version": "1.0.0",
        "backend": "sklearn.HistGradientBoostingClassifier",
        "adapted_on": "EuroSAT RGB (Helber et al., 2019) - 27,000 labelled Sentinel-2 patches",
        "dataset_url": "https://zenodo.org/records/7711810",
        "citation": ("P. Helber, B. Bischke, A. Dengel, D. Borth, EuroSAT: A Novel Dataset and "
                     "Deep Learning Benchmark for Land Use and Land Cover Classification, "
                     "IEEE JSTARS, 2019."),
        "classes": classes,
        "class_descriptions": CLASS_DESCRIPTIONS,
        "coarse_map": COARSE_MAP,
        "n_features": int(X.shape[1]),
        "n_train": int(len(X_tr)),
        "n_test": int(len(X_te)),
        "patches_per_class": args.limit_per_class,
        "test_accuracy": acc,
        "macro_f1": f1m,
        "per_class": {
            c: {
                "precision": rep[c]["precision"],
                "recall": rep[c]["recall"],
                "f1": rep[c]["f1-score"],
                "support": rep[c]["support"],
            } for c in classes
        },
        "confusion_matrix": cm,
        "fit_seconds": round(fit_s, 2),
        "trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "evaluation_protocol": (
            f"Stratified {int((1 - args.test_size) * 100)}/{int(args.test_size * 100)} "
            "train/test split, seed "
            f"{args.seed}. Metrics are measured on the held-out split only."
        ),
    }
    (settings.models_dir / REPORT_FILE).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"[save] {model_path}")
    print(f"[save] {settings.models_dir / REPORT_FILE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
