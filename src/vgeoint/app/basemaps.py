"""Online basemaps (XYZ tiles) for viewing and digitizing; not in the C++ app.

These are only displayed (streamed by QGIS as tiles); nothing is saved to files: the Google and Esri
terms do not allow downloading their imagery.
"""

from dataclasses import dataclass
from urllib.parse import quote

from qgis.core import QgsProject, QgsRasterLayer


@dataclass(frozen=True)
class Basemap:
    name: str
    url: str
    zmax: int
    attribution: str


BASEMAPS = {
    "google_satellite": Basemap(
        "Google Satellite", "https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}", 20, "© Google"
    ),
    "google_hybrid": Basemap(
        "Google Hybrid (ảnh + nhãn)", "https://mt1.google.com/vt/lyrs=y&x={x}&y={y}&z={z}", 20, "© Google"
    ),
    "esri_imagery": Basemap(
        "Esri World Imagery",
        "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        19,
        "© Esri, Maxar, Earthstar Geographics",
    ),
    "osm": Basemap(
        "OpenStreetMap", "https://tile.openstreetmap.org/{z}/{x}/{y}.png", 19, "© OpenStreetMap contributors"
    ),
}


def xyz_uri(basemap: Basemap) -> str:
    # The tile URL is one parameter of the provider URI: its own "&" must be percent-encoded.
    return f"type=xyz&url={quote(basemap.url, safe=':/{}')}&zmin=0&zmax={basemap.zmax}"


def basemap_layer(key: str) -> QgsRasterLayer:
    basemap = BASEMAPS[key]
    layer = QgsRasterLayer(xyz_uri(basemap), basemap.name, "wms")
    layer.metadata().setRights([basemap.attribution])
    layer.setCustomProperty("vgeoint/basemap", key)
    return layer


def add_basemap(key: str, project: QgsProject | None = None) -> QgsRasterLayer | None:
    """Add the basemap at the bottom of the layer tree (under the data); reuse it if already there."""
    project = project or QgsProject.instance()
    for layer in project.mapLayers().values():
        if layer.customProperty("vgeoint/basemap") == key:
            return layer
    layer = basemap_layer(key)
    if not layer.isValid():
        return None
    project.addMapLayer(layer, False)
    root = project.layerTreeRoot()
    root.insertLayer(len(root.children()), layer)
    return layer
