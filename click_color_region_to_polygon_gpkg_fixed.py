from qgis.PyQt.QtWidgets import QInputDialog, QMessageBox
from qgis.PyQt.QtCore import Qt, QVariant

from qgis.core import (
    QgsProject,
    QgsVectorLayer,
    QgsFeature,
    QgsField,
    QgsCoordinateTransform,
    QgsMapLayerType,
    QgsVectorFileWriter,
)

from qgis.gui import QgsMapToolEmitPoint

from osgeo import gdal
import numpy as np
from collections import deque
import tempfile
import os
import processing


# ============================================================
# SETTINGS
# ============================================================

COLOR_TOLERANCE = 35
EIGHT_CONNECTED = True
MAX_PIXELS = 3_000_000

OUTPUT_LAYER_NAME = "color_polygons"
OUTPUT_GPKG_NAME = "color_polygons.gpkg"

# Important behavior:
# False = if you remove the layer from QGIS, the script will NOT silently reload
#         the old GeoPackage. It will create a new file with a suffix instead.
# True  = if a GeoPackage already exists, the script loads it and appends to it.
REUSE_EXISTING_FILE_WHEN_LAYER_NOT_LOADED = False


# ============================================================
# GENERAL HELPERS
# ============================================================

def project_output_path():
    project_file = QgsProject.instance().fileName()

    if project_file:
        base_dir = os.path.dirname(project_file)
    else:
        base_dir = os.path.expanduser("~")

    return os.path.join(base_dir, OUTPUT_GPKG_NAME)


def unique_path(path):
    if not os.path.exists(path):
        return path

    root, ext = os.path.splitext(path)
    counter = 2

    while True:
        candidate = f"{root}_{counter}{ext}"
        if not os.path.exists(candidate):
            return candidate
        counter += 1


def get_active_raster_layer():
    layer = iface.activeLayer()

    if layer is not None and layer.type() == QgsMapLayerType.RasterLayer:
        return layer

    raster_layers = [
        lyr for lyr in QgsProject.instance().mapLayers().values()
        if lyr.type() == QgsMapLayerType.RasterLayer
    ]

    if len(raster_layers) == 1:
        return raster_layers[0]

    raise Exception(
        "Selected layer is not a raster layer. Please select your georeferenced raster layer first."
    )


def left_mouse_button():
    try:
        return Qt.MouseButton.LeftButton
    except AttributeError:
        return Qt.LeftButton


raster_layer = get_active_raster_layer()


# ============================================================
# OUTPUT GEOPACKAGE LAYER
# ============================================================

def required_fields():
    return [
        ("name", QVariant.String),
        ("r", QVariant.Int),
        ("g", QVariant.Int),
        ("b", QVariant.Int),
        ("tolerance", QVariant.Int),
        ("pixels", QVariant.Int),
        ("mode", QVariant.String),
    ]


def ensure_fields(layer):
    existing_names = [field.name() for field in layer.fields()]
    fields_to_add = []

    for field_name, field_type in required_fields():
        if field_name not in existing_names:
            fields_to_add.append(QgsField(field_name, field_type))

    if fields_to_add:
        layer.startEditing()
        layer.dataProvider().addAttributes(fields_to_add)
        layer.updateFields()
        layer.commitChanges()


def create_empty_geopackage_layer(path):
    crs_authid = raster_layer.crs().authid()

    memory_layer = QgsVectorLayer(
        f"Polygon?crs={crs_authid}",
        OUTPUT_LAYER_NAME,
        "memory"
    )

    provider = memory_layer.dataProvider()
    provider.addAttributes([QgsField(name, typ) for name, typ in required_fields()])
    memory_layer.updateFields()

    options = QgsVectorFileWriter.SaveVectorOptions()
    options.driverName = "GPKG"
    options.layerName = OUTPUT_LAYER_NAME
    options.actionOnExistingFile = QgsVectorFileWriter.CreateOrOverwriteFile

    result = QgsVectorFileWriter.writeAsVectorFormatV3(
        memory_layer,
        path,
        QgsProject.instance().transformContext(),
        options
    )

    error_code = result[0]
    error_message = result[1] if len(result) > 1 else ""

    if error_code != QgsVectorFileWriter.NoError:
        raise Exception(f"Could not create GeoPackage: {error_message}")

    layer = QgsVectorLayer(
        f"{path}|layername={OUTPUT_LAYER_NAME}",
        OUTPUT_LAYER_NAME,
        "ogr"
    )

    if not layer.isValid():
        raise Exception("GeoPackage was created, but the output layer could not be loaded.")

    QgsProject.instance().addMapLayer(layer)
    return layer


def load_geopackage_layer(path):
    layer = QgsVectorLayer(
        f"{path}|layername={OUTPUT_LAYER_NAME}",
        OUTPUT_LAYER_NAME,
        "ogr"
    )

    if not layer.isValid():
        raise Exception("Existing GeoPackage found, but the output layer could not be loaded.")

    ensure_fields(layer)
    QgsProject.instance().addMapLayer(layer)
    return layer


