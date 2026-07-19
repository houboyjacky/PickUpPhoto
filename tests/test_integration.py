"""
tests/test_integration.py — 整合測試

涵蓋：
- exporter 篩選與複製流程（md5 驗證）
- 快取 TTL 對話邏輯
- 跨 session 資料恢復（ratings.json → SQLite）
- 連拍群組完整流程
"""

from __future__ import annotations

import hashlib
import shutil
from datetime import datetime
from pathlib import Path

import numpy as np
import pytest

from pickupphoto.core.database import Database
from pickupphoto.core.scanner import PhotoInfo
from pickupphoto.core.thumbnail_cache import delete_cache, get_cache_info
from pickupphoto.output.exporter import (
    ConflictAction,
    ExportConfig,
    FilterMode,
    export_photos,
    filter_photos,
    verify_copy_integrity,
)
from pickupphoto.analysis.burst_grouper import (
    group_burst_photos,
    select_best_in_groups,
    apply_group_metadata,
)


# ─── 工具 ────────────────────────────────────────────────────


def make_photo(name: str, stars: int = 0, dt: datetime | None = None, tmp_path: Path | None = None) -> PhotoInfo:
    """建立帶有真實檔案的 PhotoInfo（用於複製測試）。"""
    if tmp_path is not None:
        p = tmp_path / name
        p.write_bytes(b"FAKEFILE_" + name.encode())
    else:
        p = Path("/fake") / name
    return PhotoInfo(
        path=p,
        filename=name,
        mtime=12345,
        file_size=100,
        datetime_taken=dt,
        stars=stars,
    )


# ─── Exporter 篩選 ────────────────────────────────────────────


class TestFilterPhotos:
    def test_gte_filter(self):
        photos = [make_photo(f"{i}.NEF", stars=i) for i in range(6)]
        result = filter_photos(photos, FilterMode.GTE, 3)
        assert all(p.stars >= 3 for p in result)
        assert len(result) == 3  # stars 3, 4, 5

    def test_eq_filter(self):
        photos = [make_photo(f"{i}.NEF", stars=i % 5 + 1) for i in range(10)]
        result = filter_photos(photos, FilterMode.EQ, 3)
        assert all(p.stars == 3 for p in result)

    def test_lte_filter(self):
        photos = [make_photo(f"{i}.NEF", stars=i) for i in range(6)]
        result = filter_photos(photos, FilterMode.LTE, 3)
        assert all(p.stars <= 3 for p in result)
        assert len(result) == 4  # stars 0, 1, 2, 3

    def test_gte_zero_returns_all(self):
        photos = [make_photo(f"{i}.NEF", stars=i) for i in range(6)]
        result = filter_photos(photos, FilterMode.GTE, 0)
        assert len(result) == 6

    def test_eq_zero_returns_unrated(self):
        photos = [make_photo("a.NEF", stars=0), make_photo("b.NEF", stars=3)]
        result = filter_photos(photos, FilterMode.EQ, 0)
        assert len(result) == 1
        assert result[0].filename == "a.NEF"

    def test_empty_photos(self):
        assert filter_photos([], FilterMode.GTE, 3) == []


# ─── Exporter 複製 ────────────────────────────────────────────


