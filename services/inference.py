"""
services/inference.py  –  Model registry, image preprocessing, and warm-start
loaders for all four diagnostic networks plus the dual fracture/tumor pipeline.

Hardware load balancing
-----------------------
* TF models (osteoporosis, osteoarthritis) on the system GPU with memory growth.
* PyTorch fracture and tumor models on internal CUDA when available.
"""

import os
import threading

import numpy as np
import torch
from PIL import Image
from torchvision import transforms

from services.audit import audit_logger

# ── Tunable parameters ─────────────────────────────────────────────────────────
# Decision threshold for the tumor classifier — published with the model in
# TUMOR_INFO.txt. Probability >= TUMOR_THRESHOLD → "Tumor", else "Normal".
# Override via the MEDIDIAG_TUMOR_THRESHOLD env var for clinical recalibration
# without a redeploy.
TUMOR_THRESHOLD = float(os.environ.get("MEDIDIAG_TUMOR_THRESHOLD", "0.79"))

# Image preprocessing sizes for each model family.
FRACTURE_INPUT_SIZE = (224, 224)
TUMOR_INPUT_SIZE = (512, 512)
KNEE_INPUT_SIZE = (224, 224)

# ImageNet normalization stats (used by both PyTorch transforms below).
_IMAGENET_MEAN = [0.485, 0.456, 0.406]
_IMAGENET_STD = [0.229, 0.224, 0.225]

# ── Model registry ─────────────────────────────────────────────────────────────
#   key  → (filename, input_size, class_labels)
MODEL_REGISTRY = {
    "fracture": {
        "filename":  "Fracture.pt",
        "input_size": (224, 224),
        "labels":    ["Fracture: Normal", "Fracture: Detected"],
    },
    "tumor": {
        "filename":  "tumor_model.pt",
        "input_size": (512, 512),
        "labels":    ["Tumor: Normal", "Tumor: Detected"],
    },
    "osteoarthritis": {
        "filename":  "osteoarthritis_model.h5",
        "input_size": (224, 224),
        "labels":    [
            "(Healthy)",
            "Doubtful",
            "Mild",
            "Moderate",
            "Severe",
        ],
    },
    "osteoporosis": {
        "filename":  "osteoporosis_model.h5",
        "input_size": (224, 224),
        "labels":    ["Osteoporosis: Normal", "Osteoporosis: Detected"],
    },
}

# Warm-start global cache: model_key → preloaded model object
GLOBAL_MODELS: dict = {}

# Kellgren-Lawrence grade names for the osteoarthritis classifier output.
OSTEO_GRADE_NAMES = {
    0: "Healthy",
    1: "Doubtful",
    2: "Mild",
    3: "Moderate",
    4: "Severe",
}

# Map from internal `winning_model` token → human-readable scan type.
SCAN_TYPE_LABELS = {
    "fracture":       "Fracture Detection",
    "tumor":          "Tumor Detection",
    "combined_knee":  "Degenerative Knee Diseases",
    "osteoarthritis": "Degenerative Knee Diseases",
    "osteoporosis":   "Degenerative Knee Diseases",
    "degenerative_knee": "Degenerative Knee Diseases",
}

# Tumor preprocessing: 512x512 + ImageNet normalization (built once).
_TUMOR_TRANSFORM = transforms.Compose([
    transforms.Resize(TUMOR_INPUT_SIZE),
    transforms.ToTensor(),
    transforms.Normalize(mean=_IMAGENET_MEAN, std=_IMAGENET_STD),
])

# PyTorch device for the fracture and tumor models (CUDA if available).
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print(f"PyTorch GPU Setup: using device {device}")

# Fracture classifier: ResNet50 transfer-learning, 224x224, ImageNet norm.
_FRACTURE_TRANSFORM = transforms.Compose([
    transforms.Resize(FRACTURE_INPUT_SIZE),
    transforms.ToTensor(),
    transforms.Normalize(mean=_IMAGENET_MEAN, std=_IMAGENET_STD),
])

# Lazy-loaded standalone Keras 3 handle, protected by a lock so concurrent
# requests during a cold start can't both run the heavy import + memory-growth
# setup at once.
_keras = None
_keras_lock = threading.Lock()


