# -*- coding: utf-8 -*-
"""
Ribbon layout configuration.

The entire ribbon layout (tab order, which toolbars/menus feed which
groups, per-group label style, hidden actions and global sizing) is
plain data.  It is persisted as JSON in the active QGIS profile so it
can be edited from the Customize dialog or by hand.
"""

import copy
import json
from pathlib import Path

CONFIG_VERSION = 1
CONFIG_FILENAME = "layout.json"

# Core toolbars that must never be treated as third-party plugin
# toolbars by the automatic "plugin_toolbars" group, even when they are
# not referenced anywhere in the layout.
INTERNAL_TOOLBARS = {
    "RibbonToolbarMain",
    "mBrowserToolbar",
    "mToolbar",
}


def _toolbar(source, labels=False, title=None):
    return {
        "kind": "toolbar",
        "source": source,
        "match": None,
        "title": title,
        "labels": labels,
        "visible": True,
        "hidden": [],
    }


def _menu(source, labels=True):
    return {
        "kind": "menu",
        "source": source,
        "match": None,
        "title": None,
        "labels": labels,
        "visible": True,
        "hidden": [],
    }


def _submenu(source, match, labels=True, title=None):
    return {
        "kind": "submenu",
        "source": source,
        "match": match,
        "title": title,
        "labels": labels,
        "visible": True,
        "hidden": [],
    }


def _plugin_toolbars():
    return {
        "kind": "plugin_toolbars",
        "source": None,
        "match": None,
        "title": None,
        "labels": False,
        "visible": True,
        "hidden": [],
    }


def _tab(tab_id, title, menu=None, groups=()):
    return {
        "id": tab_id,
        "title": title,
        "menu": menu,
        "visible": True,
        "groups": list(groups),
    }


def default_layout():
    """Return a fresh copy of the built-in default layout."""
    return copy.deepcopy(
        {
            "version": CONFIG_VERSION,
            "rows": 2,
            "icon_size": 16,
            "show_group_titles": False,
            "tabs": [
                _tab(
                    "project",
                    "Project",
                    "mProjectMenu",
                    [_toolbar("mFileToolBar", labels=True), _menu("mProjectMenu")],
                ),
                _tab(
                    "edit",
                    "Edit",
                    "mEditMenu",
                    [
                        _toolbar("mDigitizeToolBar"),
                        _toolbar("mAdvancedDigitizeToolBar"),
                        _toolbar("mShapeDigitizeToolBar"),
                        _menu("mEditMenu"),
                    ],
                ),
                _tab(
                    "selection",
                    "Selection",
                    None,
                    [
                        _toolbar("mSelectionToolBar"),
                        _submenu("mEditMenu", "Select", title="Selection"),
                    ],
                ),
                _tab(
                    "view",
                    "View",
                    "mViewMenu",
                    [
                        _toolbar("mMapNavToolBar"),
                        _toolbar("mAttributesToolBar"),
                        _menu("mViewMenu"),
                    ],
                ),
                _tab(
                    "layer",
                    "Layer",
                    "mLayerMenu",
                    [
                        _toolbar("mDataSourceManagerToolBar", labels=True),
                        _toolbar("mLayerToolBar"),
                        _menu("mLayerMenu"),
                    ],
                ),
                _tab("settings", "Settings", "mSettingsMenu", [_menu("mSettingsMenu")]),
                _tab(
                    "raster",
                    "Raster",
                    "mRasterMenu",
                    [_toolbar("mRasterToolBar"), _menu("mRasterMenu")],
                ),
                _tab(
                    "vector",
                    "Vector",
                    "mVectorMenu",
                    [_toolbar("mVectorToolBar"), _menu("mVectorMenu")],
                ),
                _tab(
                    "processing",
                    "Processing",
                    "processing",
                    [_toolbar("processingToolbar", labels=True), _menu("processing")],
                ),
                _tab(
                    "mesh",
                    "Mesh",
                    "mMeshMenu",
                    [_toolbar("mMeshToolBar"), _menu("mMeshMenu")],
                ),
                _tab(
                    "database",
                    "Database",
                    "mDatabaseMenu",
                    [_toolbar("mDatabaseToolBar"), _menu("mDatabaseMenu")],
                ),
                _tab(
                    "web",
                    "Web",
                    "mWebMenu",
                    [_toolbar("mWebToolBar"), _menu("mWebMenu")],
                ),
                _tab(
                    "plugins",
                    "Plugins",
                    "mPluginMenu",
                    [
                        _toolbar("mPluginToolBar"),
                        _plugin_toolbars(),
                        _menu("mPluginMenu"),
                    ],
                ),
                _tab(
                    "help",
                    "Help",
                    "mHelpMenu",
                    [_toolbar("mHelpToolBar"), _menu("mHelpMenu")],
                ),
                _tab(
                    "tools",
                    "Tools",
                    None,
                    [
                        _toolbar("mSnappingToolBar", title="Snapping"),
                        _toolbar("mLabelToolBar", title="Labels"),
                        _toolbar("mAnnotationsToolBar", title="Annotations"),
                        _toolbar("mGpsToolBar", title="GPS"),
                        _toolbar("mBookmarkToolbar", title="Bookmarks"),
                    ],
                ),
            ],
        }
    )


