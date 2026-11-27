"""Local photo library shared by the browser requests."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import BoundedSemaphore, Lock

from pickupphoto.analysis.burst_grouper import group_burst_photos, select_best_in_groups
from pickupphoto.analysis.exposure import compute_exposure
from pickupphoto.analysis.motion_blur import compute_motion_blur
from pickupphoto.analysis.sharpness import compute_sharpness
from pickupphoto.core.database import Database
from pickupphoto.core.raw_loader import (
    load_embedded_preview, load_full_decode, load_thumbnail, numpy_to_jpeg_bytes,
)
from pickupphoto.core.scanner import PhotoInfo, scan_folder
from pickupphoto.output.exporter import (
    ConflictAction, ExportConfig, FilterMode, export_photos, filter_photos,
)


class Library:
    def __init__(self, folder: Path):
        self.folder = folder
        self.photos = scan_folder(folder)
        self._db = Database(folder)
        self._lock = Lock()
        self._decode_slots = BoundedSemaphore(3)
        try:
            self._db.open()
            self._db.load_ratings_from_json()
            ratings = self._db.get_all_ratings()
            self._scores = self._db.get_all_ai_scores()
            self._groups = self._db.get_all_burst_groups()
        except Exception:
            self._db.close()
            raise
        for photo in self.photos:
            photo.stars = ratings.get(photo.filename, 0)

    def close(self):
        with self._lock:
            self._db.close()

    def listing(self):
        with self._lock:
            return [
                {
                    "id": index,
                    "name": photo.filename,
                    "stars": photo.stars,
                    "size": photo.file_size,
                    "exif": photo.exif_summary,
                    "scores": {
                        key: scores.get(key)
                        for key in ("sharpness", "exposure", "motion_blur", "eye_focus")
                    } if (scores := self._scores.get(photo.filename)) else None,
                    "group": self._groups.get(photo.filename),
                }
                for index, photo in enumerate(self.photos)
            ]

    def rate(self, index: int, stars: int):
        photo = self.photos[index]
        with self._lock:
            self._db.set_rating(photo.filename, stars)
            photo.stars = stars

    def image(self, index: int, kind: str) -> bytes:
        photo = self.photos[index]
        if kind == "thumbnail":
            with self._lock:
                cached = self._db.load_thumbnail(photo.filename)
                if cached and cached["file_mtime"] == photo.mtime:
                    return cached["thumb_blob"]

        loaders = {
            "thumbnail": load_thumbnail,
            "preview": load_embedded_preview,
            "full": load_full_decode,
        }
        with self._decode_slots:
            image = loaders[kind](photo.path)
            jpeg = numpy_to_jpeg_bytes(image.image)

        if kind == "thumbnail":
            with self._lock:
                self._db.save_thumbnail(
                    photo.filename, jpeg, photo.mtime, image.width, image.height, image.is_fallback,
                )
        return jpeg

    def analyze(self, progress, stop):
        from pickupphoto.analysis.face_focus import compute_eye_focus, is_available

        use_eyes = is_available()
        results = {}
        failures = []

        def analyze_one(photo):
            if stop.is_set():
                return None, None
            try:
                img = load_embedded_preview(photo.path, max_size=512).image
                eye_focus, has_face = compute_eye_focus(img) if use_eyes else (None, None)
                return {
                    "sharpness": compute_sharpness(img),
                    "exposure": compute_exposure(img),
                    "motion_blur": compute_motion_blur(img),
                    "eye_focus": eye_focus,
                    "has_face": has_face,
                }, None
            except Exception as error:
                return None, str(error)[:240]

        with ThreadPoolExecutor(max_workers=3) as pool:
            for index, (photo, result) in enumerate(
                zip(self.photos, pool.map(analyze_one, self.photos)), start=1
            ):
                scores, error = result
                if stop.is_set():
                    return {"cancelled": True}
                if scores is not None:
                    results[photo.filename] = scores
                else:
                    failures.append([photo.filename, error])
                progress(index, len(self.photos))

        groups = select_best_in_groups(group_burst_photos(self.photos), results, use_eyes)
        with self._lock:
            self._db.clear_burst_groups()
            for filename, scores in results.items():
                self._db.save_ai_scores(filename, **scores)
            for group in groups:
                for rank, photo in enumerate(group.photos, start=1):
                    self._db.save_burst_group(
                        photo.filename, group.group_id, len(group.photos), rank,
                        photo.ai_best, group.scores.get(photo.filename),
                    )
            self._scores = self._db.get_all_ai_scores()
            self._groups = self._db.get_all_burst_groups()
        return {"analyzed": len(results), "failed": len(failures), "errors": failures[:10]}

    def export(self, target: Path, mode: FilterMode, stars: int, conflict: ConflictAction, progress):
        if target == self.folder:
            raise ValueError("請選擇和來源不同的匯出資料夾。")
        with self._lock:
            photos = filter_photos(self.photos, mode, stars)
        result = export_photos(
            photos, ExportConfig(target, mode, stars, conflict),
            lambda completed, total, _filename: progress(completed, total),
        )
        return {
            "copied": len(result.copied), "skipped": len(result.skipped),
            "failed": len(result.errors), "errors": result.errors[:10],
        }
