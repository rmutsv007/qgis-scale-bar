# -*- coding: utf-8 -*-
"""
GUI Metadata and Item Properties Configuration Widget for CustomScaleBarItem.
Appears natively in the QGIS Print Layout 'Item Properties' panel whenever a
Custom Scale Bar item is selected, and adds a creation tool to the Print Layout.
"""

import os
from qgis.PyQt import sip
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QIcon, QFont
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFontDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)
from qgis.core import QgsApplication, QgsLayoutItemRegistry
from qgis.gui import (
    QgsCollapsibleGroupBoxBasic,
    QgsColorButton,
    QgsLayoutItemAbstractGuiMetadata,
    QgsLayoutItemBaseWidget,
    QgsLayoutItemComboBox,
    QgsLayoutItemPropertiesWidget,
    QgsScrollArea,
)

from .scalebar_item import (
    CUSTOM_SCALEBAR_TYPE,
    CustomScaleBarItem,
    DIVISION_MODES,
    LABEL_FREQUENCIES,
    LABEL_POSITIONS,
    LEFT_SUBDIVISION_MODES,
    STYLE_DEFINITIONS,
    UNIT_DEFINITIONS,
    UNIT_LABEL_POSITIONS,
)


PRESET_STOPS = [
    ("Custom...", ""),
    ("50, 100, 250, 500, 1000", "50, 100, 250, 500, 1000"),
    ("100, 250, 500, 1000", "100, 250, 500, 1000"),
    ("10, 25, 50, 100, 200", "10, 25, 50, 100, 200"),
    ("250, 500, 1000, 2000", "250, 500, 1000, 2000"),
    ("0.5, 1, 2, 5, 10", "0.5, 1, 2, 5, 10"),
    ("1, 2, 5, 10, 20", "1, 2, 5, 10, 20"),
]


