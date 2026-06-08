from qgis.PyQt.QtWidgets import QInputDialog, QMessageBox
from qgis.PyQt.QtCore import Qt, QVariant
from qgis.PyQt.QtGui import QColor

from qgis.core import (
    QgsProject,
    QgsVectorLayer,
    QgsFeature,
    QgsField,
    QgsCoordinateTransform,
    QgsMapLayerType,
    QgsRectangle,
    QgsGeometry,
    QgsWkbTypes,
    QgsVectorFileWriter,
)

from qgis.gui import QgsMapTool, QgsRubberBand

from osgeo import gdal
import numpy as np
import tempfile
import os
import processing


# ============================================================
# SETTINGS
# ============================================================

COLOR_TOLERANCE = 35
EIGHT_CONNECTED = True
MAX_PIXELS = 5_000_000

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

def show_status(message):
    print(message)


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


def make_polygon_rubber_band(canvas):
    try:
        rubber = QgsRubberBand(canvas, QgsWkbTypes.PolygonGeometry)
    except Exception:
        from qgis.core import Qgis
        rubber = QgsRubberBand(canvas, Qgis.GeometryType.Polygon)

    rubber.setColor(QColor(255, 0, 0, 80))
    rubber.setWidth(2)
    return rubber


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

def open_dataset(layer):
    dataset = gdal.Open(layer.source())
    if dataset is None:
        raise Exception("Raster could not be opened with GDAL.")
    return dataset


def transform_map_point_to_raster_crs(layer, map_point):
    canvas_crs = iface.mapCanvas().mapSettings().destinationCrs()
    raster_crs = layer.crs()

    if canvas_crs != raster_crs:
        transform = QgsCoordinateTransform(canvas_crs, raster_crs, QgsProject.instance())
        return transform.transform(map_point)

    return map_point


def raster_point_to_pixel(dataset, raster_point):
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

    return px, py


def map_point_to_raster_pixel(layer, map_point, dataset):
    raster_point = transform_map_point_to_raster_crs(layer, map_point)
    return raster_point_to_pixel(dataset, raster_point)


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


# ============================================================
# RECTANGLE COLOR LOGIC
# ============================================================

def rectangle_to_pixel_bounds(layer, dataset, point_a, point_b):
    raster_point_a = transform_map_point_to_raster_crs(layer, point_a)
    raster_point_b = transform_map_point_to_raster_crs(layer, point_b)

    px1, py1 = raster_point_to_pixel(dataset, raster_point_a)
    px2, py2 = raster_point_to_pixel(dataset, raster_point_b)

    x_min = max(0, min(px1, px2))
    x_max = min(dataset.RasterXSize - 1, max(px1, px2))
    y_min = max(0, min(py1, py2))
    y_max = min(dataset.RasterYSize - 1, max(py1, py2))

    if x_max <= x_min or y_max <= y_min:
        raise Exception("The drawn rectangle is too small or outside the raster.")

    return x_min, x_max, y_min, y_max


def create_color_mask_inside_rectangle(rgb, selected_color, x_min, x_max, y_min, y_max, tolerance):
    height, width, channels = rgb.shape
    mask = np.zeros((height, width), dtype=np.uint8)

    subset = rgb[y_min:y_max + 1, x_min:x_max + 1]
    diff = subset - selected_color
    distance = np.sqrt(np.sum(diff * diff, axis=2))
    matching = distance <= tolerance

    pixel_count = int(np.sum(matching))

    if pixel_count == 0:
        raise Exception(
            "No matching pixels found inside the rectangle. "
            "The tolerance may be too low, or the rectangle does not contain the selected color."
        )

    if pixel_count > MAX_PIXELS:
        raise Exception(
            "Too many pixels detected. The rectangle may be too large, or the tolerance too high."
        )

    mask[y_min:y_max + 1, x_min:x_max + 1][matching] = 1
    return mask, pixel_count


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


def add_regions_to_result_layer(polygon_layer, polygon_name, selected_color, pixel_count):
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
        new_feature["r"] = int(selected_color[0])
        new_feature["g"] = int(selected_color[1])
        new_feature["b"] = int(selected_color[2])
        new_feature["tolerance"] = int(COLOR_TOLERANCE)
        new_feature["pixels"] = int(pixel_count)
        new_feature["mode"] = "rectangle_color"

        result_layer.addFeature(new_feature)
        added += 1

    if not result_layer.commitChanges():
        result_layer.rollBack()
        raise Exception("Could not save changes to the output layer.")

    result_layer.updateExtents()
    result_layer.triggerRepaint()
    return added


def rectangle_geometry_from_points(point_a, point_b):
    rect = QgsRectangle(point_a, point_b)

    p1 = rect.xMinimum(), rect.yMinimum()
    p2 = rect.xMaximum(), rect.yMinimum()
    p3 = rect.xMaximum(), rect.yMaximum()
    p4 = rect.xMinimum(), rect.yMaximum()

    wkt = (
        "POLYGON(("
        f"{p1[0]} {p1[1]}, "
        f"{p2[0]} {p2[1]}, "
        f"{p3[0]} {p3[1]}, "
        f"{p4[0]} {p4[1]}, "
        f"{p1[0]} {p1[1]}"
        "))"
    )

    return QgsGeometry.fromWkt(wkt)