def _ensure_keras():
    """Import Keras 3 lazily (first model request only).

    Uses `tf.keras` (Keras 3 since TF 2.16) — no standalone `keras` package
    required. Thread-safe: under concurrent first requests, the first thread
    holds the lock through the heavy `import tensorflow` and memory-growth
    setup; subsequent threads see the cached `_keras` and return immediately.
    """
    global _keras
    if _keras is not None:
        return _keras

    with _keras_lock:
        # Double-checked: another thread may have populated _keras while
        # we waited for the lock.
        if _keras is not None:
            return _keras

        import tensorflow as tf

        # Memory growth must be set before any GPU op; doing it under the
        # lock guarantees we don't race against an in-flight GPU init.
        try:
            gpus = tf.config.list_physical_devices('GPU')
            for gpu in gpus:
                tf.config.experimental.set_memory_growth(gpu, True)
        except Exception as e:
            print(f"TF Memory Growth warning: {e}")

        _keras = tf.keras
        audit_logger.info(f"Keras {_keras.__version__} loaded (GPU enabled).")
        return _keras


def _prepare_image_pytorch(file_path: str, transform, target_device) -> torch.Tensor:
    """Resize and ImageNet-normalize an image into a batched PyTorch tensor."""
    img = Image.open(file_path).convert("RGB")
    return transform(img).unsqueeze(0).to(target_device)


def _load_fracture_model(path: str, target_device: torch.device):
    """Load the ResNet50 fracture classifier state_dict from Fracture.pt."""
    from torchvision.models import resnet50
    m = resnet50(weights=None)
    m.fc = torch.nn.Linear(m.fc.in_features, 2)
    state = torch.load(path, map_location=target_device, weights_only=True)
    m.load_state_dict(state)
    m.to(target_device)
    m.eval()
    return m


def build_osteo_model():
    from keras.applications import Xception
    from keras.layers import (
        Activation,
        BatchNormalization,
        Conv2D,
        GlobalAveragePooling2D,
    )
    from keras.models import Model

    input_shape = (224, 224, 3)
    xception = Xception(weights=None, include_top=False, input_shape=input_shape)
    x = xception.output
    x = Conv2D(filters=1024, kernel_size=3, padding="same")(x)
    x = BatchNormalization()(x)
    x = Activation("relu")(x)
    x = Conv2D(filters=256, kernel_size=3, padding="same")(x)
    x = BatchNormalization()(x)
    x = Activation("relu")(x)
    x = Conv2D(filters=64, kernel_size=3, padding="same")(x)
    x = BatchNormalization()(x)
    x = Activation("relu")(x)
    x = Conv2D(filters=5, kernel_size=3, padding="same")(x)
    x = BatchNormalization()(x)
    x = Activation("relu")(x)
    GAP = GlobalAveragePooling2D()(x)
    pred = Activation("softmax")(GAP)
    return Model(inputs=xception.input, outputs=pred)


def prepare_image_osteo(image_path):
    img = Image.open(image_path)
    img = img.resize(KNEE_INPUT_SIZE)
    if img.mode != "RGB":
        img = img.convert("RGB")
    img_array = np.array(img) / 255.0
    return np.expand_dims(img_array, axis=0)


def prepare_image_osteoporosis(image_path):
    import tensorflow as tf
    img = tf.io.read_file(image_path)
    img = tf.io.decode_image(img, channels=3, expand_animations=False)
    img = tf.image.resize(img, list(KNEE_INPUT_SIZE))
    img = tf.cast(img, tf.float32) / 255.0
    img = tf.expand_dims(img, axis=0)
    return img