def get_or_create_result_layer():
    existing = QgsProject.instance().mapLayersByName(OUTPUT_LAYER_NAME)

    if existing:
        layer = existing[0]
        ensure_fields(layer)
        return layer

    output_path = project_output_path()

    if os.path.exists(output_path) and REUSE_EXISTING_FILE_WHEN_LAYER_NOT_LOADED:
        return load_geopackage_layer(output_path)

    if os.path.exists(output_path) and not REUSE_EXISTING_FILE_WHEN_LAYER_NOT_LOADED:
        output_path = unique_path(output_path)

    return create_empty_geopackage_layer(output_path)


result_layer = get_or_create_result_layer()


# ============================================================
# RASTER HELPERS
# ============================================================

def map_point_to_raster_pixel(layer, map_point):
    canvas_crs = iface.mapCanvas().mapSettings().destinationCrs()
    raster_crs = layer.crs()

    if canvas_crs != raster_crs:
        transform = QgsCoordinateTransform(canvas_crs, raster_crs, QgsProject.instance())
        raster_point = transform.transform(map_point)
    else:
        raster_point = map_point

    dataset = gdal.Open(layer.source())

    if dataset is None:
        raise Exception("Raster could not be opened with GDAL.")

    geotransform = dataset.GetGeoTransform()
    inverse_geotransform = gdal.InvGeoTransform(geotransform)

    if inverse_geotransform is None:
        raise Exception("Could not invert raster geotransform.")

    px = int(
        inverse_geotransform[0]
        + inverse_geotransform[1] * raster_point.x()
        + inverse_geotransform[2] * raster_point.y()
    )

    py = int(
        inverse_geotransform[3]
        + inverse_geotransform[4] * raster_point.x()
        + inverse_geotransform[5] * raster_point.y()
    )

    return px, py, dataset


def read_rgb(dataset):
    if dataset.RasterCount >= 3:
        red = dataset.GetRasterBand(1).ReadAsArray()
        green = dataset.GetRasterBand(2).ReadAsArray()
        blue = dataset.GetRasterBand(3).ReadAsArray()
        return np.dstack([red, green, blue]).astype(np.int16)

    if dataset.RasterCount == 1:
        band = dataset.GetRasterBand(1)
        arr = band.ReadAsArray()
        color_table = band.GetColorTable()

        if color_table is not None:
            height, width = arr.shape
            red = np.zeros((height, width), dtype=np.uint8)
            green = np.zeros((height, width), dtype=np.uint8)
            blue = np.zeros((height, width), dtype=np.uint8)

            for value in np.unique(arr):
                color_entry = color_table.GetColorEntry(int(value))
                if color_entry is None:
                    continue
                r, g, b, a = color_entry
                mask = arr == value
                red[mask] = r
                green[mask] = g
                blue[mask] = b

            return np.dstack([red, green, blue]).astype(np.int16)

        gray = arr.astype(np.uint8)
        return np.dstack([gray, gray, gray]).astype(np.int16)

    raise Exception("Unsupported raster format.")


def flood_fill_connected_color_region(rgb, start_x, start_y, tolerance):
    height, width, channels = rgb.shape

    if start_x < 0 or start_x >= width or start_y < 0 or start_y >= height:
        raise Exception("Clicked point is outside the raster.")

    clicked_color = rgb[start_y, start_x].copy()
    visited = np.zeros((height, width), dtype=bool)
    mask = np.zeros((height, width), dtype=np.uint8)

    queue = deque()
    queue.append((start_x, start_y))
    visited[start_y, start_x] = True

    if EIGHT_CONNECTED:
        neighbours = [
            (-1, -1), (0, -1), (1, -1),
            (-1,  0),          (1,  0),
            (-1,  1), (0,  1), (1,  1),
        ]
    else:
        neighbours = [(0, -1), (-1, 0), (1, 0), (0, 1)]

    pixel_count = 0

    while queue:
        x, y = queue.popleft()
        color_distance = np.linalg.norm(rgb[y, x] - clicked_color)

        if color_distance <= tolerance:
            mask[y, x] = 1
            pixel_count += 1

            if pixel_count > MAX_PIXELS:
                raise Exception(
                    "The detected area is too large. The tolerance may be too high, "
                    "or you clicked on background, water, or a legend."
                )

            for dx, dy in neighbours:
                nx = x + dx
                ny = y + dy
                if 0 <= nx < width and 0 <= ny < height:
                    if not visited[ny, nx]:
                        visited[ny, nx] = True
                        queue.append((nx, ny))

    if pixel_count == 0:
        raise Exception("No area detected.")

    return mask, clicked_color, pixel_count