def config_path():
    """Path of the layout file inside the active QGIS profile."""
    from qgis.core import QgsApplication

    return (
        Path(QgsApplication.qgisSettingsDirPath()) / "ribbon_toolbar" / CONFIG_FILENAME
    )


def _clamp(value, low, high, fallback):
    try:
        return min(max(int(value), low), high)
    except (TypeError, ValueError):
        return fallback


def _normalize_group(group):
    if not isinstance(group, dict):
        return None
    kind = group.get("kind")
    if kind not in ("toolbar", "menu", "submenu", "plugin_toolbars"):
        return None
    if kind in ("toolbar", "menu", "submenu") and not group.get("source"):
        return None
    if kind == "submenu" and not group.get("match"):
        return None
    hidden = group.get("hidden")
    return {
        "kind": kind,
        "source": group.get("source"),
        "match": group.get("match"),
        "title": group.get("title"),
        "labels": bool(group.get("labels", False)),
        "visible": bool(group.get("visible", True)),
        "hidden": [str(h) for h in hidden] if isinstance(hidden, list) else [],
    }


def _normalize_tab(tab):
    if not isinstance(tab, dict) or not tab.get("id"):
        return None
    groups = tab.get("groups")
    groups = groups if isinstance(groups, list) else []
    normalized_groups = [g for g in map(_normalize_group, groups) if g is not None]
    return {
        "id": str(tab["id"]),
        "title": str(tab.get("title") or tab["id"]),
        "menu": tab.get("menu"),
        "visible": bool(tab.get("visible", True)),
        "groups": normalized_groups,
    }


def normalize_layout(layout):
    """Validate a layout dict, falling back to defaults where invalid."""
    default = default_layout()
    if not isinstance(layout, dict):
        return default
    tabs = layout.get("tabs")
    tabs = tabs if isinstance(tabs, list) else []
    normalized_tabs = [t for t in map(_normalize_tab, tabs) if t is not None]
    if not normalized_tabs:
        return default
    return {
        "version": CONFIG_VERSION,
        "rows": _clamp(layout.get("rows"), 1, 3, default["rows"]),
        "icon_size": _clamp(layout.get("icon_size"), 12, 48, default["icon_size"]),
        "show_group_titles": bool(layout.get("show_group_titles", False)),
        "tabs": normalized_tabs,
    }


def load_layout():
    """Load the saved layout, or the default when missing/invalid."""
    path = config_path()
    try:
        with open(path, encoding="utf-8") as f:
            return normalize_layout(json.load(f))
    except (OSError, ValueError):
        return default_layout()


def save_layout(layout):
    """Persist a layout to the profile as pretty-printed JSON."""
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(normalize_layout(layout), f, indent=2)


def reset_layout():
    """Delete the saved layout so the default applies again."""
    try:
        config_path().unlink()
    except OSError:
        pass
