# -*- coding: utf-8 -*-
"""
CustomScaleBarItem - Custom QgsLayoutItem for flexible Scale Bars in QGIS.
Supports:
- Equal or Custom Irregular division stops (e.g., 0, 50, 100, 250, 500, 1000)
- Left-of-zero subdivisions (uniform count or custom left stops, with full or half-height option)
- Bar styles:
  * Alternating Scale Bar
  * Double Alternating Scale Bar
  * Hollow Scale Bar
  * Stepped Scale Line
  * Scale Line (Ticks Above / Below / Center)
- Flexible label & tick mark frequency (All divisions & subdivisions, Divisions & endpoints,
  Divisions & first midpoint, Major divisions only)
"""

import os
from qgis.PyQt import sip
from qgis.PyQt.QtCore import Qt, QRectF, QPointF
from qgis.PyQt.QtGui import (
    QColor,
    QFont,
    QFontMetricsF,
    QIcon,
    QPainter,
    QPainterPath,
    QPen,
    QBrush,
)
from qgis.PyQt.QtXml import QDomDocument, QDomElement
from qgis.core import (
    Qgis,
    QgsApplication,
    QgsCsException,
    QgsDistanceArea,
    QgsLayoutItem,
    QgsLayoutItemAbstractMetadata,
    QgsLayoutItemMap,
    QgsLayoutItemRegistry,
    QgsLayoutItemRenderContext,
    QgsLayoutMeasurement,
    QgsLayoutPoint,
    QgsLayoutSize,
    QgsMessageLog,
    QgsPointXY,
    QgsProject,
    QgsReadWriteContext,
    QgsUnitTypes,
)

# Unique item type ID in QgsLayoutItemRegistry
CUSTOM_SCALEBAR_TYPE = QgsLayoutItemRegistry.PluginItem + 2345


UNIT_DEFINITIONS = [
    ("m", "Meters", "m", QgsUnitTypes.DistanceMeters),
    ("km", "Kilometers", "km", QgsUnitTypes.DistanceKilometers),
    ("ft", "Feet", "ft", QgsUnitTypes.DistanceFeet),
    ("yd", "Yards", "yd", QgsUnitTypes.DistanceYards),
    ("mi", "Miles", "mi", QgsUnitTypes.DistanceMiles),
    ("nmi", "Nautical Miles", "NM", QgsUnitTypes.DistanceNauticalMiles),
    ("cm", "Centimeters", "cm", QgsUnitTypes.DistanceCentimeters),
    ("mm", "Millimeters", "mm", QgsUnitTypes.DistanceMillimeters),
]

STYLE_DEFINITIONS = [
    ("alternating", "Alternating Scale Bar"),
    ("double_alternating", "Double Alternating Scale Bar"),
    ("hollow", "Hollow Scale Bar"),
    ("stepped_line", "Stepped Scale Line"),
    ("scale_line", "Scale Line"),
]

DIVISION_MODES = [
    ("custom", "Custom Irregular Stops (e.g. 50, 100, 250, 500)"),
    ("equal", "Equal Divisions"),
]

LEFT_SUBDIVISION_MODES = [
    ("equal", "Subdivide Left Division Equally"),
    ("custom", "Custom Left Stops (e.g. 25, 50, 100)"),
    ("none", "No Left Subdivisions (Start at 0)"),
]

LABEL_FREQUENCIES = [
    ("all", "All divisions and all subdivisions"),
    ("divisions_and_ends", "Divisions and left endpoint only"),
    ("divisions_and_mid", "Divisions, left endpoint, and left midpoint"),
    ("divisions_only", "Right divisions and 0 only"),
    ("ends_and_zero", "End points and 0 only"),
]

LABEL_POSITIONS = [
    ("below", "Below bar"),
    ("above", "Above bar"),
]

UNIT_LABEL_POSITIONS = [
    ("after_labels", "After labels"),
    ("after_bar", "After bar"),
    ("below_bar", "Centered below labels"),
    ("on_last_label", "Appended to last value (e.g. 1,000 m)"),
]