def run_fracture_inference(file_path: str) -> tuple[str, int, str]:
    """Run fracture inference (224x224).
    
    Returns:
        (ai_result: str, ai_confidence: int, winning_model: str)
    """
    try:
        frac_model = GLOBAL_MODELS["fracture"]
        frac_arr = _prepare_image_pytorch(file_path, _FRACTURE_TRANSFORM, device)
        with torch.no_grad():
            probs = torch.softmax(frac_model(frac_arr), dim=-1)[0]
        # Per Fracture_INFO.txt: index 0 = fractured, index 1 = not fractured.
        fracture_prob = float(probs[0])
        normal_prob = float(probs[1])

        if fracture_prob > normal_prob:
            frac_label = "Fractured"
            frac_conf = fracture_prob * 100
        else:
            frac_label = "Non-fractured"
            frac_conf = normal_prob * 100

        audit_logger.info("MEDICAL – fracture inference completed")
    except Exception as exc:
        audit_logger.error(f"Fracture model failed during inference: {exc}")
        frac_label = "Error"
        frac_conf = 0.0

    if frac_label == "Error":
        raise RuntimeError("Fracture model failed to run.")

    ai_result = frac_label
    return ai_result, int(frac_conf), "fracture"


def run_tumor_inference(file_path: str) -> tuple[str, int, str]:
    """Run tumor inference (224x224).
    
    Returns:
        (ai_result: str, ai_confidence: int, winning_model: str)
    """
    try:
        tumor_model = GLOBAL_MODELS["tumor"]
        tumor_arr = _prepare_image_pytorch(file_path, _TUMOR_TRANSFORM, device)
        with torch.no_grad():
            output = tumor_model(tumor_arr)
            if output.shape[-1] == 1:
                # Standard contract: single logit → sigmoid → P(tumor).
                tumor_p = torch.sigmoid(output).item()
            else:
                # Defensive fallback for a multi-class build of the model.
                probs = torch.softmax(output, dim=-1)[0]
                tumor_p = float(probs[1])

        if tumor_p >= TUMOR_THRESHOLD:
            tumor_label = "Tumor"
            tumor_conf = tumor_p * 100
        else:
            tumor_label = "Normal"
            tumor_conf = (1.0 - tumor_p) * 100

        audit_logger.info("MEDICAL – tumor inference completed")
    except Exception as exc:
        audit_logger.error(f"Tumor model failed during inference: {exc}")
        tumor_label = "Error"
        tumor_conf = 0.0

    if tumor_label == "Error":
        raise RuntimeError("Tumor model failed to run.")

    ai_result = tumor_label
    return ai_result, int(tumor_conf), "tumor"


def run_degenerative_knee_inference(file_path: str) -> tuple[str, int, str]:
    """Run dual inference for osteoporosis and osteoarthritis.
    
    Returns:
        (ai_result: str, ai_confidence: int, winning_model: str)
    """
    knee_errors = []

    # 1. Osteoarthritis
    try:
        osteoarthritis_model = GLOBAL_MODELS["osteoarthritis"]
        img_array = prepare_image_osteo(file_path)
        prediction = osteoarthritis_model.predict(img_array, verbose=0)[0]
        predicted_class = int(np.argmax(prediction))
        osteo_conf = float(prediction[predicted_class]) * 100
        osteo_label = OSTEO_GRADE_NAMES[predicted_class]
    except KeyError:
        audit_logger.error("Osteoarthritis model not loaded in GLOBAL_MODELS")
        osteo_label, osteo_conf = "Unavailable", 0.0
        knee_errors.append("osteoarthritis")
    except Exception as exc:
        audit_logger.error(f"Osteoarthritis inference failed: {type(exc).__name__}")
        osteo_label, osteo_conf = "Unavailable", 0.0
        knee_errors.append("osteoarthritis")

    # 2. Osteoporosis
    try:
        osteoporosis_model = GLOBAL_MODELS["osteoporosis"]
        img_tensor = prepare_image_osteoporosis(file_path)
        prob = float(osteoporosis_model.predict(img_tensor, verbose=0)[0][0])
        if prob > 0.5:
            op_label, op_conf = "Osteoporosis", prob * 100
        else:
            op_label, op_conf = "Normal", (1.0 - prob) * 100
    except KeyError:
        audit_logger.error("Osteoporosis model not loaded in GLOBAL_MODELS")
        op_label, op_conf = "Unavailable", 0.0
        knee_errors.append("osteoporosis")
    except Exception as exc:
        audit_logger.error(f"Osteoporosis inference failed: {type(exc).__name__}")
        op_label, op_conf = "Unavailable", 0.0
        knee_errors.append("osteoporosis")

    if len(knee_errors) == 2:
        raise RuntimeError("Both knee models failed to run.")

    ai_result = (
        f"Osteoarthritis: {osteo_label}. "
        f"Osteoporosis: {op_label}."
    )
    
    findings = []
    # Fixing the bug in the original logic: labels are "Healthy", "Mild", etc., not "KL Grade X"
    if "osteoarthritis" not in knee_errors and osteo_label not in ["Healthy", "Doubtful", "Unavailable"]:
        findings.append(("osteoarthritis", osteo_conf))
    if "osteoporosis" not in knee_errors and op_label == "Osteoporosis":
        findings.append(("osteoporosis", op_conf))

    if findings:
        leading_model, ai_confidence_f = max(findings, key=lambda x: x[1])
    elif "osteoarthritis" in knee_errors and "osteoporosis" not in knee_errors:
        leading_model, ai_confidence_f = "osteoporosis", op_conf
    elif "osteoporosis" in knee_errors and "osteoarthritis" not in knee_errors:
        leading_model, ai_confidence_f = "osteoarthritis", osteo_conf
    elif osteo_conf >= op_conf and "osteoarthritis" not in knee_errors:
        leading_model, ai_confidence_f = "osteoarthritis", osteo_conf
    elif "osteoporosis" not in knee_errors:
        leading_model, ai_confidence_f = "osteoporosis", op_conf
    else:
        leading_model, ai_confidence_f = "combined_knee", 0.0

    audit_logger.info("MEDICAL – degenerative knee inference completed")
    return ai_result, int(ai_confidence_f), leading_model


