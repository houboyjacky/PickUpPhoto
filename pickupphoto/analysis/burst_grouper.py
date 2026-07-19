"""
analysis/burst_grouper.py — 連拍群組自動分組與最佳幀推薦

依 EXIF 時間戳（含次秒）將相鄰照片（間距 ≤ 閾值）歸為同一連拍群組，
再依加權分數選出群組最佳幀（AI 推薦 🏆）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pickupphoto.core.scanner import PhotoInfo

# 預設連拍時間閾值（秒）
DEFAULT_BURST_GAP_SEC = 3.0

# 最佳幀加權公式
_WEIGHT_SHARPNESS = 0.45
_WEIGHT_EXPOSURE = 0.25
_WEIGHT_EYE_FOCUS = 0.20
_WEIGHT_NO_BLUR = 0.10


@dataclass
class BurstGroup:
    """單一連拍群組。"""

    group_id: str
    photos: list["PhotoInfo"] = field(default_factory=list)
    best_filename: str | None = None
    scores: dict[str, float] = field(default_factory=dict)  # filename → composite


def group_burst_photos(
    photos: list["PhotoInfo"],
    gap_sec: float = DEFAULT_BURST_GAP_SEC,
) -> list[BurstGroup]:
    """
    將照片依時間戳分組，相鄰照片間距 ≤ gap_sec 歸入同群組。

    Args:
        photos: 已依 sort_key 排序的 PhotoInfo 清單
        gap_sec: 連拍時間閾值（秒），預設 3.0

    Returns:
        BurstGroup 清單（僅包含 ≥2 張的群組；單張不分組）
    """
    from pickupphoto.core.scanner import get_burst_timestamp

    if not photos:
        return []

    groups: list[BurstGroup] = []
    current_group: list["PhotoInfo"] = [photos[0]]
    prev_ts = get_burst_timestamp(photos[0])

    for photo in photos[1:]:
        ts = get_burst_timestamp(photo)
        if ts == 0.0 or prev_ts == 0.0:
            # 無時間戳：無法分組，結束當前群組
            if len(current_group) >= 2:
                groups.append(_make_group(current_group, len(groups)))
            current_group = [photo]
        elif (ts - prev_ts) <= gap_sec:
            current_group.append(photo)
        else:
            if len(current_group) >= 2:
                groups.append(_make_group(current_group, len(groups)))
            current_group = [photo]
        prev_ts = ts if ts != 0.0 else prev_ts

    # 處理最後一組
    if len(current_group) >= 2:
        groups.append(_make_group(current_group, len(groups)))

    return groups


def select_best_in_groups(
    groups: list[BurstGroup],
    ai_scores: dict[str, dict],
    use_eye_focus: bool = False,
) -> list[BurstGroup]:
    """
    依 AI 分數計算每個群組的最佳幀。

    Args:
        groups: 連拍群組清單
        ai_scores: {filename: {sharpness, exposure, motion_blur, eye_focus, has_face}}
        use_eye_focus: 是否啟用眼睛對焦加權

    Returns:
        同 groups，但每個 BurstGroup 的 best_filename 與 scores 已填入
    """
    for group in groups:
        best_score = -1.0
        best_filename: str | None = None

        for photo in group.photos:
            scores = ai_scores.get(photo.filename)
            if scores is None:
                continue
            composite = _compute_composite(scores, use_eye_focus)
            group.scores[photo.filename] = composite
            if composite > best_score or (
                composite == best_score and best_filename is not None
                and photo.filename < best_filename  # tie-break by filename
            ):
                best_score = composite
                best_filename = photo.filename

        group.best_filename = best_filename

        # 更新 PhotoInfo.ai_best 標記
        for photo in group.photos:
            photo.ai_best = (photo.filename == best_filename)

    return groups


def apply_group_metadata(
    groups: list[BurstGroup],
    photos_by_filename: dict[str, "PhotoInfo"],
) -> None:
    """
    將群組資訊（group_id、rank）寫回 PhotoInfo。
    單張照片（不在任何群組）的 burst_group_id 保持 None。
    """
    for group in groups:
        for rank, photo in enumerate(group.photos, start=1):
            p = photos_by_filename.get(photo.filename)
            if p:
                p.burst_group_id = group.group_id
                p.burst_group_rank = rank


# ─── 內部工具 ────────────────────────────────────────────────


def _make_group(photos: list["PhotoInfo"], index: int) -> BurstGroup:
    """建立一個 BurstGroup，分配字母群組 ID（A, B, ..., AA, AB, ...）。"""
    group_id = _index_to_label(index)
    return BurstGroup(group_id=group_id, photos=list(photos))


def _index_to_label(index: int) -> str:
    """將 0-based index 轉為字母標籤（0→A, 1→B, ..., 25→Z, 26→AA...）。"""
    label = ""
    n = index
    while True:
        label = chr(ord("A") + n % 26) + label
        n = n // 26 - 1
        if n < 0:
            break
    return label


def _compute_composite(
    scores: dict,
    use_eye_focus: bool,
) -> float:
    """
    計算加權綜合分數。

    眼睛對焦未啟用或無人臉時，其權重重新分配至對焦清晰度。
    """
    sharpness = float(scores.get("sharpness") or 0.0)
    exposure = float(scores.get("exposure") or 0.0)
    motion_blur = float(scores.get("motion_blur") or 0.0)
    eye_focus = float(scores.get("eye_focus") or 0.0)
    has_face = bool(scores.get("has_face"))

    if use_eye_focus and has_face and scores.get("eye_focus") is not None:
        w_sharp = _WEIGHT_SHARPNESS
        w_exp = _WEIGHT_EXPOSURE
        w_eye = _WEIGHT_EYE_FOCUS
        w_blur = _WEIGHT_NO_BLUR
    else:
        # 眼睛對焦權重重新分配給清晰度
        w_sharp = _WEIGHT_SHARPNESS + _WEIGHT_EYE_FOCUS
        w_exp = _WEIGHT_EXPOSURE
        w_eye = 0.0
        w_blur = _WEIGHT_NO_BLUR
        eye_focus = 0.0

    return (
        sharpness * w_sharp
        + exposure * w_exp
        + eye_focus * w_eye
        + motion_blur * w_blur
    )
