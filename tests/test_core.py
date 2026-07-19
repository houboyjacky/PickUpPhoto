"""
tests/test_core.py — core 模組單元測試

測試：scanner 排序、EXIF 缺失 fallback、database schema、cache TTL
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest

from pickupphoto.core.database import Database, _utcnow
from pickupphoto.core.scanner import (
    PhotoInfo,
    _parse_datetime,
    _decode_bytes,
    get_burst_timestamp,
)


# ─── Scanner ─────────────────────────────────────────────────


class TestParseDateTime:
    def test_exif_format(self):
        result = _parse_datetime("2024:06:15 14:32:10")
        assert result == datetime(2024, 6, 15, 14, 32, 10)

    def test_iso_format(self):
        result = _parse_datetime("2024-06-15 14:32:10")
        assert result == datetime(2024, 6, 15, 14, 32, 10)

    def test_invalid_returns_none(self):
        assert _parse_datetime("invalid") is None
        assert _parse_datetime("") is None

    def test_whitespace_stripped(self):
        result = _parse_datetime("  2024:06:15 14:32:10  ")
        assert result == datetime(2024, 6, 15, 14, 32, 10)


class TestDecodeBytes:
    def test_bytes_to_str(self):
        assert _decode_bytes(b"Nikon\x00") == "Nikon"

    def test_str_passthrough(self):
        assert _decode_bytes("Canon") == "Canon"

    def test_empty_bytes(self):
        assert _decode_bytes(b"") == ""


class TestPhotoInfoSortKey:
    def _make_photo(self, dt: datetime | None, name: str) -> PhotoInfo:
        return PhotoInfo(
            path=Path(f"/fake/{name}"),
            filename=name,
            mtime=0,
            file_size=1000,
            datetime_taken=dt,
        )

    def test_sort_by_datetime(self):
        photos = [
            self._make_photo(datetime(2024, 6, 15, 14, 32, 10), "b.NEF"),
            self._make_photo(datetime(2024, 6, 15, 14, 32, 5), "a.NEF"),
        ]
        photos.sort(key=lambda p: p.sort_key)
        assert photos[0].filename == "a.NEF"

    def test_no_datetime_sorts_first(self):
        photos = [
            self._make_photo(datetime(2024, 6, 15, 14, 0, 0), "b.NEF"),
            self._make_photo(None, "a.NEF"),
        ]
        photos.sort(key=lambda p: p.sort_key)
        assert photos[0].filename == "a.NEF"  # datetime.min sorts first

    def test_same_datetime_sorts_by_filename(self):
        dt = datetime(2024, 6, 15, 14, 32, 10)
        photos = [
            self._make_photo(dt, "z.NEF"),
            self._make_photo(dt, "a.NEF"),
        ]
        photos.sort(key=lambda p: p.sort_key)
        assert photos[0].filename == "a.NEF"


class TestGetBurstTimestamp:
    def test_with_subsec(self):
        photo = PhotoInfo(
            path=Path("/fake/a.NEF"),
            filename="a.NEF",
            mtime=0,
            file_size=1000,
            datetime_taken=datetime(2024, 6, 15, 14, 32, 10),
            datetime_subsec="25",
        )
        ts = get_burst_timestamp(photo)
        assert abs(ts - datetime(2024, 6, 15, 14, 32, 10).timestamp() - 0.25) < 0.001

    def test_no_datetime_returns_zero(self):
        photo = PhotoInfo(
            path=Path("/fake/a.NEF"),
            filename="a.NEF",
            mtime=0,
            file_size=1000,
        )
        assert get_burst_timestamp(photo) == 0.0


class TestExifSummary:
    def test_full_exif(self):
        photo = PhotoInfo(
            path=Path("/fake/a.NEF"),
            filename="a.NEF",
            mtime=0,
            file_size=1000,
            datetime_taken=datetime(2024, 6, 15, 14, 32, 10),
            camera_make="Nikon",
            camera_model="Z9",
            lens_model="NIKKOR Z 85mm f/1.8 S",
            focal_length_mm=85.0,
            f_number=1.8,
            shutter_speed="1/1000",
            iso=800,
        )
        summary = photo.exif_summary
        assert "Nikon Z9" in summary
        assert "f/1.8" in summary
        assert "ISO 800" in summary

    def test_empty_exif(self):
        photo = PhotoInfo(
            path=Path("/fake/a.NEF"),
            filename="a.NEF",
            mtime=0,
            file_size=1000,
        )
        assert photo.exif_summary == "—"


# ─── Database ────────────────────────────────────────────────


@pytest.fixture
def tmp_db(tmp_path: Path) -> Database:
    """建立臨時 Database 實例。"""
    db = Database(tmp_path)
    db.open()
    yield db
    db.close()


class TestDatabaseSchema:
    def test_open_creates_tables(self, tmp_db: Database):
        tables = [
            row[0] for row in tmp_db.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        ]
        assert "thumbnails" in tables
        assert "ratings" in tables
        assert "ai_scores" in tables
        assert "burst_groups" in tables
        assert "cache_meta" in tables

    def test_cache_meta_row_exists(self, tmp_db: Database):
        row = tmp_db.conn.execute(
            "SELECT id FROM cache_meta WHERE id = 1"
        ).fetchone()
        assert row is not None


class TestThumbnails:
    def test_save_and_load(self, tmp_db: Database):
        blob = b"\xff\xd8\xff" + b"\x00" * 100  # 假 JPEG header
        tmp_db.save_thumbnail("IMG001.NEF", blob, mtime=12345, width=256, height=170)
        record = tmp_db.load_thumbnail("IMG001.NEF")
        assert record is not None
        assert record["thumb_blob"] == blob
        assert record["file_mtime"] == 12345

    def test_missing_returns_none(self, tmp_db: Database):
        assert tmp_db.load_thumbnail("nonexistent.NEF") is None

    def test_mtime_retrieval(self, tmp_db: Database):
        tmp_db.save_thumbnail("a.NEF", b"\x00", mtime=999, width=1, height=1)
        assert tmp_db.get_cached_mtime("a.NEF") == 999

    def test_thumbnail_count(self, tmp_db: Database):
        assert tmp_db.thumbnail_count() == 0
        tmp_db.save_thumbnail("a.NEF", b"\x00", mtime=1, width=1, height=1)
        tmp_db.save_thumbnail("b.NEF", b"\x00", mtime=2, width=1, height=1)
        assert tmp_db.thumbnail_count() == 2


class TestRatings:
    def test_set_and_get(self, tmp_db: Database):
        tmp_db.set_rating("a.NEF", 3)
        assert tmp_db.get_rating("a.NEF") == 3

    def test_unrated_returns_zero(self, tmp_db: Database):
        assert tmp_db.get_rating("nonexistent.NEF") == 0

    def test_update_rating(self, tmp_db: Database):
        tmp_db.set_rating("a.NEF", 2)
        tmp_db.set_rating("a.NEF", 5)
        assert tmp_db.get_rating("a.NEF") == 5

    def test_invalid_stars_raises(self, tmp_db: Database):
        with pytest.raises(AssertionError):
            tmp_db.set_rating("a.NEF", 6)

    def test_ratings_json_created(self, tmp_db: Database):
        tmp_db.set_rating("a.NEF", 4)
        assert tmp_db.ratings_path.exists()
        data = json.loads(tmp_db.ratings_path.read_text("utf-8"))
        assert data["a.NEF"] == 4

    def test_get_all_ratings(self, tmp_db: Database):
        tmp_db.set_rating("a.NEF", 1)
        tmp_db.set_rating("b.NEF", 5)
        all_r = tmp_db.get_all_ratings()
        assert all_r == {"a.NEF": 1, "b.NEF": 5}

    def test_load_ratings_from_json(self, tmp_path: Path):
        """ratings.json 優先恢復評分（跨 session）。"""
        ratings_path = tmp_path / ".pickupphoto" / "ratings.json"
        ratings_path.parent.mkdir(parents=True, exist_ok=True)
        ratings_path.write_text(json.dumps({"x.NEF": 3}), "utf-8")
        db = Database(tmp_path)
        db.open()
        db.load_ratings_from_json()
        assert db.get_rating("x.NEF") == 3
        db.close()


class TestAiScores:
    def test_save_and_get(self, tmp_db: Database):
        tmp_db.save_ai_scores("a.NEF", sharpness=85.0, exposure=72.0)
        scores = tmp_db.get_ai_scores("a.NEF")
        assert scores is not None
        assert scores["sharpness"] == 85.0
        assert scores["exposure"] == 72.0

    def test_unanalyzed_returns_none(self, tmp_db: Database):
        assert tmp_db.get_ai_scores("missing.NEF") is None


class TestBurstGroups:
    def test_save_and_get(self, tmp_db: Database):
        tmp_db.save_burst_group("a.NEF", "G1", group_size=3, group_rank=1,
                                ai_best=True, composite_score=88.5)
        info = tmp_db.get_burst_group("a.NEF")
        assert info is not None
        assert info["group_id"] == "G1"
        assert info["ai_best"] == 1

    def test_clear(self, tmp_db: Database):
        tmp_db.save_burst_group("a.NEF", "G1", group_size=1, group_rank=1,
                                ai_best=False, composite_score=None)
        tmp_db.clear_burst_groups()
        assert tmp_db.get_burst_group("a.NEF") is None


class TestCacheTTL:
    def test_fresh_cache_not_expired(self, tmp_db: Database):
        assert not tmp_db.is_expired(ttl_days=7)

    def test_expired_detection(self, tmp_db: Database):
        # 手動把 last_accessed 設成 8 天前
        past = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
        tmp_db.conn.execute(
            "UPDATE cache_meta SET last_accessed = ? WHERE id = 1", (past,)
        )
        tmp_db.conn.commit()
        assert tmp_db.is_expired(ttl_days=7)