def preload_models(model_dir: str) -> None:
    """Eagerly load every model at server boot with explicit device placement."""
    print("Initiating Model Warm Start...")
    audit_logger.info("Initiating Model Warm Start...")

    _ensure_keras()
    import tensorflow as tf

    # 1. TF models -> system GPU (memory growth applied via _ensure_keras)
    try:
        print("Loading Osteoporosis (GPU)...")
        path = os.path.join(model_dir, MODEL_REGISTRY["osteoporosis"]["filename"])
        GLOBAL_MODELS['osteoporosis'] = tf.keras.models.load_model(path, compile=False)
        audit_logger.info("Osteoporosis model loaded on system GPU.")
    except Exception as exc:
        audit_logger.error(f"Osteoporosis preload failed: {exc}")

    try:
        print("Loading Osteoarthritis (GPU)...")
        path = os.path.join(model_dir, MODEL_REGISTRY["osteoarthritis"]["filename"])
        oa = build_osteo_model()
        oa.load_weights(path)
        GLOBAL_MODELS['osteoarthritis'] = oa
        audit_logger.info("Osteoarthritis model loaded on system GPU.")
    except Exception as exc:
        audit_logger.error(f"Osteoarthritis preload failed: {exc}")

    # 2. Heavy PyTorch tumor model -> internal CUDA
    try:
        print("Loading Tumor Model (PyTorch GPU)...")
        path = os.path.join(model_dir, MODEL_REGISTRY["tumor"]["filename"])
        m = torch.jit.load(path, map_location=device)
        m.eval()
        GLOBAL_MODELS['tumor'] = m
        audit_logger.info(f"Tumor model loaded on {device}.")
    except Exception as exc:
        audit_logger.error(f"Tumor preload failed: {exc}")

    # 3. PyTorch fracture model -> internal CUDA (CPU fallback via `device`)
    try:
        print("Loading Fracture (PyTorch GPU)...")
        path = os.path.join(model_dir, MODEL_REGISTRY["fracture"]["filename"])
        GLOBAL_MODELS['fracture'] = _load_fracture_model(path, device)
        audit_logger.info(f"Fracture model loaded on {device}.")
    except Exception as exc:
        audit_logger.error(f"Fracture preload failed: {exc}")

    print("All models successfully preloaded!")
    audit_logger.info("All models successfully preloaded!")
