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
from qgis.PyQt.QtCore import QSize, Qt, QTimer, pyqtSignal
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


def _strip_toolbar_suffix(title):
    """'Digitizing Toolbar' -> 'Digitizing' for compact group captions."""
    if title.lower().endswith(" toolbar"):
        return title[: -len(" toolbar")].strip()
    return title


def _resolve_toolbar_group(group_cfg, toolbars):
    tb = toolbars.get(group_cfg.get("source"))
    if tb is None or not tb.actions():
        return []
    title = group_cfg.get("title") or _strip_toolbar_suffix(
        clean_text(tb.windowTitle())
    ) or tb.objectName()
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


class OverflowPopup(QWidget):
    """A borderless popup that hosts collapsed ribbon group frames.

    The frames are owned by the AdaptiveTab; the popup only borrows them
    into its layout while open and hands them back when it closes, so no
    widget ownership is ever transferred."""

    def __init__(self, parent):
        super().__init__(parent, Qt.Popup)
        self.setObjectName("ribbonOverflow")
        self._hbox = QHBoxLayout(self)
        self._hbox.setContentsMargins(3, 3, 3, 3)
        self._hbox.setSpacing(2)
        self._frames = []

    def show_frames(self, frames, global_pos):
        self._frames = frames
        for frame in frames:
            self._hbox.addWidget(frame)
            frame.show()
        self.adjustSize()
        self.move(global_pos)
        self.show()

    def hideEvent(self, event):
        # Return the borrowed frames to the tab (detached + hidden).
        for frame in self._frames:
            self._hbox.removeWidget(frame)
            frame.setParent(self.parent())
            frame.hide()
        self._frames = []
        super().hideEvent(event)


class AdaptiveTab(QWidget):
    """Holds a row of ribbon group frames and, when they no longer fit the
    available width, collapses the rightmost ones into an overflow dropdown
    (Office / ArcGIS Pro style). Groups expand back as the tab widens."""

    def __init__(self, frames, spacing=2, parent=None):
        super().__init__(parent)
        self._frames = frames
        self._overflow_frames = []
        self._visible_count = -1
        self._hbox = QHBoxLayout(self)
        self._hbox.setContentsMargins(2, 1, 2, 1)
        self._hbox.setSpacing(spacing)

        self._overflow = QToolButton(self)
        self._overflow.setAutoRaise(True)
        self._overflow.setFocusPolicy(Qt.NoFocus)
        self._overflow.setText("»")
        self._overflow.setToolTip("More groups")
        self._overflow.clicked.connect(self._show_overflow)

        self._popup = OverflowPopup(self)

        for frame in self._frames:
            frame.setParent(self)
            self._hbox.addWidget(frame)
        self._hbox.addStretch()

    def showEvent(self, event):
        super().showEvent(event)
        # Defer until geometry is valid so widths are meaningful.
        QTimer.singleShot(0, self._relayout)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._relayout()

    def _relayout(self):
        if not self._frames:
            return
        margins = self._hbox.contentsMargins()
        spacing = self._hbox.spacing()
        avail = self.width() - margins.left() - margins.right()

        widths = [f.sizeHint().width() for f in self._frames]
        full = sum(widths) + spacing * (len(widths) - 1)
        if full <= avail:
            fit = len(self._frames)
        else:
            budget = avail - self._overflow.sizeHint().width() - spacing
            total = 0
            fit = 0
            for i, w in enumerate(widths):
                step = w + (spacing if i else 0)
                if total + step <= budget:
                    total += step
                    fit += 1
                else:
                    break
        if fit != self._visible_count:
            self._visible_count = fit
            self._apply(fit)

    def _apply(self, fit):
        if self._popup.isVisible():
            self._popup.hide()

        while self._hbox.count():
            item = self._hbox.takeAt(0)
            widget = item.widget()
            if widget is not None and widget is not self._overflow:
                widget.setParent(self)

        for frame in self._frames[:fit]:
            self._hbox.addWidget(frame)
            frame.show()

        self._overflow_frames = self._frames[fit:]
        for frame in self._overflow_frames:
            frame.setParent(self)
            frame.hide()

        if self._overflow_frames:
            self._hbox.addWidget(self._overflow)
            self._overflow.show()
        else:
            self._overflow.hide()
        self._hbox.addStretch()

    def _show_overflow(self):
        if not self._overflow_frames:
            return
        below = self._overflow.mapToGlobal(
            self._overflow.rect().bottomLeft()
        )
        self._popup.show_frames(self._overflow_frames, below)


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
        self.show_titles = layout_cfg.get("show_group_titles", True)
        self.adaptive = layout_cfg.get("adaptive", True)
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
        seen_ids = set()
        frames = []
        for group_cfg in tab_cfg.get("groups", []):
            if not group_cfg.get("visible", True):
                continue
            for resolved in resolve_groups(group_cfg, toolbars, menus, self.layout_cfg):
                actions = self._filter_actions(resolved["actions"], group_cfg, seen_ids)
                if not any(not a.isSeparator() for a in actions):
                    continue
                frames.append(
                    self._create_group(
                        resolved["title"], actions, group_cfg.get("labels", False)
                    )
                )

        if not frames:
            return None

        if self.adaptive:
            return AdaptiveTab(frames)

        # Non-adaptive fallback: a horizontally scrolling row.
        container = QWidget()
        hbox = QHBoxLayout(container)
        hbox.setContentsMargins(2, 1, 2, 1)
        hbox.setSpacing(2)
        for frame in frames:
            hbox.addWidget(frame)
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
        """Flat, ArcGIS Pro-like chrome derived from the app palette:
        underlined active tab, vertical group dividers, muted captions."""

        def rgba(color, alpha):
            return "rgba({}, {}, {}, {})".format(
                color.red(), color.green(), color.blue(), alpha
            )

        pal = self.palette()
        window = pal.color(QPalette.Window).name()
        text = pal.color(QPalette.WindowText)
        mid = pal.color(QPalette.Mid)
        highlight = pal.color(QPalette.Highlight)
        return """
            QTabWidget::pane {{
                border: none;
                border-top: 1px solid {divider};
                background: {window};
                margin: 0px;
            }}
            QTabWidget::tab-bar {{ alignment: left; }}
            QTabBar {{ background: transparent; }}
            QTabBar::tab {{
                background: transparent;
                border: none;
                border-bottom: 2px solid transparent;
                padding: 3px 12px;
                margin: 0px;
                font-size: 11px;
                color: {text};
            }}
            QTabBar::tab:selected {{
                color: {accent};
                border-bottom: 2px solid {accent};
                font-weight: 600;
            }}
            QTabBar::tab:hover:!selected {{ color: {accent}; }}
            QFrame#ribbonGroup {{
                border: none;
                border-right: 1px solid {divider};
                background: transparent;
            }}
            QLabel#ribbonGroupTitle {{
                color: {caption};
                font-size: 9px;
                padding: 0px 4px;
            }}
            QToolButton {{
                border: none;
                border-radius: 2px;
                padding: 1px 3px;
                background: transparent;
            }}
            QToolButton:hover {{ background: {hover}; }}
            QToolButton:pressed, QToolButton:checked {{ background: {pressed}; }}
        """.format(
            window=window,
            text=text.name(),
            accent=highlight.name(),
            divider=rgba(mid, 110),
            caption=rgba(text, 150),
            hover=rgba(highlight, 28),
            pressed=rgba(highlight, 55),
        )