def format_number(val: float) -> str:
    """Format distance numbers cleanly without trailing .0, with thousands separator."""
    if abs(val - round(val)) < 1e-6:
        return f"{int(round(val)):,}"
    elif abs(val * 10 - round(val * 10)) < 1e-5:
        return f"{val:,.1f}"
    elif abs(val * 100 - round(val * 100)) < 1e-4:
        return f"{val:,.2f}"
    return f"{val:g}"


def parse_stops_string(text: str, default_stops=None) -> list:
    """Parse a comma/space separated string of positive numbers into sorted unique stops."""
    if default_stops is None:
        default_stops = [100.0, 250.0, 500.0, 1000.0]
    if not text or not text.strip():
        return list(default_stops)
    raw = text.replace(";", ",").split(",")
    vals = []
    for token in raw:
        token = token.strip()
        if not token:
            continue
        try:
            v = float(token)
            if v > 0:
                vals.append(v)
        except ValueError:
            continue
    if not vals:
        return list(default_stops)
    return sorted(set(vals))


class CustomScaleBarItem(QgsLayoutItem):
    """Custom QgsLayoutItem providing flexible Scale Bars."""

    # Global Python instance store keyed by id(self) / uuid so SIP never garbage-collects
    # the Python subclass wrapper while the C++ QgsLayout still owns the item.
    _LIVE_INSTANCES = {}

    def __init__(self, layout):
        super().__init__(layout)
        CustomScaleBarItem._LIVE_INSTANCES[id(self)] = self
        self.destroyed.connect(
            lambda obj=None, item_id=id(self): CustomScaleBarItem._LIVE_INSTANCES.pop(
                item_id, None
            )
        )

        # Disable graphics item pixmap caching so Qt never displays a blank cached pixmap
        # when selection state changes, and disable opaque white background by default
        # (matching standard QGIS Scale Bar items).
        self.setCacheMode(QgsLayoutItem.NoCache)
        self.setBackgroundEnabled(False)

        self._linked_map = None
        self._linked_map_uuid = ""
        self._auto_scaled_once = False

        # Style & Bar Geometry
        self._style = "double_alternating"
        self._bar_height = 3.5  # mm
        self._left_sub_height_ratio = 1.0  # 1.0 = full height, 0.5 = half height

        # Units
        self._unit_key = "m"
        self._unit_label = "Meters"

        # Right of 0 (Main Divisions)
        self._division_mode = "custom"  # "custom" or "equal"
        self._custom_right_stops = "100, 250, 500, 1000"
        self._equal_division_value = 250.0
        self._equal_division_count = 4

        # Left of 0 (Subdivisions before zero)
        self._left_mode = "equal"  # "equal", "custom", or "none"
        self._left_total_value = 100.0  # Distance to the left of 0
        self._left_subdivisions = 4  # Number of subdivisions on the left of 0
        self._custom_left_stops = "25, 50, 100"
        self._show_negative_sign = False

        # Ticks & Labels
        self._label_frequency = "divisions_and_mid"
        self._label_position = "below"  # "below" or "above"
        self._unit_label_position = "after_labels"
        self._unit_label_gap = 2.0  # mm
        self._label_bar_space = 1.8  # mm
        self._major_tick_height = 2.2  # mm
        self._minor_tick_height = 1.3  # mm
        self._draw_ticks = True

        # Colors & Stroke
        self._fill_color1 = QColor(30, 30, 30)
        self._fill_color2 = QColor(255, 255, 255)
        self._line_color = QColor(30, 30, 30)
        self._line_width = 0.35  # mm
        self._text_color = QColor(20, 20, 20)
        self._font = QFont("Arial", 9)

        # Set default size in layout units (mm)
        self.attemptResize(QgsLayoutSize(110.0, 18.0, QgsUnitTypes.LayoutMillimeters))

        # Auto-link to reference map or first map in layout if available
        if layout is not None:
            ref_map = layout.referenceMap()
            if ref_map is not None:
                self.setLinkedMap(ref_map, auto_fit_stops=True)
            else:
                for item in layout.items():
                    if isinstance(item, QgsLayoutItemMap):
                        self.setLinkedMap(item, auto_fit_stops=True)
                        break

    def type(self) -> int:
        return CUSTOM_SCALEBAR_TYPE

    def icon(self) -> QIcon:
        icon_path = os.path.join(os.path.dirname(__file__), "icon.svg")
        if os.path.exists(icon_path):
            return QIcon(icon_path)
        return QgsApplication.getThemeIcon("/mActionScaleBar.svg")

    def displayName(self) -> str:
        if self.id():
            return self.id()
        return "Custom Scale Bar"

    # ---- Linked Map Management ----

    def linkedMap(self):
        return self._linked_map

    def setLinkedMap(self, map_item, auto_fit_stops: bool = False):
        if self._linked_map is map_item and not auto_fit_stops:
            return
        if self._linked_map is not None and not sip.isdeleted(self._linked_map):
            try:
                self._linked_map.extentChanged.disconnect(self._on_map_changed)
                self._linked_map.crsChanged.disconnect(self._on_map_changed)
            except (TypeError, RuntimeError) as exc:
                QgsMessageLog.logMessage(
                    f"Map signal disconnect info: {exc}",
                    "Custom Scale Bar",
                    Qgis.Info,
                )
        self._linked_map = map_item
        if map_item is not None and not sip.isdeleted(map_item):
            self._linked_map_uuid = map_item.uuid()
            map_item.extentChanged.connect(self._on_map_changed)
            map_item.crsChanged.connect(self._on_map_changed)
            if auto_fit_stops and not self._auto_scaled_once:
                self._auto_fit_stops_to_map()
        else:
            self._linked_map_uuid = ""
        self.invalidateCache()
        self.update()

    def _auto_fit_stops_to_map(self):
        """Automatically choose sensible initial units and irregular stops if default 1000m is way too small or huge."""
        if self._linked_map is None:
            return
        mm_for_1000m = self.distanceToLayoutMillimeters(1000.0, "m")
        if mm_for_1000m <= 0:
            return
        # If 1000m is already between 15mm and 180mm on the page, keep the default 100, 250, 500, 1000m
        if 15.0 <= mm_for_1000m <= 180.0:
            self._auto_scaled_once = True
            return

        import math
        # Target ~70 mm for max right stop
        target_meters = 1000.0 * (70.0 / mm_for_1000m)
        if target_meters >= 2000.0:
            self._unit_key = "km"
            self._unit_label = "Kilometers"
            target_val = target_meters / 1000.0
        else:
            self._unit_key = "m"
            self._unit_label = "Meters"
            target_val = target_meters

        if target_val <= 0:
            return
        exp = math.floor(math.log10(target_val))
        base = 10.0 ** exp
        norm = target_val / base
        if norm < 1.5:
            max_stop = 1.0 * base
        elif norm < 3.5:
            max_stop = 2.0 * base
        elif norm < 7.5:
            max_stop = 5.0 * base
        else:
            max_stop = 10.0 * base

        s1 = max_stop * 0.1
        s2 = max_stop * 0.25
        s3 = max_stop * 0.5
        s4 = max_stop
        self._custom_right_stops = (
            f"{format_number(s1).replace(',', '')}, "
            f"{format_number(s2).replace(',', '')}, "
            f"{format_number(s3).replace(',', '')}, "
            f"{format_number(s4).replace(',', '')}"
        )
        self._equal_division_value = s2
        self._left_total_value = s1
        self._custom_left_stops = (
            f"{format_number(s1 * 0.25).replace(',', '')}, "
            f"{format_number(s1 * 0.5).replace(',', '')}, "
            f"{format_number(s1).replace(',', '')}"
        )
        self._auto_scaled_once = True

    def _on_map_changed(self):
        self.invalidateCache()
        self.update()

    # ---- Unit Conversion Helper ----

    def _get_qgis_distance_unit(self, unit_key: str):
        for k, _, _, q_unit in UNIT_DEFINITIONS:
            if k == unit_key:
                return q_unit
        return QgsUnitTypes.DistanceMeters

    def distanceToLayoutMillimeters(self, distance_val: float, unit_key: str = None) -> float:
        """Convert a real-world ground distance in `unit_key` to layout millimeters."""
        if unit_key is None:
            unit_key = self._unit_key
        q_unit = self._get_qgis_distance_unit(unit_key)

        map_item = self._linked_map
        if map_item is None and self.layout() is not None:
            map_item = self.layout().referenceMap()

        if map_item is not None:
            extent = map_item.extent()
            if not extent.isEmpty() and extent.width() > 0:
                da = QgsDistanceArea()
                crs = map_item.crs()
                da.setSourceCrs(crs, QgsProject.instance().transformContext())
                ellipsoid = QgsProject.instance().ellipsoid()
                if ellipsoid:
                    da.setEllipsoid(ellipsoid)
                mid_y = extent.center().y()
                p1 = QgsPointXY(extent.xMinimum(), mid_y)
                p2 = QgsPointXY(extent.xMaximum(), mid_y)
                try:
                    measured = da.measureLine(p1, p2)
                    measured_unit = da.lengthUnits()
                    factor = QgsUnitTypes.fromUnitToUnitFactor(measured_unit, q_unit)
                    width_in_target_unit = measured * factor
                    if width_in_target_unit > 0:
                        # Convert map item width to mm
                        map_width_layout = map_item.rect().width()
                        if self.layout() is not None:
                            conv = self.layout().convertFromLayoutUnits(
                                map_width_layout, QgsUnitTypes.LayoutMillimeters
                            )
                            map_width_mm = conv.length()
                        else:
                            map_width_mm = map_width_layout
                        return distance_val * (map_width_mm / width_in_target_unit)
                except QgsCsException as exc:
                    QgsMessageLog.logMessage(
                        f"Distance measurement fallback: {exc}",
                        "Custom Scale Bar",
                        Qgis.Info,
                    )

                # Fallback to scale denominator
                scale = map_item.scale()
                if scale > 0:
                    factor_to_mm = QgsUnitTypes.fromUnitToUnitFactor(
                        q_unit, QgsUnitTypes.DistanceMillimeters
                    )
                    return (distance_val * factor_to_mm) / scale

        # Default fallback if no map is linked (assume 1:10,000 scale for preview)
        factor_to_mm = QgsUnitTypes.fromUnitToUnitFactor(
            q_unit, QgsUnitTypes.DistanceMillimeters
        )
        return (distance_val * factor_to_mm) / 10000.0

    # ---- Division & Subdivision Stops Computation ----

    def getRightStops(self) -> list:
        """Return sorted list of positive stops to the right of 0 (excluding 0)."""
        if self._division_mode == "equal":
            step = max(1e-6, float(self._equal_division_value))
            count = max(1, int(self._equal_division_count))
            return [step * i for i in range(1, count + 1)]
        else:
            return parse_stops_string(
                self._custom_right_stops, [100.0, 250.0, 500.0, 1000.0]
            )

    def getLeftStops(self) -> list:
        """Return sorted list of positive distances to the left of 0 (excluding 0)."""
        if self._left_mode == "none":
            return []
        elif self._left_mode == "custom":
            return parse_stops_string(self._custom_left_stops, [25.0, 50.0, 100.0])
        else:
            total = max(0.0, float(self._left_total_value))
            count = max(1, int(self._left_subdivisions))
            if total <= 0:
                return []
            step = total / count
            return [step * i for i in range(1, count + 1)]

    def _should_label_left_stop(self, idx: int, total_count: int) -> bool:
        """Determine whether left subdivision stop `idx` (1-based from 0 to left end) gets a label."""
        freq = self._label_frequency
        if freq == "all":
            return True
        if freq == "divisions_and_ends":
            return idx == total_count
        if freq == "divisions_and_mid":
            if idx == total_count:
                return True
            if total_count >= 2 and total_count % 2 == 0 and idx == total_count // 2:
                return True
            return False
        if freq == "divisions_only":
            return False
        if freq == "ends_and_zero":
            return idx == total_count
        return idx == total_count

    def _should_label_right_stop(self, idx: int, total_count: int) -> bool:
        """Determine whether right division stop `idx` (1-based from 0 to right end) gets a label."""
        freq = self._label_frequency
        if freq == "ends_and_zero":
            return idx == total_count
        return True

    # ---- Size Adjustment Helper ----

    def adjustSizeToContent(self):
        """Automatically resize the item bounding box to fit the current scale bar & labels."""
        right_stops = self.getRightStops()
        left_stops = self.getLeftStops()
        max_right_val = right_stops[-1] if right_stops else 100.0
        max_left_val = left_stops[-1] if left_stops else 0.0

        bar_mm = self.distanceToLayoutMillimeters(max_left_val + max_right_val)
        # Estimate extra horizontal space for labels & unit text
        extra_w = 35.0
        extra_h = max(16.0, self._bar_height + 14.0)
        self.attemptResize(
            QgsLayoutSize(max(30.0, bar_mm + extra_w), extra_h, QgsUnitTypes.LayoutMillimeters)
        )
        self.invalidateCache()
        self.update()

    # ---- Rendering ----

    def draw(self, context: QgsLayoutItemRenderContext):
        render_context = context.renderContext()
        painter = render_context.painter()
        if painter is None:
            return

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)

        def mm_to_px(mm_val: float) -> float:
            return render_context.convertToPainterUnits(
                mm_val, QgsUnitTypes.RenderMillimeters
            )

        right_stops = self.getRightStops()
        left_stops = self.getLeftStops()

        max_left_val = left_stops[-1] if left_stops else 0.0
        max_right_val = right_stops[-1] if right_stops else 100.0

        left_width_mm = self.distanceToLayoutMillimeters(max_left_val) if max_left_val > 0 else 0.0
        right_width_mm = self.distanceToLayoutMillimeters(max_right_val) if max_right_val > 0 else 10.0

        # Prepare font in painter pixels
        font_px = QFont(self._font)
        pt_size = self._font.pointSizeF()
        if pt_size <= 0:
            pt_size = 9.0
        px_font_size = render_context.convertToPainterUnits(
            pt_size, QgsUnitTypes.RenderPoints
        )
        font_px.setPixelSize(max(1, int(round(px_font_size))))
        painter.setFont(font_px)
        fm = QFontMetricsF(font_px)

        text_h_px = fm.height()
        ascent_px = fm.ascent()

        # Left margin so the leftmost label is not clipped
        first_left_text = ""
        if left_stops:
            prefix = "-" if self._show_negative_sign else ""
            first_left_text = f"{prefix}{format_number(left_stops[-1])}"
        else:
            first_left_text = "0"
        left_pad_px = max(mm_to_px(2.5), fm.horizontalAdvance(first_left_text) * 0.55 + mm_to_px(1.5))

        x_zero_px = left_pad_px + mm_to_px(left_width_mm)
        bar_h_px = mm_to_px(self._bar_height)
        tick_major_px = mm_to_px(self._major_tick_height) if self._draw_ticks else 0.0
        tick_minor_px = mm_to_px(self._minor_tick_height) if self._draw_ticks else 0.0
        label_space_px = mm_to_px(self._label_bar_space)

        # Vertical layout in painter coordinates
        if self._label_position == "above":
            label_y_top = mm_to_px(1.5)
            bar_top_px = label_y_top + text_h_px + label_space_px + tick_major_px
        else:
            bar_top_px = mm_to_px(2.0) + (tick_major_px if self._style in ("stepped_line", "scale_line") else 0.0)
            label_y_top = bar_top_px + bar_h_px + tick_major_px + label_space_px

        bar_bottom_px = bar_top_px + bar_h_px
        bar_mid_y_px = bar_top_px + bar_h_px * 0.5

        # Build ordered segments from left to 0, then 0 to right
        # Each segment: (x0_px, x1_px, seg_index, is_left_subdivision)
        segments = []
        # Left subdivisions (drawn from furthest left toward 0, or 0 toward left)
        if left_stops:
            # boundaries in distance left of 0: [max_left, ..., stop_1, 0]
            left_bounds = list(reversed(left_stops)) + [0.0]
            for i in range(len(left_bounds) - 1):
                d_left_start = left_bounds[i]
                d_left_end = left_bounds[i + 1]
                x0 = x_zero_px - mm_to_px(self.distanceToLayoutMillimeters(d_left_start))
                x1 = x_zero_px - mm_to_px(self.distanceToLayoutMillimeters(d_left_end))
                segments.append((x0, x1, i, True))

        # Right main divisions
        right_bounds = [0.0] + list(right_stops)
        for i in range(len(right_bounds) - 1):
            d_start = right_bounds[i]
            d_end = right_bounds[i + 1]
            x0 = x_zero_px + mm_to_px(self.distanceToLayoutMillimeters(d_start))
            x1 = x_zero_px + mm_to_px(self.distanceToLayoutMillimeters(d_end))
            segments.append((x0, x1, i, False))

        # Setup pens and brushes
        line_w_px = max(1.0, mm_to_px(self._line_width))
        pen = QPen(self._line_color, line_w_px, Qt.SolidLine, Qt.SquareCap, Qt.MiterJoin)
        brush1 = QBrush(self._fill_color1)
        brush2 = QBrush(self._fill_color2)

        painter.setPen(pen)

        # Draw segments according to selected bar style
        for idx, (x0, x1, seg_i, is_left) in enumerate(segments):
            w = max(0.0, x1 - x0)
            # Determine segment height (supports half-height left subdivisions if configured)
            seg_h = bar_h_px * (self._left_sub_height_ratio if is_left else 1.0)
            seg_top = bar_bottom_px - seg_h

            # Alternate parity relative to 0 so 0 boundary always contrasts cleanly
            if is_left:
                # Count index outwards from 0
                dist_idx_from_zero = (len(left_stops) - 1 - seg_i)
                even = (dist_idx_from_zero % 2 == 0)
            else:
                even = (seg_i % 2 == 0)

            if self._style == "alternating":
                painter.setBrush(brush1 if even else brush2)
                painter.drawRect(QRectF(x0, seg_top, w, seg_h))

            elif self._style == "double_alternating":
                half_h = seg_h * 0.5
                # Top row
                painter.setBrush(brush1 if even else brush2)
                painter.drawRect(QRectF(x0, seg_top, w, half_h))
                # Bottom row (inverted)
                painter.setBrush(brush2 if even else brush1)
                painter.drawRect(QRectF(x0, seg_top + half_h, w, half_h))

            elif self._style == "hollow":
                painter.setBrush(brush2)
                painter.drawRect(QRectF(x0, seg_top, w, seg_h))
                if even:
                    # Inner center line for alternating hollow look or pure hollow
                    pass

            elif self._style == "stepped_line":
                painter.setBrush(Qt.NoBrush)
                y_level = seg_top if even else bar_bottom_px
                painter.drawLine(QPointF(x0, y_level), QPointF(x1, y_level))
                # Vertical step connectors
                painter.drawLine(QPointF(x0, seg_top), QPointF(x0, bar_bottom_px))
                if idx == len(segments) - 1:
                    painter.drawLine(QPointF(x1, seg_top), QPointF(x1, bar_bottom_px))

            elif self._style == "scale_line":
                painter.setBrush(Qt.NoBrush)
                painter.drawLine(QPointF(x0, bar_bottom_px), QPointF(x1, bar_bottom_px))

        # Collect tick positions and label specs
        # Each tick entry: (x_px, is_major, label_str_or_None)
        tick_entries = []

        # Left stops (1-based index from 0 outwards)
        total_left = len(left_stops)
        for i, d_val in enumerate(left_stops, start=1):
            x_pos = x_zero_px - mm_to_px(self.distanceToLayoutMillimeters(d_val))
            is_end = (i == total_left)
            should_lbl = self._should_label_left_stop(i, total_left)
            lbl = None
            if should_lbl:
                prefix = "-" if self._show_negative_sign else ""
                lbl = f"{prefix}{format_number(d_val)}"
            tick_entries.append((x_pos, is_end or should_lbl, lbl))

        # Zero stop
        tick_entries.append((x_zero_px, True, "0"))

        # Right stops
        total_right = len(right_stops)
        for i, d_val in enumerate(right_stops, start=1):
            x_pos = x_zero_px + mm_to_px(self.distanceToLayoutMillimeters(d_val))
            should_lbl = self._should_label_right_stop(i, total_right)
            lbl = None
            if should_lbl:
                lbl = format_number(d_val)
                if i == total_right and self._unit_label_position == "on_last_label" and self._unit_label:
                    lbl = f"{lbl} {self._unit_label}"
            tick_entries.append((x_pos, True, lbl))

        # Draw tick marks and labels
        max_label_right_px = x_zero_px + mm_to_px(right_width_mm)
        last_tick_x_px = x_zero_px + mm_to_px(right_width_mm)

        for x_pos, is_major, lbl_text in tick_entries:
            if self._draw_ticks:
                t_len = tick_major_px if is_major else tick_minor_px
                painter.setPen(pen)
                if self._label_position == "above":
                    painter.drawLine(
                        QPointF(x_pos, bar_top_px),
                        QPointF(x_pos, bar_top_px - t_len),
                    )
                else:
                    if self._style == "scale_line":
                        painter.drawLine(
                            QPointF(x_pos, bar_bottom_px - bar_h_px),
                            QPointF(x_pos, bar_bottom_px + t_len),
                        )
                    else:
                        painter.drawLine(
                            QPointF(x_pos, bar_bottom_px),
                            QPointF(x_pos, bar_bottom_px + t_len),
                        )

            if lbl_text is not None:
                painter.setPen(QPen(self._text_color))
                tw = fm.horizontalAdvance(lbl_text)
                tx = x_pos - tw * 0.5
                ty = label_y_top + ascent_px
                painter.drawText(QPointF(tx, ty), lbl_text)
                max_label_right_px = max(max_label_right_px, tx + tw)

        # Draw Primary Unit Label
        if self._unit_label and self._unit_label_position != "on_last_label":
            painter.setPen(QPen(self._text_color))
            gap_px = mm_to_px(self._unit_label_gap)
            if self._unit_label_position == "after_labels":
                ux = max_label_right_px + gap_px
                uy = label_y_top + ascent_px
                painter.drawText(QPointF(ux, uy), self._unit_label)
            elif self._unit_label_position == "after_bar":
                ux = last_tick_x_px + gap_px
                uy = bar_mid_y_px + (ascent_px - fm.descent()) * 0.5
                painter.drawText(QPointF(ux, uy), self._unit_label)
            elif self._unit_label_position == "below_bar":
                first_x = (
                    x_zero_px - mm_to_px(left_width_mm) if left_stops else x_zero_px
                )
                center_x = 0.5 * (first_x + last_tick_x_px)
                uw = fm.horizontalAdvance(self._unit_label)
                ux = center_x - uw * 0.5
                uy = label_y_top + text_h_px + mm_to_px(1.0) + ascent_px
                painter.drawText(QPointF(ux, uy), self._unit_label)

        painter.restore()

    # ---- XML Persistence ----

    def writePropertiesToElement(
        self, element: QDomElement, document: QDomDocument, context: QgsReadWriteContext
    ) -> bool:
        element.setAttribute(
            "linkedMapUuid",
            self._linked_map.uuid() if self._linked_map else self._linked_map_uuid,
        )
        element.setAttribute("style", self._style)
        element.setAttribute("barHeight", str(self._bar_height))
        element.setAttribute("leftSubHeightRatio", str(self._left_sub_height_ratio))
        element.setAttribute("unitKey", self._unit_key)
        element.setAttribute("unitLabel", self._unit_label)

        element.setAttribute("divisionMode", self._division_mode)
        element.setAttribute("customRightStops", self._custom_right_stops)
        element.setAttribute("equalDivisionValue", str(self._equal_division_value))
        element.setAttribute("equalDivisionCount", str(self._equal_division_count))

        element.setAttribute("leftMode", self._left_mode)
        element.setAttribute("leftTotalValue", str(self._left_total_value))
        element.setAttribute("leftSubdivisions", str(self._left_subdivisions))
        element.setAttribute("customLeftStops", self._custom_left_stops)
        element.setAttribute("showNegativeSign", "1" if self._show_negative_sign else "0")

        element.setAttribute("labelFrequency", self._label_frequency)
        element.setAttribute("labelPosition", self._label_position)
        element.setAttribute("unitLabelPosition", self._unit_label_position)
        element.setAttribute("unitLabelGap", str(self._unit_label_gap))
        element.setAttribute("labelBarSpace", str(self._label_bar_space))
        element.setAttribute("majorTickHeight", str(self._major_tick_height))
        element.setAttribute("minorTickHeight", str(self._minor_tick_height))
        element.setAttribute("drawTicks", "1" if self._draw_ticks else "0")

        element.setAttribute("fillColor1", self._fill_color1.name(QColor.HexArgb))
        element.setAttribute("fillColor2", self._fill_color2.name(QColor.HexArgb))
        element.setAttribute("lineColor", self._line_color.name(QColor.HexArgb))
        element.setAttribute("lineWidth", str(self._line_width))
        element.setAttribute("textColor", self._text_color.name(QColor.HexArgb))
        element.setAttribute("font", self._font.toString())
        return True

    def readPropertiesFromElement(
        self, element: QDomElement, document: QDomDocument, context: QgsReadWriteContext
    ) -> bool:
        self._linked_map_uuid = element.attribute("linkedMapUuid", "")
        self._style = element.attribute("style", self._style)
        self._bar_height = float(element.attribute("barHeight", str(self._bar_height)))
        self._left_sub_height_ratio = float(
            element.attribute("leftSubHeightRatio", str(self._left_sub_height_ratio))
        )
        self._unit_key = element.attribute("unitKey", self._unit_key)
        self._unit_label = element.attribute("unitLabel", self._unit_label)

        self._division_mode = element.attribute("divisionMode", self._division_mode)
        self._custom_right_stops = element.attribute(
            "customRightStops", self._custom_right_stops
        )
        self._equal_division_value = float(
            element.attribute("equalDivisionValue", str(self._equal_division_value))
        )
        self._equal_division_count = int(
            element.attribute("equalDivisionCount", str(self._equal_division_count))
        )

        self._left_mode = element.attribute("leftMode", self._left_mode)
        self._left_total_value = float(
            element.attribute("leftTotalValue", str(self._left_total_value))
        )
        self._left_subdivisions = int(
            element.attribute("leftSubdivisions", str(self._left_subdivisions))
        )
        self._custom_left_stops = element.attribute(
            "customLeftStops", self._custom_left_stops
        )
        self._show_negative_sign = element.attribute("showNegativeSign", "0") == "1"

        self._label_frequency = element.attribute("labelFrequency", self._label_frequency)
        self._label_position = element.attribute("labelPosition", self._label_position)
        self._unit_label_position = element.attribute(
            "unitLabelPosition", self._unit_label_position
        )
        self._unit_label_gap = float(
            element.attribute("unitLabelGap", str(self._unit_label_gap))
        )
        self._label_bar_space = float(
            element.attribute("labelBarSpace", str(self._label_bar_space))
        )
        self._major_tick_height = float(
            element.attribute("majorTickHeight", str(self._major_tick_height))
        )
        self._minor_tick_height = float(
            element.attribute("minorTickHeight", str(self._minor_tick_height))
        )
        self._draw_ticks = element.attribute("drawTicks", "1") == "1"

        c1 = QColor(element.attribute("fillColor1", "#1e1e1e"))
        if c1.isValid():
            self._fill_color1 = c1
        c2 = QColor(element.attribute("fillColor2", "#ffffff"))
        if c2.isValid():
            self._fill_color2 = c2
        lc = QColor(element.attribute("lineColor", "#1e1e1e"))
        if lc.isValid():
            self._line_color = lc
        self._line_width = float(element.attribute("lineWidth", str(self._line_width)))
        tc = QColor(element.attribute("textColor", "#141414"))
        if tc.isValid():
            self._text_color = tc

        font_str = element.attribute("font", "")
        if font_str:
            f = QFont()
            if f.fromString(font_str):
                self._font = f
        return True

    def finalizeRestoreFromXml(self):
        super().finalizeRestoreFromXml()
        if self.layout() is not None and self._linked_map_uuid:
            item = self.layout().itemByUuid(self._linked_map_uuid)
            if isinstance(item, QgsLayoutItemMap):
                self.setLinkedMap(item)


class CustomScaleBarMetadata(QgsLayoutItemAbstractMetadata):
    """Core Layout Item Registry Metadata for CustomScaleBarItem."""

    def __init__(self):
        super().__init__(CUSTOM_SCALEBAR_TYPE, "Custom Scale Bar", "Custom Scale Bars")

    def createItem(self, layout):
        item = CustomScaleBarItem(layout)
        if hasattr(sip, "transferto"):
            sip.transferto(item, None)
        return item
