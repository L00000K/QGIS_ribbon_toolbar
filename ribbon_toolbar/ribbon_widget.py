# -*- coding: utf-8 -*-
"""
Ribbon widget — a compact QTabWidget styled like an Office ribbon.

The layout is fully data-driven (see ribbon_config): each tab lists
groups, and each group pulls its actions live from a QGIS toolbar,
menu or submenu.  Buttons size to their content so labels are never
truncated, actions with submenus become dropdown buttons
automatically, and colors come from the application palette so the
ribbon follows the active QGIS theme.
"""

import re

from qgis.PyQt import sip
from qgis.PyQt.QtCore import QSize, Qt, pyqtSignal
from qgis.PyQt.QtGui import QPalette
from qgis.PyQt.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMenu,
    QScrollArea,
    QSizePolicy,
    QTabWidget,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

from .ribbon_config import INTERNAL_TOOLBARS


def clean_text(text):
    """Strip accelerator markers and rich-text markup from a label."""
    return re.sub(r"<[^>]+>", "", (text or "").replace("&", "")).strip()


def action_key(action):
    """Identifier used to match actions in the per-group hidden list."""
    return action.objectName() or clean_text(action.text())


def collect_toolbars(main_window):
    """All named toolbars on the main window, by objectName."""
    return {
        tb.objectName(): tb
        for tb in main_window.findChildren(QToolBar)
        if tb.objectName()
    }


def collect_menus(main_window):
    """All top-level menubar menus, by objectName."""
    menubar = main_window.menuBar()
    return {
        menu.objectName(): menu
        for menu in menubar.findChildren(QMenu)
        if menu.parent() is menubar
    }


def referenced_toolbars(layout_cfg):
    """Toolbar names claimed by the layout or known to be QGIS-internal."""
    names = set(INTERNAL_TOOLBARS)
    for tab in layout_cfg.get("tabs", []):
        for group in tab.get("groups", []):
            if group.get("kind") == "toolbar" and group.get("source"):
                names.add(group["source"])
    return names


def _resolve_toolbar_group(group_cfg, toolbars):
    tb = toolbars.get(group_cfg.get("source"))
    if tb is None or not tb.actions():
        return []
    title = group_cfg.get("title") or clean_text(tb.windowTitle()) or tb.objectName()
    return [{"title": title, "name": tb.objectName(), "actions": tb.actions()}]


def _resolve_menu_group(group_cfg, menus):
    menu = menus.get(group_cfg.get("source"))
    if menu is None:
        return []
    title = group_cfg.get("title") or clean_text(menu.title())
    return [{"title": title, "name": menu.objectName(), "actions": menu.actions()}]


def _resolve_submenu_group(group_cfg, menus):
    menu = menus.get(group_cfg.get("source"))
    match = group_cfg.get("match") or ""
    if menu is None or not match:
        return []
    for action in menu.actions():
        submenu = action.menu()
        if submenu is None:
            continue
        if action.objectName() == match or clean_text(action.text()) == match:
            title = group_cfg.get("title") or clean_text(action.text())
            return [{"title": title, "name": match, "actions": submenu.actions()}]
    return []


def _resolve_plugin_toolbar_groups(toolbars, layout_cfg):
    claimed = referenced_toolbars(layout_cfg)
    groups = []
    for name in sorted(toolbars):
        tb = toolbars[name]
        if name in claimed or not tb.actions():
            continue
        groups.append(
            {
                "title": clean_text(tb.windowTitle()) or name,
                "name": name,
                "actions": tb.actions(),
            }
        )
    return groups


def resolve_groups(group_cfg, toolbars, menus, layout_cfg):
    """Resolve one group config entry into concrete groups.

    Returns a list of {"title", "name", "actions"} dicts — one entry for
    toolbar/menu/submenu kinds, one per discovered toolbar for the
    automatic plugin_toolbars kind.
    """
    kind = group_cfg.get("kind")
    if kind == "toolbar":
        return _resolve_toolbar_group(group_cfg, toolbars)
    if kind == "menu":
        return _resolve_menu_group(group_cfg, menus)
    if kind == "submenu":
        return _resolve_submenu_group(group_cfg, menus)
    if kind == "plugin_toolbars":
        return _resolve_plugin_toolbar_groups(toolbars, layout_cfg)
    return []


