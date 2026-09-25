from __future__ import annotations

from pathlib import Path
import json

import cv2
import numpy as np

try:
    from base_config import BASE_DIR
except ImportError:
    BASE_DIR = Path(__file__).resolve().parents[1]

from train_sign_detector.labels import SIGN_LABELS

PACKAGE_DIR = Path(__file__).resolve().parent
DATASET_PATH = PACKAGE_DIR / "dataset"
COLLECTED_DATASET_PATH = PACKAGE_DIR / "collected_dataset"
MODEL_FILE = Path(BASE_DIR) / "assets" / "svm_model.xml"
MODEL_METADATA_FILE = MODEL_FILE.with_suffix(MODEL_FILE.suffix + ".metadata.json")

winSize = (32, 32)
blockSize = (16, 16)
blockStride = (8, 8)
cellSize = (8, 8)
nbins = 9
hog = cv2.HOGDescriptor(
    winSize, blockSize, blockStride, cellSize, nbins,
    1, 4.0, 0, 0.2, 0, 64
)


def extract_features(image):
    img_resized = cv2.resize(image, (32, 32))
    hsv = cv2.cvtColor(img_resized, cv2.COLOR_BGR2HSV)
    hist = cv2.calcHist(
        [hsv], [0, 1], None, [16, 16], [0, 180, 0, 256]
    )
    cv2.normalize(hist, hist)
    color_features = hist.flatten()
    gray = cv2.cvtColor(img_resized, cv2.COLOR_BGR2GRAY)
    hog_features = hog.compute(gray).flatten()
    return np.concatenate((color_features, hog_features)).astype(np.float32)


def load_dataset(dataset_path=DATASET_PATH):
    dataset_path = DATASET_PATH if dataset_path is None else Path(dataset_path)
    labels, features_list = [], []
    if not dataset_path.exists():
        return None, None
    for label_dir in sorted(dataset_path.iterdir()):
        if not label_dir.is_dir() or not label_dir.name.isdigit():
            continue
        label = int(label_dir.name)
        if label not in SIGN_LABELS:
            continue
        for img_path in sorted(label_dir.iterdir()):
            if (
                not img_path.is_file()
                or img_path.suffix.lower() not in {".png", ".jpg", ".jpeg"}
            ):
                continue
            image = cv2.imread(str(img_path), cv2.IMREAD_COLOR)
            if image is None:
                continue
            features_list.append(extract_features(image))
            labels.append(label)
    if not features_list:
        return None, None
    return (
        np.asarray(features_list, dtype=np.float32),
        np.asarray(labels, dtype=np.int32),
    )


def load_model_compatible(model_file=MODEL_FILE):
    model_file = Path(model_file)
    if not model_file.exists():
        legacy = Path(BASE_DIR) / "rf_model.xml"
        if legacy.exists():
            model_file = legacy
        else:
            return None
    metadata_file = model_file.with_suffix(model_file.suffix + ".metadata.json")
    try:
        model = cv2.ml.SVM_load(str(model_file))
        if metadata_file.exists():
            metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
            mapping = {
                int(k): v
                for k, v in metadata.get("class_mapping", {}).items()
            }
            if (
                metadata.get("model_type") != "svm"
                or mapping != SIGN_LABELS
            ):
                raise ValueError(
                    "traffic-sign model metadata does not match "
                    "the runtime contract"
                )
        return model
    except Exception:
        try:
            return cv2.ml.RTrees_load(str(model_file))
        except Exception:
            return None


def train_and_evaluate(
    retrain=False,
    dataset_path=DATASET_PATH,
    model_file=MODEL_FILE,
):
    model_file = Path(model_file)
    dataset_path = DATASET_PATH if dataset_path is None else Path(dataset_path)
    if not retrain:
        model = load_model_compatible(model_file)
        if model is not None:
            return model
    features, labels = load_dataset(dataset_path)
    if features is None:
        return load_model_compatible(model_file)
    if len(set(labels.tolist())) < 2:
        raise ValueError(
            "training requires at least two numeric sign classes"
        )
    svm = cv2.ml.SVM_create()
    svm.setType(cv2.ml.SVM_C_SVC)
    svm.setKernel(cv2.ml.SVM_RBF)
    svm.trainAuto(features, cv2.ml.ROW_SAMPLE, labels)
    model_file.parent.mkdir(parents=True, exist_ok=True)
    svm.save(str(model_file))
    metadata = {
        "model_type": "svm",
        "feature_contract": "HSV-16x16-histogram + HOG(32x32)",
        "class_mapping": {str(k): v for k, v in SIGN_LABELS.items()},
    }
    model_file.with_suffix(
        model_file.suffix + ".metadata.json"
    ).write_text(
        json.dumps(metadata, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return svm


def get_label(model, image):
    if model is None or image is None or image.size == 0:
        return 0
    try:
        features = extract_features(image)
        _, result = model.predict(
            np.asarray([features], dtype=np.float32)
        )
        label = int(result[0][0])
        return label if label in SIGN_LABELS else 0
    except Exception:
        return 0