class TestExportPhotos:
    def test_basic_copy(self, tmp_path: Path):
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        dest_dir = tmp_path / "dest"

        photos = [make_photo("a.NEF", stars=3, tmp_path=src_dir)]
        config = ExportConfig(target_folder=dest_dir)
        result = export_photos(photos, config)

        assert len(result.copied) == 1
        assert (dest_dir / "a.NEF").exists()

    def test_md5_integrity(self, tmp_path: Path):
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        dest_dir = tmp_path / "dest"

        photos = [make_photo("img.NEF", stars=5, tmp_path=src_dir)]
        config = ExportConfig(target_folder=dest_dir)
        export_photos(photos, config)

        assert verify_copy_integrity(src_dir / "img.NEF", dest_dir / "img.NEF")

    def test_skip_on_conflict(self, tmp_path: Path):
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        dest_dir = tmp_path / "dest"
        dest_dir.mkdir()

        # 預先存在目標檔案
        (dest_dir / "a.NEF").write_bytes(b"EXISTING")
        photos = [make_photo("a.NEF", stars=4, tmp_path=src_dir)]
        config = ExportConfig(target_folder=dest_dir, conflict_action=ConflictAction.SKIP)
        result = export_photos(photos, config)

        assert len(result.skipped) == 1
        assert (dest_dir / "a.NEF").read_bytes() == b"EXISTING"

    def test_rename_on_conflict(self, tmp_path: Path):
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        dest_dir = tmp_path / "dest"
        dest_dir.mkdir()

        (dest_dir / "a.NEF").write_bytes(b"EXISTING")
        photos = [make_photo("a.NEF", stars=4, tmp_path=src_dir)]
        config = ExportConfig(target_folder=dest_dir, conflict_action=ConflictAction.RENAME)
        result = export_photos(photos, config)

        assert len(result.copied) == 1
        assert (dest_dir / "a_1.NEF").exists()

    def test_overwrite_on_conflict(self, tmp_path: Path):
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        dest_dir = tmp_path / "dest"
        dest_dir.mkdir()

        (dest_dir / "a.NEF").write_bytes(b"OLD")
        photos = [make_photo("a.NEF", stars=4, tmp_path=src_dir)]
        config = ExportConfig(target_folder=dest_dir, conflict_action=ConflictAction.OVERWRITE)
        export_photos(photos, config)

        assert (dest_dir / "a.NEF").read_bytes() == b"FAKEFILE_a.NEF"

    def test_progress_callback(self, tmp_path: Path):
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        dest_dir = tmp_path / "dest"
        calls = []

        photos = [make_photo(f"{i}.NEF", stars=3, tmp_path=src_dir) for i in range(3)]
        config = ExportConfig(target_folder=dest_dir)
        export_photos(photos, config, on_progress=lambda c, t, f: calls.append(c))

        assert calls == [1, 2, 3]

    def test_multiple_renames(self, tmp_path: Path):
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        dest_dir = tmp_path / "dest"
        dest_dir.mkdir()

        # 建立 a.NEF, a_1.NEF, a_2.NEF
        for name in ["a.NEF", "a_1.NEF", "a_2.NEF"]:
            (dest_dir / name).write_bytes(b"X")

        photos = [make_photo("a.NEF", stars=5, tmp_path=src_dir)]
        config = ExportConfig(target_folder=dest_dir, conflict_action=ConflictAction.RENAME)
        result = export_photos(photos, config)

        assert (dest_dir / "a_3.NEF").exists()


# ─── 跨 Session 資料恢復 ─────────────────────────────────────


class TestCrossSessionRestore:
    def test_ratings_survive_db_delete(self, tmp_path: Path):
        """ratings.json 在 DB 刪除後仍可恢復評分。"""
        # Session 1：寫入評分
        db1 = Database(tmp_path)
        db1.open()
        db1.set_rating("a.NEF", 4)
        db1.set_rating("b.NEF", 2)
        db1.close()

        # 刪除 DB（模擬 TTL 清理）
        delete_cache(tmp_path)
        assert not db1.db_path.exists()

        # Session 2：從 ratings.json 恢復
        db2 = Database(tmp_path)
        db2.open()
        db2.load_ratings_from_json()
        assert db2.get_rating("a.NEF") == 4
        assert db2.get_rating("b.NEF") == 2
        db2.close()

    def test_ai_scores_restored_from_db(self, tmp_path: Path):
        """AI 分析結果在重新開啟時可從 DB 讀取。"""
        db = Database(tmp_path)
        db.open()
        db.save_ai_scores("a.NEF", sharpness=85.0, exposure=72.0, motion_blur=90.0)
        db.close()

        db2 = Database(tmp_path)
        db2.open()
        scores = db2.get_ai_scores("a.NEF")
        assert scores is not None
        assert scores["sharpness"] == 85.0
        db2.close()


