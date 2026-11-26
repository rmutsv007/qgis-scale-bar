# -*- coding: utf-8 -*-
"""
Main Plugin Lifecycle for Custom Scale Bar.
Registers the custom Layout Item and its GUI metadata in QGIS, and also adds a
convenient button/action inside every opened Print Layout Designer window so
users can click-and-drag to place a Custom Scale Bar directly from the toolbar
or Add Item menu.
"""

import os
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction, QMessageBox
from qgis.core import QgsApplication, QgsLayoutPoint, QgsLayoutSize, QgsUnitTypes
from qgis.gui import QgsGui

from .scalebar_item import CUSTOM_SCALEBAR_TYPE, CustomScaleBarItem, CustomScaleBarMetadata
from .scalebar_gui import CustomScaleBarGuiMetadata


class CustomScaleBarPlugin:
    """QGIS Plugin registering the Custom Scale Bar layout item."""

    # Class-level list so old metadata wrappers stay alive across plugin reloads
    _REGISTERED_METADATA = []

    def __init__(self, iface):
        self.iface = iface
        self.item_metadata = None
        self.gui_metadata = None
        self.main_action = None
        self._designer_actions = []

    def _icon(self) -> QIcon:
        icon_path = os.path.join(os.path.dirname(__file__), "icon.svg")
        if os.path.exists(icon_path):
            return QIcon(icon_path)
        return QgsApplication.getThemeIcon("/mActionScaleBar.svg")

    def initGui(self):
        # 1. Register core layout item metadata if not already registered
        registry = QgsApplication.layoutItemRegistry()
        if registry.itemMetadata(CUSTOM_SCALEBAR_TYPE) is None:
            self.item_metadata = CustomScaleBarMetadata()
            CustomScaleBarPlugin._REGISTERED_METADATA.append(self.item_metadata)
            registry.addLayoutItemType(self.item_metadata)
            try:
                from qgis.PyQt import sip
                sip.transferto(self.item_metadata, None)
            except Exception:
                pass

        # 2. Register GUI metadata in QgsGui.layoutItemGuiRegistry()
        # This automatically adds "Add Custom Scale Bar" to the Print Layout toolbox & Add Item menu!
        gui_registry = QgsGui.layoutItemGuiRegistry()
        existing_ids = [
            gui_registry.itemMetadata(mid).type()
            for mid in gui_registry.itemMetadataIds()
            if gui_registry.itemMetadata(mid) is not None
        ]
        if CUSTOM_SCALEBAR_TYPE not in existing_ids:
            self.gui_metadata = CustomScaleBarGuiMetadata()
            CustomScaleBarPlugin._REGISTERED_METADATA.append(self.gui_metadata)
            gui_registry.addLayoutItemGuiMetadata(self.gui_metadata)
            try:
                from qgis.PyQt import sip
                sip.transferto(self.gui_metadata, None)
            except Exception:
                pass

        # 3. Also hook layoutDesignerOpened to add a quick one-click "Quick Add Custom Scale Bar"
        # button to the Print Layout toolbar if the user prefers instant placement.
        self.iface.layoutDesignerOpened.connect(self._on_designer_opened)
        for designer in self.iface.openLayoutDesigners():
            self._on_designer_opened(designer)

        # 4. Add a main QGIS Plugins menu item explaining how to use it in Print Layout
        self.main_action = QAction(
            self._icon(), "Custom Scale Bar (Print Layout)", self.iface.mainWindow()
        )
        self.main_action.triggered.connect(self._show_help_or_open_layout)
        self.iface.addPluginToMenu("&Custom Scale Bar", self.main_action)

    def _on_designer_opened(self, designer):
        """When a Print Layout window opens, ensure a quick-add toolbar action is available."""
        try:
            win = designer.window()
            act = QAction(
                self._icon(),
                "Quick Add Custom Scale Bar",
                win,
            )
            act.setToolTip(
                "Insert a Custom Scale Bar (or use 'Add Item -> Add Custom Scale Bar' to draw on layout)"
            )
            act.triggered.connect(lambda checked=False, d=designer: self._quick_add_item(d))
            designer.actionsToolbar().addAction(act)
            self._designer_actions.append((designer, act))
        except Exception:
            pass

    def _quick_add_item(self, designer):
        """Insert a pre-configured Custom Scale Bar onto the current Print Layout."""
        layout = designer.masterLayout()
        if layout is None:
            return
        item = CustomScaleBarItem(layout)
        item.attemptMove(QgsLayoutPoint(20.0, 180.0, QgsUnitTypes.LayoutMillimeters))
        item.attemptResize(QgsLayoutSize(115.0, 20.0, QgsUnitTypes.LayoutMillimeters))
        layout.addLayoutItem(item)
        item.adjustSizeToContent()
        layout.deselectAll()
        item.setSelected(True)
        designer.selectItems([item])

    def _show_help_or_open_layout(self):
        open_designers = self.iface.openLayoutDesigners()
        if open_designers:
            self._quick_add_item(open_designers[0])
            open_designers[0].window().raise_()
            open_designers[0].window().activateWindow()
            return

        QMessageBox.information(
            self.iface.mainWindow(),
            "Custom Scale Bar",
            "<b>Custom Scale Bar is registered in Print Layout!</b><br><br>"
            "To use it:<br>"
            "1. Open any Print Layout (<b>Project &rarr; Layouts</b>).<br>"
            "2. Click <b>Add Item &rarr; Add Custom Scale Bar</b> (or the Custom Scale Bar icon on the left toolbox / top toolbar) and drag on the page.<br>"
            "3. Configure custom division stops (e.g. <code>50, 100, 250, 500, 1000</code>), left subdivisions before 0, and bar style in the <b>Item Properties</b> panel on the right.",
        )

    def unload(self):
        try:
            self.iface.layoutDesignerOpened.disconnect(self._on_designer_opened)
        except Exception:
            pass

        for designer, act in self._designer_actions:
            try:
                designer.actionsToolbar().removeAction(act)
            except Exception:
                pass
        self._designer_actions.clear()

        if self.main_action is not None:
            self.iface.removePluginMenu("&Custom Scale Bar", self.main_action)
            self.main_action = None
