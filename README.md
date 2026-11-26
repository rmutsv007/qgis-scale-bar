# Custom Scale Bar (QGIS Plugin)

A QGIS plugin that adds a **Custom Scale Bar** item to the Print Layout Designer, overcoming the equal-interval limitation of standard QGIS scale bars.

## Key Features

- **Custom Irregular Main Divisions (Right of 0)**: Define non-uniform distance breaks freely (e.g. `50, 100, 250, 500, 1000`), or use standard equal divisions.
- **Subdivisions Left of 0**: Subdivide the left side of `0` equally into custom subdivision counts or specify custom left stops, with adjustable height ratio and optional negative sign.
- **5 Visual Styles**:
  - Double Alternating Scale Bar
  - Alternating Scale Bar
  - Hollow Scale Bar
  - Stepped Scale Line
  - Scale Line
- **Flexible Number & Tick Placement**: Control label frequency, label position (above/below bar), unit label placement, tick mark heights, colors, and typography directly from the **Item Properties** panel in Print Layout.
- **Auto-Fit to Map Scale**: Automatically adapts initial units and division stops to match the linked map's scale.

## Usage in QGIS Print Layout

1. Open **Project -> Layouts** and open a Print Layout.
2. Click **Add Item -> Add Custom Scale Bar** (or click the **Custom Scale Bar** icon on the toolbar) and drag on the layout page.
3. Select the item and customize divisions, subdivisions, and appearance in the **Item Properties** panel.

## Author & License

- **Author**: Passakorn Poonkerd (`pussakorn8899@gmail.com`)
- **Repository**: https://github.com/rmutsv007/qgis-scale-bar
- **License**: GNU General Public License v2.0 or later (GPL-2.0-or-later)
