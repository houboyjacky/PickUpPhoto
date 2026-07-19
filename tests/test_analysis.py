"""
tests/test_analysis.py — analysis 模組單元測試

使用合成圖像測試各分析函數的邊界值與預期行為。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import numpy as np
import pytest

from pickupphoto.analysis.sharpness import compute_sharpness
from pickupphoto.analysis.exposure import compute_exposure, exposure_details
from pickupphoto.analysis.motion_blur import compute_motion_blur
from pickupphoto.analysis.burst_grouper import (
    BurstGroup,
    _compute_composite,
    _index_to_label,
    group_burst_photos,
    select_best_in_groups,
)
from pickupphoto.core.scanner import PhotoInfo


# ─── 合成圖像工具 ─────────────────────────────────────────────


def make_sharp_image(size: int = 64) -> np.ndarray:
    """建立高對比棋盤格圖（清晰）。"""
    img = np.zeros((size, size, 3), dtype=np.uint8)
    for i in range(size):
        for j in range(size):
            if (i + j) % 2 == 0:
                img[i, j] = [255, 255, 255]
    return img


def make_blurry_image(size: int = 64) -> np.ndarray:
    """建立均勻灰色圖（模糊，低 variance）。"""
    return np.full((size, size, 3), 128, dtype=np.uint8)


def make_overexposed_image(size: int = 64) -> np.ndarray:
    """建立純白圖（過曝）。"""
    return np.full((size, size, 3), 255, dtype=np.uint8)


def make_underexposed_image(size: int = 64) -> np.ndarray:
    """建立純黑圖（欠曝）。"""
    return np.full((size, size, 3), 0, dtype=np.uint8)


def make_normal_exposure_image(size: int = 64) -> np.ndarray:
    """建立中等亮度圖（正常曝光）。"""
    return np.full((size, size, 3), 128, dtype=np.uint8)


def make_photo(dt: datetime | None, name: str, subsec: str = "") -> PhotoInfo:
    return PhotoInfo(
        path=Path(f"/fake/{name}"),
        filename=name,
        mtime=0,
        file_size=1000,
        datetime_taken=dt,
        datetime_subsec=subsec,
    )


# ─── Sharpness ───────────────────────────────────────────────


class TestSharpness:
    def test_sharp_image_high_score(self):
        img = make_sharp_image()
        score = compute_sharpness(img)
        assert score > 50.0, f"Expected > 50, got {score}"

    def test_blurry_image_low_score(self):
        img = make_blurry_image()
        score = compute_sharpness(img)
        assert score < 10.0, f"Expected < 10, got {score}"

    def test_score_range(self):
        for img in [make_sharp_image(), make_blurry_image()]:
            score = compute_sharpness(img)
            assert 0.0 <= score <= 100.0

    def test_grayscale_input(self):
        gray = np.full((32, 32), 128, dtype=np.uint8)
        score = compute_sharpness(gray)
        assert 0.0 <= score <= 100.0

    def test_sharp_beats_blurry(self):
        assert compute_sharpness(make_sharp_image()) > compute_sharpness(make_blurry_image())


# ─── Exposure ────────────────────────────────────────────────


class TestExposure:
    def test_overexposed_low_score(self):
        img = make_overexposed_image()
        score = compute_exposure(img)
        assert score < 50.0, f"Expected < 50, got {score}"

    def test_underexposed_low_score(self):
        img = make_underexposed_image()
        score = compute_exposure(img)
        assert score < 50.0, f"Expected < 50, got {score}"

    def test_normal_exposure_high_score(self):
        # 中等亮度不觸發 clipping → 高分
        img = np.full((64, 64, 3), 128, dtype=np.uint8)
        score = compute_exposure(img)
        assert score > 80.0, f"Expected > 80, got {score}"

    def test_score_range(self):
        for img in [make_overexposed_image(), make_underexposed_image(), make_normal_exposure_image()]:
            assert 0.0 <= compute_exposure(img) <= 100.0

    def test_exposure_details_keys(self):
        img = make_normal_exposure_image()
        details = exposure_details(img)
        assert "score" in details
        assert "highlight_ratio" in details
        assert "shadow_ratio" in details
        assert "mean_brightness" in details


# ─── Motion Blur ─────────────────────────────────────────────


class TestMotionBlur:
    def test_sharp_image_high_score(self):
        img = make_sharp_image()
        score = compute_motion_blur(img)
        assert score > 30.0, f"Expected > 30 for sharp image, got {score}"

    def test_uniform_image_score_range(self):
        img = make_blurry_image()
        score = compute_motion_blur(img)
        assert 0.0 <= score <= 100.0

    def test_score_always_in_range(self):
        for img in [make_sharp_image(), make_blurry_image(), make_overexposed_image()]:
            assert 0.0 <= compute_motion_blur(img) <= 100.0


# ─── Burst Grouper ───────────────────────────────────────────


class TestIndexToLabel:
    def test_basic(self):
        assert _index_to_label(0) == "A"
        assert _index_to_label(1) == "B"
        assert _index_to_label(25) == "Z"
        assert _index_to_label(26) == "AA"
        assert _index_to_label(27) == "AB"


class TestGroupBurstPhotos:
    def test_single_photo_no_group(self):
        photos = [make_photo(datetime(2024, 1, 1, 10, 0, 0), "a.NEF")]
        groups = group_burst_photos(photos, gap_sec=3.0)
        assert groups == []

    def test_two_close_photos_one_group(self):
        photos = [
            make_photo(datetime(2024, 1, 1, 10, 0, 0), "a.NEF"),
            make_photo(datetime(2024, 1, 1, 10, 0, 2), "b.NEF"),
        ]
        groups = group_burst_photos(photos, gap_sec=3.0)
        assert len(groups) == 1
        assert len(groups[0].photos) == 2

    def test_two_far_photos_no_group(self):
        photos = [
            make_photo(datetime(2024, 1, 1, 10, 0, 0), "a.NEF"),
            make_photo(datetime(2024, 1, 1, 10, 0, 5), "b.NEF"),
        ]
        groups = group_burst_photos(photos, gap_sec=3.0)
        assert groups == []

    def test_multiple_groups(self):
        photos = [
            make_photo(datetime(2024, 1, 1, 10, 0, 0), "a.NEF"),
            make_photo(datetime(2024, 1, 1, 10, 0, 1), "b.NEF"),
            make_photo(datetime(2024, 1, 1, 10, 0, 2), "c.NEF"),
            make_photo(datetime(2024, 1, 1, 10, 0, 8), "d.NEF"),  # 新群組
            make_photo(datetime(2024, 1, 1, 10, 0, 9), "e.NEF"),
        ]
        groups = group_burst_photos(photos, gap_sec=3.0)
        assert len(groups) == 2
        assert groups[0].group_id == "A"
        assert groups[1].group_id == "B"
        assert len(groups[0].photos) == 3
        assert len(groups[1].photos) == 2

    def test_no_datetime_handled(self):
        photos = [
            make_photo(None, "a.NEF"),
            make_photo(None, "b.NEF"),
        ]
        # 無時間戳不應 crash
        groups = group_burst_photos(photos, gap_sec=3.0)
        assert isinstance(groups, list)


class TestSelectBestInGroups:
    def test_best_selected(self):
        photos = [
            make_photo(datetime(2024, 1, 1, 10, 0, 0), "a.NEF"),
            make_photo(datetime(2024, 1, 1, 10, 0, 1), "b.NEF"),
        ]
        group = BurstGroup(group_id="A", photos=photos)
        ai_scores = {
            "a.NEF": {"sharpness": 50.0, "exposure": 50.0, "motion_blur": 50.0},
            "b.NEF": {"sharpness": 90.0, "exposure": 80.0, "motion_blur": 70.0},
        }
        result = select_best_in_groups([group], ai_scores)
        assert result[0].best_filename == "b.NEF"
        assert photos[1].ai_best is True
        assert photos[0].ai_best is False

    def test_no_scores_no_best(self):
        photos = [make_photo(datetime(2024, 1, 1, 10, 0, 0), "a.NEF")]
        group = BurstGroup(group_id="A", photos=photos)
        result = select_best_in_groups([group], ai_scores={})
        assert result[0].best_filename is None


class TestComputeComposite:
    def test_without_eye_focus(self):
        scores = {"sharpness": 80.0, "exposure": 60.0, "motion_blur": 70.0}
        composite = _compute_composite(scores, use_eye_focus=False)
        expected = 80.0 * 0.65 + 60.0 * 0.25 + 70.0 * 0.10
        assert abs(composite - expected) < 0.01

    def test_with_eye_focus_no_face(self):
        scores = {"sharpness": 80.0, "exposure": 60.0, "motion_blur": 70.0,
                  "eye_focus": 90.0, "has_face": False}
        # 無人臉 → 眼睛權重歸入清晰度
        score_with = _compute_composite(scores, use_eye_focus=True)
        score_without = _compute_composite(scores, use_eye_focus=False)
        assert abs(score_with - score_without) < 0.01
