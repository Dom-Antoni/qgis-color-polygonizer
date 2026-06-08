# QGIS Color to Polygon

PyQGIS scripts to convert colored regions in georeferenced raster maps into polygon layers.

This repository provides two simple QGIS Python scripts for users who need to digitize colored areas from raster maps without manually tracing every polygon.

---

## What it does

`QGIS Color to Polygon` helps you create polygon layers from color-coded raster maps.

It is useful when you have a georeferenced map where regions are already shown as colored areas, but no vector polygon data exists.

The scripts detect raster colors and polygonize the matching areas.

---

## Included scripts

### 1. Click mode

```text
click_color_region_to_polygon_gpkg_fixed.py

This script lets you click on one colored area.

It then:

reads the color at the clicked pixel,
finds the connected area with a similar color,
converts that area into a polygon,
asks for a polygon name,
saves the polygon into a GeoPackage.

Use this when the area you want to extract is mostly connected.

2. Rectangle mode
rectangle_color_regions_to_polygons_gpkg_fixed.py

This script lets you select a color and then drag a rectangle.

It then:

reads the selected color,
searches for matching pixels inside the rectangle,
converts all matching areas into polygons,
asks for a polygon name,
saves the polygons into a GeoPackage.

Use this when the same region is split into several disconnected parts.

Who this is for

This repository may help people working with:

scanned maps
historical maps
thematic maps
geological maps
vegetation maps
land-use maps
administrative maps
region maps
old atlases
color-coded raster maps

It is especially useful when manual polygon tracing would be slow and repetitive.

Requirements

You need:

QGIS
a georeferenced raster layer
Python support inside QGIS
GDAL
NumPy

GDAL and NumPy are usually included in standard QGIS installations.

Basic workflow
1. Load a georeferenced raster map

Open QGIS and load your raster map.

The raster should already be georeferenced, for example as a GeoTIFF.

2. Select the raster layer

Click the raster layer in the QGIS Layers panel.

The scripts use the currently active raster layer.

3. Open the Python Console

In QGIS:

Plugins → Python Console

Then open the script editor.

4. Run one of the scripts

Paste one of the scripts into the QGIS Python editor and run it.

You can use either:

click_color_region_to_polygon_gpkg_fixed.py

or:

rectangle_color_regions_to_polygons_gpkg_fixed.py
Click mode workflow

Use the click script when you want to extract one connected colored area.

1. Run the click script.
2. Click on a colored area in the raster.
3. Enter a name for the polygon.
4. The connected color region is converted to a polygon.
5. The polygon is saved to a GeoPackage.
Rectangle mode workflow

Use the rectangle script when one region is split into several disconnected parts.

1. Run the rectangle script.
2. Click on the color you want to detect.
3. Drag a rectangle over the search area.
4. Enter a name for the polygons.
5. All matching color areas inside the rectangle are polygonized.
6. The polygons are saved to a GeoPackage.
Output

The scripts write the results to a GeoPackage.

Default output file:

color_polygons.gpkg

Default layer name:

color_polygons

The GeoPackage output is safer than a temporary memory layer because the polygons remain saved after closing QGIS.

Important note about GeoPackage behavior

The scripts are designed to avoid losing work.

If the output layer is already loaded in QGIS, new polygons are added to that existing layer.

If the layer was removed from the QGIS project, the fixed scripts do not automatically reload an old deleted layer. Instead, they create a new output file if needed.

This prevents accidentally continuing work in a layer that the user intentionally removed.

Adjusting color sensitivity

The most important setting is:

COLOR_TOLERANCE = 35

This controls how similar a pixel color must be to the selected color.

Lower values

Use lower values when the map has clean, sharp colors.

Example:

COLOR_TOLERANCE = 15

Lower values are stricter and reduce the chance of detecting neighboring colors.

Higher values

Use higher values when the map is noisy, scanned, compressed, or slightly blurred.

Example:

COLOR_TOLERANCE = 50

Higher values detect more pixels, but may also include unwanted areas.

Typical values:

10–25  = strict
25–45  = normal
45–70  = tolerant
Other settings
Pixel connectivity
EIGHT_CONNECTED = True

If this is set to True, diagonally touching pixels count as connected.

This is usually helpful for map regions.

Maximum number of pixels
MAX_PIXELS = 3_000_000

or:

MAX_PIXELS = 5_000_000

This prevents QGIS from freezing if a very large area is selected by accident.

If you work with very large rasters, you may need to increase this value.

Recommended raster preparation

For best results, use a raster with clear color regions.

When georeferencing your map, use:

Nearest neighbour

as the resampling method.

Avoid:

Bilinear
Cubic
Lanczos

These methods blend colors at borders and make color detection harder.

Limitations

The scripts work best with maps that use clear color classes.

They may perform poorly when:

the map has gradients
colors are strongly compressed
the raster is blurry
borders are anti-aliased
text overlaps colored regions
colors are very similar
the map is strongly distorted
the raster is not accurately georeferenced

The scripts are intended as practical digitizing tools, not as a replacement for official GIS datasets.

Always inspect the resulting polygons before using them for analysis.

Possible improvements

Possible future improvements include:

a small QGIS user interface
tolerance adjustment inside QGIS
manual output path selection
automatic removal of tiny polygons
polygon smoothing
filling small holes
merging polygons by name
optional export tools
turning the scripts into a full QGIS plugin
Suggested use cases

Examples:

digitizing historical map regions
extracting color-coded thematic map areas
creating polygons from scanned map images
converting old atlas maps into GIS layers
quickly tracing repeated color regions
extracting disconnected areas with the same color
Short description
PyQGIS scripts to convert colored regions in georeferenced raster maps into polygon layers.
Suggested repository name
qgis-color-to-polygon

Alternative names:

qgis-color-polygonizer
qgis-raster-color-polygonizer
raster-color-to-polygon-qgis
qgis-click-drag-color-polygons
Keywords
qgis
pyqgis
gis
raster
polygon
polygonize
color-segmentation
georeferencing
map-digitization
digitizing
gdal
License

Choose a license before publishing.

A simple option is the MIT License.

Disclaimer

These scripts are experimental tools for raster-based map digitization.

Use the results carefully and always check the generated polygons visually before analysis.