# ─── 快取 TTL 對話邏輯 ────────────────────────────────────────


class TestCacheManagement:
    def test_get_cache_info_no_cache(self, tmp_path: Path):
        assert get_cache_info(tmp_path) is None

    def test_get_cache_info_with_cache(self, tmp_path: Path):
        db = Database(tmp_path)
        db.open()
        db.close()
        info = get_cache_info(tmp_path)
        assert info is not None
        assert "size_bytes" in info
        assert info["size_bytes"] > 0

    def test_delete_cache_removes_db(self, tmp_path: Path):
        db = Database(tmp_path)
        db.open()
        db.set_rating("a.NEF", 3)  # ratings.json 應保留
        db.close()

        assert db.db_path.exists()
        delete_cache(tmp_path)
        assert not db.db_path.exists()
        assert db.ratings_path.exists()  # ratings.json 保留

    def test_delete_nonexistent_cache(self, tmp_path: Path):
        assert delete_cache(tmp_path) is False


# ─── 連拍群組完整流程 ─────────────────────────────────────────


class TestBurstGroupIntegration:
    def _make_photos(self) -> list[PhotoInfo]:
        dts = [
            datetime(2024, 6, 15, 10, 0, 0),
            datetime(2024, 6, 15, 10, 0, 1),
            datetime(2024, 6, 15, 10, 0, 2),
            datetime(2024, 6, 15, 10, 0, 8),  # 新群組
            datetime(2024, 6, 15, 10, 0, 9),
            datetime(2024, 6, 15, 10, 0, 10),
        ]
        return [
            PhotoInfo(path=Path(f"/f/{i}.NEF"), filename=f"{i}.NEF",
                      mtime=0, file_size=1000, datetime_taken=dt)
            for i, dt in enumerate(dts)
        ]

    def test_full_pipeline(self):
        photos = self._make_photos()
        groups = group_burst_photos(photos, gap_sec=3.0)
        assert len(groups) == 2

        ai_scores = {
            "0.NEF": {"sharpness": 60.0, "exposure": 70.0, "motion_blur": 65.0},
            "1.NEF": {"sharpness": 90.0, "exposure": 85.0, "motion_blur": 88.0},
            "2.NEF": {"sharpness": 50.0, "exposure": 60.0, "motion_blur": 55.0},
            "3.NEF": {"sharpness": 75.0, "exposure": 80.0, "motion_blur": 70.0},
            "4.NEF": {"sharpness": 88.0, "exposure": 82.0, "motion_blur": 85.0},
            "5.NEF": {"sharpness": 40.0, "exposure": 50.0, "motion_blur": 45.0},
        }

        groups = select_best_in_groups(groups, ai_scores)
        photos_by_name = {p.filename: p for p in photos}
        apply_group_metadata(groups, photos_by_name)

        # 群組 A 最佳應為 1.NEF（最高分）
        group_a = next(g for g in groups if g.group_id == "A")
        assert group_a.best_filename == "1.NEF"

        # 群組 B 最佳應為 4.NEF
        group_b = next(g for g in groups if g.group_id == "B")
        assert group_b.best_filename == "4.NEF"

        # group_id 應寫回 PhotoInfo
        assert photos[0].burst_group_id == "A"
        assert photos[3].burst_group_id == "B"
        assert photos[1].ai_best is True
        assert photos[4].ai_best is True

    def test_db_persistence(self, tmp_path: Path):
        """連拍群組資訊寫入 DB 後可正確讀取。"""
        db = Database(tmp_path)
        db.open()
        db.save_burst_group("a.NEF", "A", group_size=3, group_rank=2,
                            ai_best=True, composite_score=82.5)
        info = db.get_burst_group("a.NEF")
        assert info["group_id"] == "A"
        assert info["group_size"] == 3
        assert info["ai_best"] == 1
        assert abs(info["composite_score"] - 82.5) < 0.001
        db.close()
