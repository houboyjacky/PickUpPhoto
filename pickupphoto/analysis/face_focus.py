"""
analysis/face_focus.py — 眼睛對焦分析（可選模組）

使用 MediaPipe FaceMesh 偵測人臉，計算眼部區域清晰度。
若 mediapipe 未安裝，graceful skip（回傳 None）。

Mac Metal 加速：MediaPipe 在 Apple Silicon 上自動使用 Metal delegate。
"""

from __future__ import annotations

from typing import Any

import numpy as np

# 嘗試 import mediapipe，未安裝時設 flag
try:
    import mediapipe as mp

    _MP_AVAILABLE = True
    _face_mesh: Any = None  # lazy init
except ImportError:
    _MP_AVAILABLE = False
    mp = None  # type: ignore
    _face_mesh = None


def is_available() -> bool:
    """回傳 mediapipe 是否已安裝。"""
    return _MP_AVAILABLE


def compute_eye_focus(image: np.ndarray) -> tuple[float | None, bool]:
    """
    計算眼睛對焦分數。

    Args:
        image: RGB uint8 numpy array (H, W, 3)

    Returns:
        (score, has_face)
        - score: 0.0–100.0（眼部清晰度），無人臉時為 None
        - has_face: 是否偵測到人臉
    """
    if not _MP_AVAILABLE:
        return None, False

    mesh = _get_face_mesh()
    results = mesh.process(image)

    if not results.multi_face_landmarks:
        return None, False

    # 取第一張臉的眼部 landmark
    landmarks = results.multi_face_landmarks[0]
    h, w = image.shape[:2]

    left_eye_region = _extract_eye_region(image, landmarks, _LEFT_EYE_INDICES, w, h)
    right_eye_region = _extract_eye_region(image, landmarks, _RIGHT_EYE_INDICES, w, h)

    scores = []
    for region in [left_eye_region, right_eye_region]:
        if region is not None and region.size > 0:
            from pickupphoto.analysis.sharpness import compute_sharpness
            scores.append(compute_sharpness(region))

    if not scores:
        return None, True

    avg_score = sum(scores) / len(scores)
    return round(avg_score, 2), True


def _get_face_mesh():
    """Lazy-init MediaPipe FaceMesh（避免啟動時載入模型）。"""
    global _face_mesh
    if _face_mesh is None:
        _face_mesh = mp.solutions.face_mesh.FaceMesh(
            static_image_mode=True,
            max_num_faces=1,
            refine_landmarks=True,
            min_detection_confidence=0.5,
        )
    return _face_mesh


def _extract_eye_region(
    image: np.ndarray,
    landmarks,
    indices: list[int],
    img_w: int,
    img_h: int,
) -> np.ndarray | None:
    """從 FaceMesh landmark 提取眼部 bounding box 區域。"""
    xs = [int(landmarks.landmark[i].x * img_w) for i in indices]
    ys = [int(landmarks.landmark[i].y * img_h) for i in indices]

    x_min, x_max = max(0, min(xs) - 5), min(img_w, max(xs) + 5)
    y_min, y_max = max(0, min(ys) - 5), min(img_h, max(ys) + 5)

    if x_max <= x_min or y_max <= y_min:
        return None

    return image[y_min:y_max, x_min:x_max]


# MediaPipe FaceMesh 眼部 landmark 索引
# 參考：https://github.com/google/mediapipe/blob/master/mediapipe/modules/face_geometry/data/canonical_face_model_uv_visualization.png
_LEFT_EYE_INDICES = [
    33, 7, 163, 144, 145, 153, 154, 155, 133,
    173, 157, 158, 159, 160, 161, 246,
]
_RIGHT_EYE_INDICES = [
    362, 382, 381, 380, 374, 373, 390, 249,
    263, 466, 388, 387, 386, 385, 384, 398,
]
