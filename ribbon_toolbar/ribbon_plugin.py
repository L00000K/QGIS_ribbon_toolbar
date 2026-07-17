# -*- coding: utf-8 -*-
"""
Main plugin class for Ribbon Toolbar.
Handles plugin lifecycle, toggling between ribbon and classic UI,
rebuilding the ribbon after customization and persisting state.
"""

from pathlib import Path

from qgis.core import QgsSettings
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction, QHBoxLayout, QToolBar, QToolButton, QWidget

from . import ribbon_config

SETTINGS_ACTIVE = "ribbon_toolbar/active"


class RibbonToolbarPlugin:
    """QGIS Plugin: Replaces menus/toolbars with a ribbon interface."""

    RIBBON_OBJECT_NAME = "RibbonToolbarMain"

    def __init__(self, iface):
        self.iface = iface
        self.main_window = iface.mainWindow()
        self.ribbon_active = False
        self.ribbon_toolbar = None
        self.ribbon_widget = None
        self.toggle_action = None
        # Store original visibility states for toolbars
        self._original_toolbar_visibility = {}
        self.plugin_dir = Path(__file__).parent
        # Menubar corner widget
        self._corner_widget = None

    def initGui(self):
        """Called when plugin is loaded."""
        icon_path = self.plugin_dir / "icon.svg"
        icon = QIcon(str(icon_path)) if icon_path.exists() else QIcon()

        # Toggle action
        self.toggle_action = QAction(icon, "Toggle Ribbon Toolbar", self.main_window)
        self.toggle_action.setCheckable(True)
        self.toggle_action.setChecked(True)
        self.toggle_action.triggered.connect(self._on_toggle)
        self.iface.addToolBarIcon(self.toggle_action)
        self.iface.addPluginToMenu("&Ribbon Toolbar", self.toggle_action)

        # Create button and corner widget for menubar
        toggle_button = QToolButton()
        toggle_button.setDefaultAction(self.toggle_action)
        toggle_button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)

        corner_layout = QHBoxLayout()
        corner_layout.setContentsMargins(0, 0, 10, 0)  # 10 px margin on right side
        corner_layout.addWidget(toggle_button)

        self._corner_widget = QWidget()
        self._corner_widget.setLayout(corner_layout)
        self.main_window.menuBar().setCornerWidget(
            self._corner_widget, Qt.TopRightCorner
        )
        self._corner_widget.setVisible(True)

        # Connect to initialization completed to render ribbon
        self.iface.initializationCompleted.connect(self._on_initialization_completed)

    def unload(self):
        """Called when plugin is unloaded."""
        if self.ribbon_active:
            self._deactivate_ribbon()
        if self.toggle_action is not None:
            self.iface.removePluginMenu("&Ribbon Toolbar", self.toggle_action)
            self.iface.removeToolBarIcon(self.toggle_action)
            self.toggle_action = None

        # Disconnect initialization signal if still connected
        try:
            self.iface.initializationCompleted.disconnect(
                self._on_initialization_completed
            )
        except TypeError:
            pass

        # Remove the toggle button from the menubar corner
        if self._corner_widget is not None:
            self._corner_widget.setVisible(False)
            self.main_window.menuBar().setCornerWidget(QWidget())
            self._corner_widget = None

    def _on_initialization_completed(self):
        """Called after QGIS initialization is complete."""
        try:
            self.iface.initializationCompleted.disconnect(
                self._on_initialization_completed
            )
        except TypeError:
            pass

        # Activate the ribbon unless the user turned it off last session
        active = QgsSettings().value(SETTINGS_ACTIVE, True, type=bool)
        self.toggle_action.setChecked(active)
        if active:
            self._activate_ribbon()

    def _on_toggle(self, checked):
        QgsSettings().setValue(SETTINGS_ACTIVE, checked)
        if checked:
            self._activate_ribbon()
        else:
            self._deactivate_ribbon()

    def _activate_ribbon(self):
        """Hide toolbars and show the ribbon."""
        if self.ribbon_active:
            return

        # Save current toolbar visibility so deactivation can restore it
        self._original_toolbar_visibility = {}
        for tb in self._main_window_toolbars():
            self._original_toolbar_visibility[tb.objectName()] = tb.isVisible()

        self._create_ribbon()
        self._hide_main_toolbars()
        self.ribbon_active = True

    def rebuild_ribbon(self):
        """Rebuild the ribbon in place (after customize/refresh)."""
        if not self.ribbon_active:
            return
        self._destroy_ribbon()
        self._create_ribbon()
        self._hide_main_toolbars()

    def _create_ribbon(self):
        from .ribbon_widget import RibbonWidget

        layout_cfg = ribbon_config.load_layout()
        self.ribbon_widget = RibbonWidget(self.iface, layout_cfg, self.main_window)
        self.ribbon_widget.customizeRequested.connect(self._open_customize)
        self.ribbon_widget.refreshRequested.connect(self.rebuild_ribbon)

        self.ribbon_toolbar = QToolBar("Ribbon", self.main_window)
        self.ribbon_toolbar.setObjectName(self.RIBBON_OBJECT_NAME)
        self.ribbon_toolbar.setMovable(False)
        self.ribbon_toolbar.setFloatable(False)
        self.ribbon_toolbar.setContextMenuPolicy(Qt.PreventContextMenu)

        self.ribbon_widget.build_ribbon()
        self.ribbon_toolbar.addWidget(self.ribbon_widget)
        self.main_window.addToolBar(Qt.TopToolBarArea, self.ribbon_toolbar)

    def _destroy_ribbon(self):
        if self.ribbon_toolbar is None:
            return
        if self.ribbon_widget is not None:
            self.ribbon_widget.teardown()
        self.main_window.removeToolBar(self.ribbon_toolbar)
        self.ribbon_toolbar.deleteLater()
        self.ribbon_toolbar = None
        self.ribbon_widget = None

    def _main_window_toolbars(self):
        """Toolbars docked to the main window, excluding the ribbon."""
        return [
            tb
            for tb in self.main_window.findChildren(QToolBar)
            if tb.objectName() != self.RIBBON_OBJECT_NAME
            and tb.parent() == self.main_window
        ]

    def _hide_main_toolbars(self):
        for tb in self._main_window_toolbars():
            # Record toolbars that appeared after activation (late-loaded
            # plugins) so deactivation can restore them too
            self._original_toolbar_visibility.setdefault(
                tb.objectName(), tb.isVisible()
            )
            tb.setVisible(False)

    def _open_customize(self):
        from .customize_dialog import CustomizeDialog

        dialog = CustomizeDialog(ribbon_config.load_layout(), self.main_window)
        if dialog.exec():
            ribbon_config.save_layout(dialog.result_layout())
            self.rebuild_ribbon()

    def _deactivate_ribbon(self):
        """Restore toolbars and remove the ribbon."""
        if not self.ribbon_active:
            return

        self._destroy_ribbon()

        # Restore menubar
        self.main_window.menuBar().setVisible(True)

        # If every toolbar was hidden before activation, fall back to a
        # sensible default set instead of restoring an empty UI
        all_toolbars_hidden = all(
            not visible for visible in self._original_toolbar_visibility.values()
        )
        default_toolbars = {
            "mFileToolBar",
            "mDigitizeToolBar",
            "mMapNavToolBar",
            "mAttributesToolBar",
            "mPluginToolBar",
            "mSnappingToolBar",
            "mDataSourceManagerToolBar",
            "mSelectionToolBar",
        }
        for tb in self._main_window_toolbars():
            if tb.isVisible():
                continue
            name = tb.objectName()
            if name not in self._original_toolbar_visibility:
                continue
            if all_toolbars_hidden:
                tb.setVisible(name in default_toolbars)
            else:
                tb.setVisible(self._original_toolbar_visibility[name])

        self.ribbon_active = False
        self.toggle_action.setChecked(False)