class CustomScaleBarWidget(QgsLayoutItemBaseWidget):
    """Side-panel configuration widget in QGIS Print Layout Item Properties."""

    def __init__(self, parent, item: CustomScaleBarItem):
        super().__init__(parent, item)
        self._item = item
        self._updating = False
        self.setPanelTitle("Custom Scale Bar Properties")
        self._build_ui()
        self._load_from_item()

    def _build_ui(self):
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)

        scroll_area = QgsScrollArea(self)
        scroll_area.setFrameShape(QFrame.NoFrame)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll_area.setWidgetResizable(True)
        outer_layout.addWidget(scroll_area)

        scroll_content = QWidget(scroll_area)
        scroll_area.setWidget(scroll_content)

        main_layout = QVBoxLayout(scroll_content)
        main_layout.setContentsMargins(4, 4, 4, 4)
        main_layout.setSpacing(6)

        # 1. Main Properties (Linked Map, Style, Units)
        grp_main = QgsCollapsibleGroupBoxBasic("Main Properties", self)
        form_main = QFormLayout(grp_main)

        self.cmb_map = QgsLayoutItemComboBox(
            self, self._item.layout() if self._item else None
        )
        self.cmb_map.setItemType(QgsLayoutItemRegistry.LayoutMap)
        self.cmb_map.itemChanged.connect(self._on_map_changed)
        form_main.addRow("Map:", self.cmb_map)

        self.cmb_style = QComboBox(self)
        self.cmb_style.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        for key, label in STYLE_DEFINITIONS:
            self.cmb_style.addItem(label, key)
        self.cmb_style.currentIndexChanged.connect(self._apply_to_item)
        form_main.addRow("Bar Style:", self.cmb_style)

        self.cmb_unit = QComboBox(self)
        self.cmb_unit.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        for key, label, abbr, _ in UNIT_DEFINITIONS:
            self.cmb_unit.addItem(f"{label} ({abbr})", key)
        self.cmb_unit.currentIndexChanged.connect(self._on_unit_changed)
        form_main.addRow("Division Units:", self.cmb_unit)

        self.txt_unit_label = QLineEdit(self)
        self.txt_unit_label.textChanged.connect(self._apply_to_item)
        form_main.addRow("Unit Label:", self.txt_unit_label)

        self.btn_auto_scale = QPushButton("Auto-Fit to Map Scale", self)
        self.btn_auto_scale.clicked.connect(self._on_auto_scale_stops)
        form_main.addRow("", self.btn_auto_scale)

        self.btn_fit_size = QPushButton("Fit Box to Bar Width", self)
        self.btn_fit_size.clicked.connect(self._on_fit_size)
        form_main.addRow("", self.btn_fit_size)

        main_layout.addWidget(grp_main)

        # 2. Right Divisions (Main Divisions right of 0)
        grp_right = QgsCollapsibleGroupBoxBasic("Main Divisions (Right of 0)", self)
        form_right = QFormLayout(grp_right)

        self.cmb_div_mode = QComboBox(self)
        self.cmb_div_mode.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        for key, label in DIVISION_MODES:
            self.cmb_div_mode.addItem(label, key)
        self.cmb_div_mode.currentIndexChanged.connect(self._on_div_mode_changed)
        form_right.addRow("Mode:", self.cmb_div_mode)

        self.cmb_presets = QComboBox(self)
        self.cmb_presets.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        for label, stops_str in PRESET_STOPS:
            self.cmb_presets.addItem(label, stops_str)
        self.cmb_presets.currentIndexChanged.connect(self._on_preset_selected)
        form_right.addRow("Quick Preset:", self.cmb_presets)

        self.txt_custom_right = QLineEdit(self)
        self.txt_custom_right.setPlaceholderText("e.g. 50, 100, 250, 500, 1000")
        self.txt_custom_right.textChanged.connect(self._apply_to_item)
        form_right.addRow("Stops from 0:", self.txt_custom_right)

        self.spn_equal_val = QDoubleSpinBox(self)
        self.spn_equal_val.setRange(0.001, 100000000.0)
        self.spn_equal_val.setDecimals(2)
        self.spn_equal_val.setSingleStep(50.0)
        self.spn_equal_val.valueChanged.connect(self._apply_to_item)
        form_right.addRow("Division Value:", self.spn_equal_val)

        self.spn_equal_cnt = QSpinBox(self)
        self.spn_equal_cnt.setRange(1, 50)
        self.spn_equal_cnt.valueChanged.connect(self._apply_to_item)
        form_right.addRow("Number of Divisions:", self.spn_equal_cnt)

        main_layout.addWidget(grp_right)

        # 3. Left Subdivisions (Before 0)
        grp_left = QgsCollapsibleGroupBoxBasic("Subdivisions (Left of 0)", self)
        form_left = QFormLayout(grp_left)

        self.cmb_left_mode = QComboBox(self)
        self.cmb_left_mode.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        for key, label in LEFT_SUBDIVISION_MODES:
            self.cmb_left_mode.addItem(label, key)
        self.cmb_left_mode.currentIndexChanged.connect(self._on_left_mode_changed)
        form_left.addRow("Left Mode:", self.cmb_left_mode)

        self.spn_left_total = QDoubleSpinBox(self)
        self.spn_left_total.setRange(0.0, 100000000.0)
        self.spn_left_total.setDecimals(2)
        self.spn_left_total.setSingleStep(25.0)
        self.spn_left_total.valueChanged.connect(self._apply_to_item)
        form_left.addRow("Left Total Length:", self.spn_left_total)

        self.spn_left_subs = QSpinBox(self)
        self.spn_left_subs.setRange(1, 50)
        self.spn_left_subs.valueChanged.connect(self._apply_to_item)
        form_left.addRow("Subdivisions Count:", self.spn_left_subs)

        self.txt_custom_left = QLineEdit(self)
        self.txt_custom_left.setPlaceholderText("e.g. 25, 50, 100")
        self.txt_custom_left.textChanged.connect(self._apply_to_item)
        form_left.addRow("Custom Left Stops:", self.txt_custom_left)

        self.spn_left_height_ratio = QDoubleSpinBox(self)
        self.spn_left_height_ratio.setRange(0.2, 1.0)
        self.spn_left_height_ratio.setSingleStep(0.1)
        self.spn_left_height_ratio.setDecimals(2)
        self.spn_left_height_ratio.setToolTip("1.0 = same height as main bar; 0.5 = half height for subdivisions")
        self.spn_left_height_ratio.valueChanged.connect(self._apply_to_item)
        form_left.addRow("Left Height Ratio:", self.spn_left_height_ratio)

        self.chk_neg_sign = QCheckBox("Show '-' sign on left of 0", self)
        self.chk_neg_sign.toggled.connect(self._apply_to_item)
        form_left.addRow("", self.chk_neg_sign)

        main_layout.addWidget(grp_left)

        # 4. Numbers, Marks & Unit Label Placement
        grp_labels = QgsCollapsibleGroupBoxBasic("Numbers, Marks & Placement", self)
        form_labels = QFormLayout(grp_labels)

        self.cmb_lbl_freq = QComboBox(self)
        self.cmb_lbl_freq.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        for key, label in LABEL_FREQUENCIES:
            self.cmb_lbl_freq.addItem(label, key)
        self.cmb_lbl_freq.currentIndexChanged.connect(self._apply_to_item)
        form_labels.addRow("Numbers Frequency:", self.cmb_lbl_freq)

        self.cmb_lbl_pos = QComboBox(self)
        self.cmb_lbl_pos.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        for key, label in LABEL_POSITIONS:
            self.cmb_lbl_pos.addItem(label, key)
        self.cmb_lbl_pos.currentIndexChanged.connect(self._apply_to_item)
        form_labels.addRow("Numbers Position:", self.cmb_lbl_pos)

        self.cmb_unit_pos = QComboBox(self)
        self.cmb_unit_pos.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        for key, label in UNIT_LABEL_POSITIONS:
            self.cmb_unit_pos.addItem(label, key)
        self.cmb_unit_pos.currentIndexChanged.connect(self._apply_to_item)
        form_labels.addRow("Unit Label Position:", self.cmb_unit_pos)

        self.spn_unit_gap = QDoubleSpinBox(self)
        self.spn_unit_gap.setRange(0.0, 50.0)
        self.spn_unit_gap.setSingleStep(0.5)
        self.spn_unit_gap.setSuffix(" mm")
        self.spn_unit_gap.valueChanged.connect(self._apply_to_item)
        form_labels.addRow("Unit Label Gap:", self.spn_unit_gap)

        self.chk_ticks = QCheckBox("Draw division & subdivision tick marks", self)
        self.chk_ticks.toggled.connect(self._apply_to_item)
        form_labels.addRow("", self.chk_ticks)

        self.spn_major_tick = QDoubleSpinBox(self)
        self.spn_major_tick.setRange(0.0, 20.0)
        self.spn_major_tick.setSingleStep(0.2)
        self.spn_major_tick.setSuffix(" mm")
        self.spn_major_tick.valueChanged.connect(self._apply_to_item)
        form_labels.addRow("Major Tick Height:", self.spn_major_tick)

        self.spn_minor_tick = QDoubleSpinBox(self)
        self.spn_minor_tick.setRange(0.0, 20.0)
        self.spn_minor_tick.setSingleStep(0.2)
        self.spn_minor_tick.setSuffix(" mm")
        self.spn_minor_tick.valueChanged.connect(self._apply_to_item)
        form_labels.addRow("Subdivision Tick Height:", self.spn_minor_tick)

        self.spn_lbl_space = QDoubleSpinBox(self)
        self.spn_lbl_space.setRange(0.0, 20.0)
        self.spn_lbl_space.setSingleStep(0.2)
        self.spn_lbl_space.setSuffix(" mm")
        self.spn_lbl_space.valueChanged.connect(self._apply_to_item)
        form_labels.addRow("Label Spacing:", self.spn_lbl_space)

        main_layout.addWidget(grp_labels)

        # 5. Appearance (Bar Height, Colors, Line Width, Font)
        grp_style = QgsCollapsibleGroupBoxBasic("Appearance & Colors", self)
        form_style = QFormLayout(grp_style)

        self.spn_bar_height = QDoubleSpinBox(self)
        self.spn_bar_height.setRange(0.5, 50.0)
        self.spn_bar_height.setSingleStep(0.5)
        self.spn_bar_height.setSuffix(" mm")
        self.spn_bar_height.valueChanged.connect(self._apply_to_item)
        form_style.addRow("Bar Height:", self.spn_bar_height)

        self.btn_fill1 = QgsColorButton(self)
        self.btn_fill1.colorChanged.connect(self._apply_to_item)
        form_style.addRow("Primary Fill Color:", self.btn_fill1)

        self.btn_fill2 = QgsColorButton(self)
        self.btn_fill2.colorChanged.connect(self._apply_to_item)
        form_style.addRow("Alternate Fill Color:", self.btn_fill2)

        self.btn_line_color = QgsColorButton(self)
        self.btn_line_color.colorChanged.connect(self._apply_to_item)
        form_style.addRow("Stroke / Tick Color:", self.btn_line_color)

        self.spn_line_width = QDoubleSpinBox(self)
        self.spn_line_width.setRange(0.05, 5.0)
        self.spn_line_width.setSingleStep(0.05)
        self.spn_line_width.setSuffix(" mm")
        self.spn_line_width.valueChanged.connect(self._apply_to_item)
        form_style.addRow("Line Width:", self.spn_line_width)

        self.btn_text_color = QgsColorButton(self)
        self.btn_text_color.colorChanged.connect(self._apply_to_item)
        form_style.addRow("Text Color:", self.btn_text_color)

        self.btn_font = QPushButton("Choose Font...", self)
        self.btn_font.clicked.connect(self._on_choose_font)
        form_style.addRow("Font:", self.btn_font)

        main_layout.addWidget(grp_style)

        # 6. Standard QGIS Layout Item Properties (Position, Size, Rotation, Frame, Background)
        self.item_props_widget = QgsLayoutItemPropertiesWidget(self, self._item)
        main_layout.addWidget(self.item_props_widget)
        main_layout.addStretch(1)

    def setNewItem(self, item) -> bool:
        if not isinstance(item, CustomScaleBarItem):
            return False
        self._item = item
        self.item_props_widget.setItem(item)
        self._load_from_item()
        return True

    def _update_visibility_states(self):
        div_mode = self.cmb_div_mode.currentData()
        is_custom = div_mode == "custom"
        self.cmb_presets.setEnabled(is_custom)
        self.txt_custom_right.setEnabled(is_custom)
        self.spn_equal_val.setEnabled(not is_custom)
        self.spn_equal_cnt.setEnabled(not is_custom)

        left_mode = self.cmb_left_mode.currentData()
        self.spn_left_total.setEnabled(left_mode == "equal")
        self.spn_left_subs.setEnabled(left_mode == "equal")
        self.txt_custom_left.setEnabled(left_mode == "custom")
        self.spn_left_height_ratio.setEnabled(left_mode != "none")
        self.chk_neg_sign.setEnabled(left_mode != "none")

    def _load_from_item(self):
        if self._item is None:
            return
        self._updating = True
        try:
            if self._item.layout():
                self.cmb_map.setCurrentLayout(self._item.layout())
            self.cmb_map.setItem(self._item.linkedMap())

            idx = self.cmb_style.findData(self._item._style)
            if idx >= 0:
                self.cmb_style.setCurrentIndex(idx)

            idx = self.cmb_unit.findData(self._item._unit_key)
            if idx >= 0:
                self.cmb_unit.setCurrentIndex(idx)
            self.txt_unit_label.setText(self._item._unit_label)

            idx = self.cmb_div_mode.findData(self._item._division_mode)
            if idx >= 0:
                self.cmb_div_mode.setCurrentIndex(idx)
            self.txt_custom_right.setText(self._item._custom_right_stops)
            self.spn_equal_val.setValue(self._item._equal_division_value)
            self.spn_equal_cnt.setValue(self._item._equal_division_count)

            idx = self.cmb_left_mode.findData(self._item._left_mode)
            if idx >= 0:
                self.cmb_left_mode.setCurrentIndex(idx)
            self.spn_left_total.setValue(self._item._left_total_value)
            self.spn_left_subs.setValue(self._item._left_subdivisions)
            self.txt_custom_left.setText(self._item._custom_left_stops)
            self.spn_left_height_ratio.setValue(self._item._left_sub_height_ratio)
            self.chk_neg_sign.setChecked(self._item._show_negative_sign)

            idx = self.cmb_lbl_freq.findData(self._item._label_frequency)
            if idx >= 0:
                self.cmb_lbl_freq.setCurrentIndex(idx)
            idx = self.cmb_lbl_pos.findData(self._item._label_position)
            if idx >= 0:
                self.cmb_lbl_pos.setCurrentIndex(idx)
            idx = self.cmb_unit_pos.findData(self._item._unit_label_position)
            if idx >= 0:
                self.cmb_unit_pos.setCurrentIndex(idx)

            self.spn_unit_gap.setValue(self._item._unit_label_gap)
            self.chk_ticks.setChecked(self._item._draw_ticks)
            self.spn_major_tick.setValue(self._item._major_tick_height)
            self.spn_minor_tick.setValue(self._item._minor_tick_height)
            self.spn_lbl_space.setValue(self._item._label_bar_space)

            self.spn_bar_height.setValue(self._item._bar_height)
            self.btn_fill1.setColor(self._item._fill_color1)
            self.btn_fill2.setColor(self._item._fill_color2)
            self.btn_line_color.setColor(self._item._line_color)
            self.spn_line_width.setValue(self._item._line_width)
            self.btn_text_color.setColor(self._item._text_color)
            self._update_font_button_label()

            self._update_visibility_states()
        finally:
            self._updating = False

    def _update_font_button_label(self):
        if self._item:
            f = self._item._font
            self.btn_font.setText(f"{f.family()}, {f.pointSize()} pt")

    def _on_map_changed(self, item):
        if self._updating or self._item is None:
            return
        self._item.setLinkedMap(item)

    def _on_unit_changed(self):
        if self._updating or self._item is None:
            return
        unit_key = self.cmb_unit.currentData()
        for k, label, _, _ in UNIT_DEFINITIONS:
            if k == unit_key:
                self.txt_unit_label.setText(label)
                break
        self._apply_to_item()

    def _on_div_mode_changed(self):
        self._update_visibility_states()
        self._apply_to_item()

    def _on_left_mode_changed(self):
        self._update_visibility_states()
        self._apply_to_item()

    def _on_preset_selected(self):
        if self._updating:
            return
        stops = self.cmb_presets.currentData()
        if stops:
            self.txt_custom_right.setText(stops)

    def _on_choose_font(self):
        if self._item is None:
            return
        font, ok = QFontDialog.getFont(self._item._font, self, "Select Scale Bar Font")
        if ok:
            self._item._font = font
            self._update_font_button_label()
            self._item.invalidateCache()
            self._item.update()

    def _on_auto_scale_stops(self):
        if self._item is not None:
            self._item._auto_fit_stops_to_map()
            self._load_from_item()
            self._item.adjustSizeToContent()
            self._item.invalidateCache()
            self._item.update()

    def _on_fit_size(self):
        if self._item is not None:
            self._item.adjustSizeToContent()

    def _apply_to_item(self):
        if self._updating or self._item is None:
            return
        self._item._style = self.cmb_style.currentData()
        self._item._unit_key = self.cmb_unit.currentData()
        self._item._unit_label = self.txt_unit_label.text()

        self._item._division_mode = self.cmb_div_mode.currentData()
        self._item._custom_right_stops = self.txt_custom_right.text()
        self._item._equal_division_value = self.spn_equal_val.value()
        self._item._equal_division_count = self.spn_equal_cnt.value()

        self._item._left_mode = self.cmb_left_mode.currentData()
        self._item._left_total_value = self.spn_left_total.value()
        self._item._left_subdivisions = self.spn_left_subs.value()
        self._item._custom_left_stops = self.txt_custom_left.text()
        self._item._left_sub_height_ratio = self.spn_left_height_ratio.value()
        self._item._show_negative_sign = self.chk_neg_sign.isChecked()

        self._item._label_frequency = self.cmb_lbl_freq.currentData()
        self._item._label_position = self.cmb_lbl_pos.currentData()
        self._item._unit_label_position = self.cmb_unit_pos.currentData()
        self._item._unit_label_gap = self.spn_unit_gap.value()
        self._item._draw_ticks = self.chk_ticks.isChecked()
        self._item._major_tick_height = self.spn_major_tick.value()
        self._item._minor_tick_height = self.spn_minor_tick.value()
        self._item._label_bar_space = self.spn_lbl_space.value()

        self._item._bar_height = self.spn_bar_height.value()
        self._item._fill_color1 = self.btn_fill1.color()
        self._item._fill_color2 = self.btn_fill2.color()
        self._item._line_color = self.btn_line_color.color()
        self._item._line_width = self.spn_line_width.value()
        self._item._text_color = self.btn_text_color.color()

        self._item.invalidateCache()
        self._item.update()


class CustomScaleBarGuiMetadata(QgsLayoutItemAbstractGuiMetadata):
    """GUI Registry Metadata connecting CustomScaleBarItem to Print Layout tools & properties panel."""

    def __init__(self):
        super().__init__(CUSTOM_SCALEBAR_TYPE, "Custom Scale Bar")

    def creationIcon(self) -> QIcon:
        icon_path = os.path.join(os.path.dirname(__file__), "icon.svg")
        if os.path.exists(icon_path):
            return QIcon(icon_path)
        return QgsApplication.getThemeIcon("/mActionScaleBar.svg")

    def createItemWidget(self, item):
        widget = CustomScaleBarWidget(None, item)
        if hasattr(sip, "transferto"):
            sip.transferto(widget, None)
        return widget

    def createItem(self, layout):
        item = CustomScaleBarItem(layout)
        if hasattr(sip, "transferto"):
            sip.transferto(item, None)
        return item

    def newItemAddedToLayout(self, item):
        if isinstance(item, CustomScaleBarItem):
            if not item._auto_scaled_once and item.linkedMap() is not None:
                item._auto_fit_stops_to_map()
            item.invalidateCache()
            item.update()