# ============================================================
# MAP TOOL
# ============================================================

class RectangleColorRegionsToPolygonsTool(QgsMapTool):
    def __init__(self, canvas, raster_layer):
        super().__init__(canvas)

        self.canvas = canvas
        self.raster_layer = raster_layer
        self.dataset = open_dataset(raster_layer)
        self.rgb = read_rgb(self.dataset)

        self.selected_color = None
        self.selected_pixel = None
        self.dragging = False
        self.start_point = None
        self.end_point = None
        self.rubber_band = make_polygon_rubber_band(canvas)

        show_status("Step 1: click the color you want to polygonize.")

    def canvasPressEvent(self, event):
        if event.button() != left_mouse_button():
            return

        map_point = self.toMapCoordinates(event.pos())

        if self.selected_color is None:
            try:
                px, py = map_point_to_raster_pixel(self.raster_layer, map_point, self.dataset)
                height, width, channels = self.rgb.shape

                if px < 0 or px >= width or py < 0 or py >= height:
                    raise Exception("Clicked point is outside the raster.")

                self.selected_color = self.rgb[py, px].copy()
                self.selected_pixel = (px, py)

                QMessageBox.information(
                    None,
                    "Color selected",
                    "Target color selected:\n\n"
                    f"RGB: {int(self.selected_color[0])}, {int(self.selected_color[1])}, {int(self.selected_color[2])}\n\n"
                    "Now drag a rectangle over the area where this color should be searched."
                )

                show_status("Step 2: drag a rectangle over the search area.")

            except Exception as error:
                QMessageBox.critical(None, "Error", str(error))

            return

        self.dragging = True
        self.start_point = map_point
        self.end_point = map_point

        self.rubber_band.reset()
        geom = rectangle_geometry_from_points(self.start_point, self.end_point)
        self.rubber_band.setToGeometry(geom, None)

    def canvasMoveEvent(self, event):
        if not self.dragging:
            return

        self.end_point = self.toMapCoordinates(event.pos())
        self.rubber_band.reset()
        geom = rectangle_geometry_from_points(self.start_point, self.end_point)
        self.rubber_band.setToGeometry(geom, None)

    def canvasReleaseEvent(self, event):
        if event.button() != left_mouse_button():
            return

        if self.selected_color is None or not self.dragging:
            return

        self.dragging = False
        self.end_point = self.toMapCoordinates(event.pos())

        self.rubber_band.reset()
        geom = rectangle_geometry_from_points(self.start_point, self.end_point)
        self.rubber_band.setToGeometry(geom, None)

        polygon_name, ok = QInputDialog.getText(
            None,
            "Name polygons",
            "Name for the polygon(s) to create:"
        )

        if not ok or polygon_name.strip() == "":
            QMessageBox.information(None, "Cancelled", "No name entered. No polygons were created.")
            self.reset_color_selection()
            return

        polygon_name = polygon_name.strip()

        try:
            x_min, x_max, y_min, y_max = rectangle_to_pixel_bounds(
                self.raster_layer,
                self.dataset,
                self.start_point,
                self.end_point
            )

            mask, pixel_count = create_color_mask_inside_rectangle(
                self.rgb,
                self.selected_color,
                x_min,
                x_max,
                y_min,
                y_max,
                COLOR_TOLERANCE
            )

            mask_path = write_mask_as_geotiff(mask, self.dataset)
            polygon_layer = polygonize_mask(mask_path)

            added = add_regions_to_result_layer(
                polygon_layer,
                polygon_name,
                self.selected_color,
                pixel_count
            )

            try:
                os.remove(mask_path)
            except Exception:
                pass

            QMessageBox.information(
                None,
                "Polygons created",
                f"Name: {polygon_name}\n"
                f"Matching pixels inside rectangle: {pixel_count}\n"
                f"Polygons added: {added}\n"
                f"RGB color: {int(self.selected_color[0])}, {int(self.selected_color[1])}, {int(self.selected_color[2])}\n\n"
                "You can now click another color and draw another rectangle."
            )

            self.reset_color_selection()

        except Exception as error:
            QMessageBox.critical(None, "Error", str(error))
            self.reset_color_selection()

    def reset_color_selection(self):
        self.selected_color = None
        self.selected_pixel = None
        self.start_point = None
        self.end_point = None
        self.dragging = False
        self.rubber_band.reset()
        show_status("Ready: click the next target color.")


# ============================================================
# ACTIVATE TOOL
# ============================================================

tool = RectangleColorRegionsToPolygonsTool(iface.mapCanvas(), raster_layer)
iface.mapCanvas().setMapTool(tool)

QMessageBox.information(
    None,
    "Tool active",
    "Rectangle color polygon tool is active.\n\n"
    "Workflow:\n"
    "1. Click the target color.\n"
    "2. Drag a rectangle over the search area.\n"
    "3. Enter a name.\n\n"
    "All raster areas with the selected color inside the rectangle will be polygonized."
)

print("rectangle color polygon tool active.")