class RibbonWidget(QTabWidget):
    """Compact, configurable ribbon interface for QGIS."""

    customizeRequested = pyqtSignal()
    refreshRequested = pyqtSignal()

    def __init__(self, iface, layout_cfg, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.main_window = iface.mainWindow()
        self.layout_cfg = layout_cfg
        self.rows = layout_cfg.get("rows", 2)
        self.icon_px = layout_cfg.get("icon_size", 16)
        self.btn_height = self.icon_px + 6
        self.show_titles = layout_cfg.get("show_group_titles", False)
        # Connections to long-lived QGIS objects, released in teardown()
        self._connections = []
        self.setStyleSheet(self._build_stylesheet())
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setUsesScrollButtons(True)
        self._install_corner_menu()

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def build_ribbon(self):
        """Populate the ribbon from the layout configuration."""
        toolbars = collect_toolbars(self.main_window)
        menus = collect_menus(self.main_window)
        for tab_cfg in self.layout_cfg.get("tabs", []):
            if not tab_cfg.get("visible", True):
                continue
            page = self._build_tab(tab_cfg, toolbars, menus)
            if page is not None:
                self.addTab(page, self._tab_title(tab_cfg, menus))
        self._apply_fixed_height()

    def teardown(self):
        """Disconnect from external QGIS objects before deletion."""
        for signal, slot in self._connections:
            try:
                signal.disconnect(slot)
            except (TypeError, RuntimeError):
                pass
        self._connections = []

    def _tab_title(self, tab_cfg, menus):
        menu = menus.get(tab_cfg.get("menu")) if tab_cfg.get("menu") else None
        if menu is not None and clean_text(menu.title()):
            return clean_text(menu.title())
        return tab_cfg.get("title") or tab_cfg.get("id", "")

    def _build_tab(self, tab_cfg, toolbars, menus):
        container = QWidget()
        hbox = QHBoxLayout(container)
        hbox.setContentsMargins(2, 1, 2, 1)
        hbox.setSpacing(2)

        seen_ids = set()
        added = False
        for group_cfg in tab_cfg.get("groups", []):
            if not group_cfg.get("visible", True):
                continue
            for resolved in resolve_groups(group_cfg, toolbars, menus, self.layout_cfg):
                actions = self._filter_actions(resolved["actions"], group_cfg, seen_ids)
                if not any(not a.isSeparator() for a in actions):
                    continue
                frame = self._create_group(
                    resolved["title"], actions, group_cfg.get("labels", False)
                )
                hbox.addWidget(frame)
                added = True

        if not added:
            return None
        hbox.addStretch()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(container)
        return scroll

    def _filter_actions(self, actions, group_cfg, seen_ids):
        """Drop hidden actions and duplicates already placed on this tab."""
        hidden = set(group_cfg.get("hidden", []))
        kept = []
        for action in actions:
            if action.isSeparator():
                kept.append(action)
                continue
            if action_key(action) in hidden or id(action) in seen_ids:
                continue
            seen_ids.add(id(action))
            kept.append(action)
        return kept

    def _create_group(self, title, actions, labels):
        """A framed ribbon group: a button grid plus an optional title."""
        frame = QFrame()
        frame.setObjectName("ribbonGroup")

        vbox = QVBoxLayout(frame)
        vbox.setContentsMargins(3, 1, 3, 1)
        vbox.setSpacing(0)

        grid = QGridLayout()
        grid.setSpacing(1)
        grid.setContentsMargins(0, 0, 0, 0)
        row, col = 0, 0
        for action in actions:
            if action.isSeparator():
                if row:
                    row, col = 0, col + 1
                continue
            if isinstance(action, QWidgetAction):
                btn = self._make_widget_button(action.defaultWidget(), labels, frame)
            else:
                btn = self._make_action_button(action, labels, frame)
            if btn is None:
                continue
            grid.addWidget(btn, row, col)
            row += 1
            if row >= self.rows:
                row, col = 0, col + 1

        vbox.addLayout(grid)
        vbox.addStretch()
        if self.show_titles:
            label = QLabel(title)
            label.setObjectName("ribbonGroupTitle")
            label.setAlignment(Qt.AlignCenter)
            vbox.addWidget(label)
        return frame

    # ------------------------------------------------------------------
    # Buttons
    # ------------------------------------------------------------------

    def _make_action_button(self, action, labels, parent):
        btn = QToolButton(parent)
        btn.setAutoRaise(True)
        btn.setFocusPolicy(Qt.NoFocus)
        menu = action.menu()
        if menu is not None:
            # Any action with a submenu becomes a dropdown button.
            btn.setMenu(menu)
            btn.setPopupMode(QToolButton.InstantPopup)
            self._sync_menu_button(btn, action)
            slot = self._menu_sync_slot(btn, action)
            action.changed.connect(slot)
            self._connections.append((action.changed, slot))
        else:
            btn.setDefaultAction(action)
        self._style_button(btn, action.icon(), labels)
        return btn

    def _make_widget_button(self, source, labels, parent):
        """Mirror a QToolButton hosted by a QWidgetAction.

        Prefer sharing the source's default action so state stays in
        sync; otherwise forward clicks to the hidden original.
        Non-QToolButton widgets (spinboxes etc.) are skipped.
        """
        if not isinstance(source, QToolButton):
            return None
        btn = QToolButton(parent)
        btn.setAutoRaise(True)
        btn.setFocusPolicy(Qt.NoFocus)
        default = source.defaultAction()
        if default is not None:
            btn.setDefaultAction(default)
            icon = default.icon()
        else:
            btn.setIcon(source.icon())
            btn.setText(clean_text(source.text()))
            btn.setToolTip(source.toolTip())
            btn.clicked.connect(self._widget_click_slot(source))
            icon = source.icon()
        if source.menu() is not None:
            btn.setMenu(source.menu())
            btn.setPopupMode(source.popupMode())
        self._style_button(btn, icon, labels)
        return btn

    def _menu_sync_slot(self, btn, action):
        return lambda b=btn, a=action: self._sync_menu_button(b, a)

    def _widget_click_slot(self, source):
        def forward(checked=False, s=source):
            if not sip.isdeleted(s):
                s.click()

        return forward

    def _sync_menu_button(self, btn, action):
        """Keep a dropdown button aligned with its source action."""
        if sip.isdeleted(btn) or sip.isdeleted(action):
            return
        btn.setText(clean_text(action.text()))
        btn.setIcon(action.icon())
        btn.setToolTip(clean_text(action.toolTip()) or clean_text(action.text()))
        btn.setEnabled(action.isEnabled())
        btn.setVisible(action.isVisible())

    def _style_button(self, btn, icon, labels):
        btn.setIconSize(QSize(self.icon_px, self.icon_px))
        has_icon = icon is not None and not icon.isNull()
        if not has_icon:
            btn.setToolButtonStyle(Qt.ToolButtonTextOnly)
        elif labels:
            btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        else:
            btn.setToolButtonStyle(Qt.ToolButtonIconOnly)
        btn.setFixedHeight(self.btn_height)

    # ------------------------------------------------------------------
    # Chrome
    # ------------------------------------------------------------------

    def _install_corner_menu(self):
        btn = QToolButton(self)
        btn.setAutoRaise(True)
        btn.setText("⚙")
        btn.setToolTip("Ribbon options")
        btn.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu(btn)
        menu.addAction("Customize Ribbon…", self.customizeRequested.emit)
        menu.addAction("Refresh Ribbon", self.refreshRequested.emit)
        btn.setMenu(menu)
        self.setCornerWidget(btn, Qt.TopRightCorner)

    def _apply_fixed_height(self):
        content = self.rows * self.btn_height + (self.rows - 1) + 6
        if self.show_titles:
            content += 14
        self.setFixedHeight(self.tabBar().sizeHint().height() + content + 4)

    def _build_stylesheet(self):
        """Derive the ribbon chrome from the application palette."""
        pal = self.palette()
        window = pal.color(QPalette.Window).name()
        base = pal.color(QPalette.Base).name()
        text = pal.color(QPalette.WindowText).name()
        mid = pal.color(QPalette.Mid).name()
        highlight = pal.color(QPalette.Highlight)
        hover = "rgba({}, {}, {}, 40)".format(
            highlight.red(), highlight.green(), highlight.blue()
        )
        return """
            QTabWidget::pane {{
                border: 1px solid {mid};
                background: {base};
                margin: 0px;
            }}
            QTabWidget::tab-bar {{ alignment: left; }}
            QTabBar::tab {{
                background: {window};
                color: {text};
                border: 1px solid {mid};
                border-bottom: none;
                padding: 2px 10px;
                margin-right: 1px;
                font-size: 11px;
            }}
            QTabBar::tab:selected {{
                background: {base};
                color: {selected};
                font-weight: 600;
            }}
            QTabBar::tab:hover:!selected {{ background: {hover}; }}
            QFrame#ribbonGroup {{
                border: none;
                border-right: 1px solid {mid};
                background: transparent;
            }}
            QLabel#ribbonGroupTitle {{ color: {mid}; font-size: 9px; }}
            QToolButton {{ padding: 1px 3px; }}
        """.format(
            mid=mid,
            base=base,
            window=window,
            text=text,
            selected=highlight.name(),
            hover=hover,
        )
