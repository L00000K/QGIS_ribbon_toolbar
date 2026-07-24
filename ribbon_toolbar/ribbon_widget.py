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


class RibbonGroup(QFrame):
    """A framed ribbon group whose buttons can be reflowed between 1 and N
    rows without rebuilding them. Reflowing lets the ribbon trade height
    for width: one row is short and wide, more rows are tall and narrow."""

    H_MARGIN = 3
    V_MARGIN = 1
    GRID_SPACING = 1

    def __init__(self, title, show_title, parent=None):
        super().__init__(parent)
        self.setObjectName("ribbonGroup")
        self._buttons = []
        self._widths = []
        self._rows = 0

        vbox = QVBoxLayout(self)
        vbox.setContentsMargins(
            self.H_MARGIN, self.V_MARGIN, self.H_MARGIN, self.V_MARGIN
        )
        vbox.setSpacing(0)
        self._grid = QGridLayout()
        self._grid.setSpacing(self.GRID_SPACING)
        self._grid.setContentsMargins(0, 0, 0, 0)
        vbox.addLayout(self._grid)
        vbox.addStretch()

        self._caption_w = 0
        if show_title:
            label = QLabel(title)
            label.setObjectName("ribbonGroupTitle")
            label.setAlignment(Qt.AlignCenter)
            vbox.addWidget(label)
            self._caption_w = label.sizeHint().width()

    def add_button(self, btn):
        self._buttons.append(btn)
        self._widths.append(btn.sizeHint().width())

    def button_count(self):
        return len(self._buttons)

    def reflow(self, rows):
        rows = max(1, rows)
        if rows == self._rows or not self._buttons:
            if rows == self._rows:
                return
        while self._grid.count():
            self._grid.takeAt(0)
        for i, btn in enumerate(self._buttons):
            self._grid.addWidget(btn, i % rows, i // rows)
        self._rows = rows

    def width_at(self, rows):
        """Predicted frame width at ``rows`` rows, from stored button widths."""
        rows = max(1, rows)
        n = len(self._widths)
        pad = 2 * self.H_MARGIN
        if n == 0:
            return self._caption_w + pad
        ncols = -(-n // rows)  # ceil division
        total = 0
        for c in range(ncols):
            col = self._widths[c * rows : (c + 1) * rows]
            total += max(col)
        total += self.GRID_SPACING * (ncols - 1) + pad
        return max(total, self._caption_w + pad)


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

    def __init__(self, frames, spacing=2, spread=True, parent=None):
        super().__init__(parent)
        self._frames = frames
        self._spread = spread
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

        self._overflow_frames = self._frames[fit:]
        for frame in self._overflow_frames:
            frame.setParent(self)
            frame.hide()

        visible = self._frames[:fit]
        if self._overflow_frames:
            # Too narrow: pack groups left, then the overflow button.
            for frame in visible:
                self._hbox.addWidget(frame)
                frame.show()
            self._hbox.addWidget(self._overflow)
            self._overflow.show()
            self._hbox.addStretch()
        else:
            self._overflow.hide()
            # Everything fits: spread groups across the full width so a
            # wide screen is used, instead of bunching them on the left.
            for i, frame in enumerate(visible):
                if self._spread and i > 0:
                    self._hbox.addStretch()
                self._hbox.addWidget(frame)
                frame.show()
            if not self._spread or len(visible) <= 1:
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
        self.max_rows = layout_cfg.get("rows", 2)
        self.icon_px = layout_cfg.get("icon_size", 16)
        self.btn_height = self.icon_px + 6
        self.show_titles = layout_cfg.get("show_group_titles", True)
        self.adaptive = layout_cfg.get("adaptive", True)
        self.auto_rows = layout_cfg.get("auto_rows", True)
        self.spread = layout_cfg.get("spread", True)
        # Index of every triggerable action (key -> QAction) and the
        # usage tracker behind the Favorites tab.
        self._action_index = {}
        self._usage = None
        # Connections to long-lived QGIS objects, released in teardown()
        self._connections = []
        self.setStyleSheet(self._build_stylesheet())
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setUsesScrollButtons(True)
        self.currentChanged.connect(self._update_height)
        self._install_corner_menu()

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def build_ribbon(self):
        """Populate the ribbon from the layout configuration."""
        toolbars = collect_toolbars(self.main_window)
        menus = collect_menus(self.main_window)
        self._build_usage_index(toolbars, menus)
        for tab_cfg in self.layout_cfg.get("tabs", []):
            if not tab_cfg.get("visible", True):
                continue
            page = self._build_tab(tab_cfg, toolbars, menus)
            if page is not None:
                self.addTab(page, self._tab_title(tab_cfg, menus))
        self._update_height()

    def _build_usage_index(self, toolbars, menus):
        """Index all triggerable actions and record their usage globally, so
        the Favorites tab reflects tools used anywhere in QGIS, not just here."""
        from .ribbon_usage import UsageTracker

        self._usage = UsageTracker()
        index = {}
        for tb in toolbars.values():
            for action in tb.actions():
                self._index_action(action, index)
        for menu in menus.values():
            self._index_menu(menu, index)
        self._action_index = index
        for key, action in index.items():
            slot = self._usage_slot(key)
            action.triggered.connect(slot)
            self._connections.append((action.triggered, slot))

    def _index_menu(self, menu, index, depth=0):
        if depth > 4:
            return
        for action in menu.actions():
            submenu = action.menu()
            if submenu is not None:
                self._index_menu(submenu, index, depth + 1)
            else:
                self._index_action(action, index)

    def _index_action(self, action, index):
        if action.isSeparator():
            return
        key = action_key(action)
        if key and key not in index:
            index[key] = action

    def _usage_slot(self, key):
        def record(checked=False, key=key):
            if self._usage is not None:
                self._usage.record(key)

        return record

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
        has_usage = False
        for group_cfg in tab_cfg.get("groups", []):
            if not group_cfg.get("visible", True):
                continue
            kind = group_cfg.get("kind")
            if kind in ("frequent", "recent"):
                has_usage = True
                frame = self._build_usage_group(kind, group_cfg, seen_ids)
                if frame is not None:
                    frames.append(frame)
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
            return self._empty_favorites_page() if has_usage else None

        rows = self._rows_for(frames)
        for frame in frames:
            frame.reflow(rows)

        page = self._page_for_frames(frames)
        page._rib_rows = rows
        return page

    def _page_for_frames(self, frames):
        if self.adaptive:
            return AdaptiveTab(frames, spread=self.spread)

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

    def _rows_for(self, frames):
        """Per-tab row count: two rows is the standard, dropping to one for
        sparse tabs and rising toward max_rows for very dense ones."""
        if not self.auto_rows:
            return self.max_rows
        total = sum(f.button_count() for f in frames)
        if total <= 8:
            rows = 1
        elif total <= 22:
            rows = 2
        else:
            rows = 3
        return max(1, min(self.max_rows, rows))

    def _build_usage_group(self, kind, group_cfg, seen_ids):
        # Frequently- and recently-used lists overlap heavily, so give each
        # usage group its own dedup scope instead of the shared tab one.
        actions = self._usage_actions(kind)
        actions = self._filter_actions(actions, group_cfg, set())
        if not actions:
            return None
        return self._create_group(
            group_cfg.get("title") or kind.title(),
            actions,
            group_cfg.get("labels", True),
        )

    def _usage_actions(self, kind, count=12):
        if self._usage is None:
            return []
        by = "count" if kind == "frequent" else "last"
        keys = self._usage.top(count, by=by)
        return [self._action_index[k] for k in keys if k in self._action_index]

    def _empty_favorites_page(self):
        page = QWidget()
        box = QHBoxLayout(page)
        box.setContentsMargins(8, 2, 8, 2)
        hint = QLabel(
            "Use some tools — the ones you use most and most recently "
            "will appear here. Click ⚙ ▸ Refresh Ribbon to update."
        )
        hint.setObjectName("ribbonGroupTitle")
        box.addWidget(hint)
        box.addStretch()
        page._rib_rows = 1
        return page

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
        """A reflowable ribbon group: a button grid plus an optional title."""
        group = RibbonGroup(title, self.show_titles)
        for action in actions:
            if action.isSeparator():
                continue
            if isinstance(action, QWidgetAction):
                btn = self._make_widget_button(action.defaultWidget(), labels, group)
            else:
                btn = self._make_action_button(action, labels, group)
            if btn is None:
                continue
            group.add_button(btn)
        group.reflow(self.max_rows)
        return group

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

    def _height_for(self, rows):
        content = rows * self.btn_height + (rows - 1) + 6
        if self.show_titles:
            content += 14
        return self.tabBar().sizeHint().height() + content + 4

    def _update_height(self, *args):
        """Size the ribbon to the current tab's row count, so a sparse tab
        stays shallow and a dense one is allowed to be taller."""
        page = self.currentWidget()
        rows = getattr(page, "_rib_rows", self.max_rows)
        self.setFixedHeight(self._height_for(rows))

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
