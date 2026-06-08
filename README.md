# QGIS Color to Polygon

Convert colored areas in georeferenced raster maps into polygon layers in QGIS.

This repository contains two PyQGIS scripts for digitizing color-coded raster maps without manually tracing every polygon.

## Scripts

### click_color_region_to_polygon_gpkg_fixed.py

Click on a colored area in a georeferenced raster.

The script detects the connected area with a similar color and saves it as a polygon.

Best for:

- one connected colored area
- simple region extraction
- quick manual digitizing

### rectangle_color_regions_to_polygons_gpkg_fixed.py

Click on a color, then drag a rectangle over the area to search.

The script detects all matching color areas inside the rectangle and saves them as polygons.

Best for:

- regions split into multiple parts
- repeated colors within a defined area
- faster digitizing of separated shapes

## Use cases

This can help with digitizing:

- scanned maps
- historical maps
- thematic maps
- land-use maps
- geological maps
- vegetation maps
- administrative maps
- color-coded georeferenced raster maps

## Requirements

- QGIS
- a georeferenced raster layer
- Python support inside QGIS
- GDAL and NumPy, usually included with QGIS

## Basic workflow

1. Load your georeferenced raster map in QGIS.
2. Select the raster layer in the Layers panel.
3. Open the QGIS Python Console.
4. Open the script editor.
5. Paste and run one of the scripts.
6. Create polygons by clicking or dragging.
7. The output is saved to a GeoPackage.

## Output

The scripts save polygons to a GeoPackage named:

**color_polygons.gpkg**

The default layer name is:

**color_polygons**

If the output layer is already loaded in QGIS, new polygons are added to it.

## Important setting

The main setting to adjust is:

**COLOR_TOLERANCE = 35**

Lower values are stricter.

Example:

**COLOR_TOLERANCE = 15**

Higher values detect more color variation.

Example:

**COLOR_TOLERANCE = 50**

Useful range:

- **10-25**: strict
- **25-45**: normal
- **45-70**: tolerant

## Recommended raster preparation

When georeferencing your raster, use:

**Nearest neighbour**

This keeps colors sharper.

Avoid bilinear, cubic, or Lanczos resampling if you want clean color detection.

## Limitations

The scripts work best with clear, solid colors.

They may struggle with:

- blurry scans
- JPEG artifacts
- gradients
- anti-aliased borders
- text over colored regions
- very similar colors
- poorly georeferenced maps

Always check the generated polygons before using them for analysis.

## Possible improvements

Future improvements could include:

- a QGIS plugin interface
- tolerance settings in a dialog
- automatic removal of tiny polygons
- polygon smoothing
- filling small holes
- merging polygons by name
- custom output file selection

## License

MIT.

## Disclaimer

These scripts are practical digitizing tools, not a replacement for official GIS datasets.
