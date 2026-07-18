# -*- coding: utf-8 -*-
"""
Customize dialog for the ribbon layout.

Presents the layout as a tree of tabs → groups → actions with
checkboxes for visibility, a per-group "Labels" toggle, Up/Down
reordering for tabs and groups, and global sizing options.  The result
is a layout dict ready for ribbon_config.save_layout().
"""

import copy

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from .ribbon_config import CONFIG_VERSION, default_layout
from .ribbon_widget import (
    action_key,
    clean_text,
    collect_menus,
    collect_toolbars,
    resolve_groups,
)

TAB_ROLE = Qt.UserRole
GROUP_ROLE = Qt.UserRole + 1
ACTION_ROLE = Qt.UserRole + 2


def _check(state):
    return Qt.Checked if state else Qt.Unchecked


class CustomizeDialog(QDialog):
    """Edit the ribbon layout and return the result via result_layout()."""

    def __init__(self, layout_cfg, main_window, parent=None):
        super().__init__(parent or main_window)
        self.setWindowTitle("Customize Ribbon")
        self.resize(540, 600)
        self._main_window = main_window
        self._build_ui()
        self._populate(copy.deepcopy(layout_cfg))

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self):
        vbox = QVBoxLayout(self)
        vbox.addWidget(
            QLabel(
                "Check items to show them in the ribbon. "
                "Use Move Up/Down to reorder tabs and groups."
            )
        )

        self.tree = QTreeWidget()
        self.tree.setColumnCount(2)
        self.tree.setHeaderLabels(["Item", "Labels"])
        self.tree.setColumnWidth(0, 380)
        vbox.addWidget(self.tree)

        move_row = QHBoxLayout()
        up_btn = QPushButton("Move Up")
        up_btn.clicked.connect(lambda: self._move_current(-1))
        down_btn = QPushButton("Move Down")
        down_btn.clicked.connect(lambda: self._move_current(1))
        move_row.addWidget(up_btn)
        move_row.addWidget(down_btn)
        move_row.addStretch()
        vbox.addLayout(move_row)

        opts_row = QHBoxLayout()
        opts_row.addWidget(QLabel("Button rows:"))
        self.rows_spin = QSpinBox()
        self.rows_spin.setRange(1, 3)
        opts_row.addWidget(self.rows_spin)
        opts_row.addWidget(QLabel("Icon size:"))
        self.icon_spin = QSpinBox()
        self.icon_spin.setRange(12, 48)
        self.icon_spin.setSuffix(" px")
        opts_row.addWidget(self.icon_spin)
        self.titles_check = QCheckBox("Show group titles")
        opts_row.addWidget(self.titles_check)
        opts_row.addStretch()
        vbox.addLayout(opts_row)

        buttons = QDialogButtonBox(
            QDialogButtonBox.RestoreDefaults
            | QDialogButtonBox.Ok
            | QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.RestoreDefaults).clicked.connect(
            self._restore_defaults
        )
        vbox.addWidget(buttons)

    # ------------------------------------------------------------------
    # Populate
    # ------------------------------------------------------------------

    def _populate(self, layout_cfg):
        self.tree.clear()
        self.rows_spin.setValue(layout_cfg.get("rows", 2))
        self.icon_spin.setValue(layout_cfg.get("icon_size", 16))
        self.titles_check.setChecked(layout_cfg.get("show_group_titles", True))

        toolbars = collect_toolbars(self._main_window)
        menus = collect_menus(self._main_window)
        for tab_cfg in layout_cfg.get("tabs", []):
            tab_item = QTreeWidgetItem(self.tree)
            tab_item.setText(0, self._tab_label(tab_cfg, menus))
            tab_item.setFlags(
                Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable
            )
            tab_item.setCheckState(0, _check(tab_cfg.get("visible", True)))
            tab_item.setData(0, TAB_ROLE, tab_cfg)
            for group_cfg in tab_cfg.get("groups", []):
                self._add_group_item(
                    tab_item, group_cfg, toolbars, menus, layout_cfg
                )
            tab_item.setExpanded(False)

    def _tab_label(self, tab_cfg, menus):
        menu = menus.get(tab_cfg.get("menu")) if tab_cfg.get("menu") else None
        if menu is not None and clean_text(menu.title()):
            return clean_text(menu.title())
        return tab_cfg.get("title") or tab_cfg.get("id", "")

    def _add_group_item(self, tab_item, group_cfg, toolbars, menus, layout_cfg):
        group_item = QTreeWidgetItem(tab_item)
        group_item.setFlags(
            Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable
        )
        group_item.setCheckState(0, _check(group_cfg.get("visible", True)))
        group_item.setCheckState(1, _check(group_cfg.get("labels", False)))
        group_item.setData(0, GROUP_ROLE, group_cfg)

        if group_cfg.get("kind") == "plugin_toolbars":
            group_item.setText(0, "Plugin toolbars (automatic)")
            return

        resolved = resolve_groups(group_cfg, toolbars, menus, layout_cfg)
        if not resolved:
            # Source not present on this machine — keep the entry so the
            # saved layout is not silently destroyed.
            group_item.setText(
                0, "{} (not loaded)".format(group_cfg.get("source") or "?")
            )
            return
        group_item.setText(0, resolved[0]["title"])

        hidden = set(group_cfg.get("hidden", []))
        for action in resolved[0]["actions"]:
            if action.isSeparator():
                continue
            key = action_key(action)
            if not key:
                continue
            action_item = QTreeWidgetItem(group_item)
            action_item.setFlags(
                Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable
            )
            action_item.setText(0, clean_text(action.text()) or key)
            action_item.setIcon(0, action.icon())
            action_item.setCheckState(0, _check(key not in hidden))
            action_item.setData(0, ACTION_ROLE, key)

    # ------------------------------------------------------------------
    # Interaction
    # ------------------------------------------------------------------

    def _move_current(self, delta):
        item = self.tree.currentItem()
        if item is None or item.data(0, ACTION_ROLE) is not None:
            return
        parent = item.parent()
        if parent is None:
            index = self.tree.indexOfTopLevelItem(item)
            target = index + delta
            if 0 <= target < self.tree.topLevelItemCount():
                expanded = item.isExpanded()
                self.tree.takeTopLevelItem(index)
                self.tree.insertTopLevelItem(target, item)
                item.setExpanded(expanded)
                self.tree.setCurrentItem(item)
        else:
            index = parent.indexOfChild(item)
            target = index + delta
            if 0 <= target < parent.childCount():
                expanded = item.isExpanded()
                parent.takeChild(index)
                parent.insertChild(target, item)
                item.setExpanded(expanded)
                self.tree.setCurrentItem(item)

    def _restore_defaults(self):
        self._populate(default_layout())

    # ------------------------------------------------------------------
    # Result
    # ------------------------------------------------------------------

    def result_layout(self):
        tabs = []
        for i in range(self.tree.topLevelItemCount()):
            tab_item = self.tree.topLevelItem(i)
            tab_cfg = copy.deepcopy(tab_item.data(0, TAB_ROLE))
            tab_cfg["visible"] = tab_item.checkState(0) == Qt.Checked
            tab_cfg["groups"] = [
                self._group_result(tab_item.child(j))
                for j in range(tab_item.childCount())
            ]
            tabs.append(tab_cfg)
        return {
            "version": CONFIG_VERSION,
            "rows": self.rows_spin.value(),
            "icon_size": self.icon_spin.value(),
            "show_group_titles": self.titles_check.isChecked(),
            "tabs": tabs,
        }

    def _group_result(self, group_item):
        group_cfg = copy.deepcopy(group_item.data(0, GROUP_ROLE))
        group_cfg["visible"] = group_item.checkState(0) == Qt.Checked
        group_cfg["labels"] = group_item.checkState(1) == Qt.Checked
        if group_item.childCount():
            group_cfg["hidden"] = [
                group_item.child(k).data(0, ACTION_ROLE)
                for k in range(group_item.childCount())
                if group_item.child(k).checkState(0) != Qt.Checked
            ]
        return group_cfg