def write_mask_as_geotiff(mask, reference_dataset):
    temp_file = tempfile.NamedTemporaryFile(suffix=".tif", delete=False)
    temp_path = temp_file.name
    temp_file.close()

    driver = gdal.GetDriverByName("GTiff")
    output_dataset = driver.Create(
        temp_path,
        reference_dataset.RasterXSize,
        reference_dataset.RasterYSize,
        1,
        gdal.GDT_Byte
    )

    output_dataset.SetGeoTransform(reference_dataset.GetGeoTransform())
    output_dataset.SetProjection(reference_dataset.GetProjection())

    band = output_dataset.GetRasterBand(1)
    band.WriteArray(mask)
    band.SetNoDataValue(0)
    band.FlushCache()

    output_dataset.FlushCache()
    output_dataset = None

    return temp_path


def polygonize_mask(mask_path):
    result = processing.run(
        "gdal:polygonize",
        {
            "INPUT": mask_path,
            "BAND": 1,
            "FIELD": "DN",
            "EIGHT_CONNECTEDNESS": EIGHT_CONNECTED,
            "EXTRA": "",
            "OUTPUT": "TEMPORARY_OUTPUT"
        }
    )

    output = result["OUTPUT"]

    if hasattr(output, "isValid"):
        polygon_layer = output
    else:
        polygon_layer = QgsVectorLayer(output, "temporary_polygonized_region", "ogr")

    if not polygon_layer.isValid():
        raise Exception("Polygonization failed. The temporary polygon layer could not be loaded.")

    return polygon_layer


def add_region_to_result_layer(polygon_layer, polygon_name, clicked_color, pixel_count):
    if not result_layer.startEditing():
        raise Exception("Could not start editing the output layer.")

    added = 0

    for feature in polygon_layer.getFeatures():
        try:
            dn_value = int(feature["DN"])
        except Exception:
            continue

        if dn_value != 1:
            continue

        geometry = feature.geometry()
        if geometry is None or geometry.isEmpty():
            continue

        new_feature = QgsFeature(result_layer.fields())
        new_feature.setGeometry(geometry)
        new_feature["name"] = polygon_name
        new_feature["r"] = int(clicked_color[0])
        new_feature["g"] = int(clicked_color[1])
        new_feature["b"] = int(clicked_color[2])
        new_feature["tolerance"] = int(COLOR_TOLERANCE)
        new_feature["pixels"] = int(pixel_count)
        new_feature["mode"] = "click_connected_color"

        result_layer.addFeature(new_feature)
        added += 1

    if not result_layer.commitChanges():
        result_layer.rollBack()
        raise Exception("Could not save changes to the output layer.")

    result_layer.updateExtents()
    result_layer.triggerRepaint()
    return added


# ============================================================
# CLICK TOOL
# ============================================================

class ClickColorRegionToPolygonTool(QgsMapToolEmitPoint):
    def __init__(self, canvas, raster_layer):
        super().__init__(canvas)
        self.canvas = canvas
        self.raster_layer = raster_layer

    def canvasReleaseEvent(self, event):
        if event.button() != left_mouse_button():
            return

        map_point = self.toMapCoordinates(event.pos())

        polygon_name, ok = QInputDialog.getText(
            None,
            "Name polygon",
            "Name for the polygon to create:"
        )

        if not ok or polygon_name.strip() == "":
            QMessageBox.information(None, "Cancelled", "No name entered. No polygon was created.")
            return

        polygon_name = polygon_name.strip()

        try:
            px, py, dataset = map_point_to_raster_pixel(self.raster_layer, map_point)
            rgb = read_rgb(dataset)

            mask, clicked_color, pixel_count = flood_fill_connected_color_region(
                rgb,
                px,
                py,
                COLOR_TOLERANCE
            )

            mask_path = write_mask_as_geotiff(mask, dataset)
            polygon_layer = polygonize_mask(mask_path)

            added = add_region_to_result_layer(
                polygon_layer,
                polygon_name,
                clicked_color,
                pixel_count
            )

            try:
                os.remove(mask_path)
            except Exception:
                pass

            QMessageBox.information(
                None,
                "Polygon created",
                f"Name: {polygon_name}\n"
                f"Detected pixels: {pixel_count}\n"
                f"Polygons added: {added}\n"
                f"RGB color: {int(clicked_color[0])}, {int(clicked_color[1])}, {int(clicked_color[2])}"
            )

        except Exception as error:
            QMessageBox.critical(None, "Error", str(error))


# ============================================================
# ACTIVATE TOOL
# ============================================================

tool = ClickColorRegionToPolygonTool(iface.mapCanvas(), raster_layer)
iface.mapCanvas().setMapTool(tool)

QMessageBox.information(
    None,
    "Tool active",
    "Click-color polygon tool is active.\n\n"
    "Click on a colored area in the active georeferenced raster.\n"
    "The connected color area will be polygonized and written to a GeoPackage."
)

print("click color polygon tool active.")
