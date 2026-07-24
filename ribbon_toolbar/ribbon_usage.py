# -*- coding: utf-8 -*-
"""
Tool usage tracking for the Favorites tab.

Counts how often each action is triggered (anywhere in QGIS) and when it
was last used, persisted as JSON in the active QGIS profile. The ribbon
reads this to populate "Frequently Used" and "Recently Used" groups.
"""

import json
import time
from pathlib import Path

USAGE_FILENAME = "usage.json"
MAX_TRACKED = 400  # cap the store so it cannot grow without bound


def usage_path():
    from qgis.core import QgsApplication

    return (
        Path(QgsApplication.qgisSettingsDirPath())
        / "ribbon_toolbar"
        / USAGE_FILENAME
    )


class UsageTracker:
    """In-memory usage counters, flushed to disk on each record."""

    def __init__(self):
        self._data = self._load()

    def _load(self):
        try:
            with open(usage_path(), encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return {}
        if not isinstance(data, dict):
            return {}
        # Keep only well-formed entries.
        clean = {}
        for key, entry in data.items():
            if isinstance(entry, dict) and "count" in entry:
                clean[str(key)] = {
                    "count": int(entry.get("count", 0)),
                    "last": float(entry.get("last", 0.0)),
                }
        return clean

    def _save(self):
        path = usage_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self._data, f)
        except OSError:
            pass

    def record(self, key):
        if not key:
            return
        entry = self._data.setdefault(key, {"count": 0, "last": 0.0})
        entry["count"] += 1
        entry["last"] = time.time()
        self._prune()
        self._save()

    def _prune(self):
        if len(self._data) <= MAX_TRACKED:
            return
        # Drop the least recently used entries beyond the cap.
        ordered = sorted(
            self._data.items(), key=lambda kv: kv[1].get("last", 0.0), reverse=True
        )
        self._data = dict(ordered[:MAX_TRACKED])

    def top(self, count, by="count"):
        """Return up to ``count`` keys ordered by 'count' or 'last'."""
        field = "count" if by == "count" else "last"
        ordered = sorted(
            self._data.items(),
            key=lambda kv: kv[1].get(field, 0),
            reverse=True,
        )
        return [key for key, entry in ordered[:count] if entry.get(field, 0) > 0]
