"""Download satellite imagery for free, without Google Earth Engine (not in the C++ app).

Same form as the Google Earth Engine dialog, with Microsoft Planetary Computer as the source: its STAC
catalogue and read tokens are public, so there is no login and no project. The script reads only the
region from the cloud-optimized GeoTIFFs and runs with the app's own Python (GDAL), so it also works
without the AI add-on.
"""

from qgis.PyQt.QtWidgets import QFormLayout, QGroupBox, QLabel

from vgeoint.ai.runner import GUI_ENV
from vgeoint.app.dialogs.google_earth_engine import Dataset, GoogleEarthEngineDialog, explain_error
from vgeoint.common.utils import get_icon

CATALOG_URL = "https://planetarycomputer.microsoft.com/catalog"
CLOUD = "eo:cloud_cover"

DATASETS = [
    Dataset(
        "Sentinel-2 (quang học, 10 m)", "sentinel-2-l2a", 10,
        [("Màu thật (B4, B3, B2)", "B04,B03,B02"), ("Hồng ngoại màu giả (B8, B4, B3)", "B08,B04,B03"),
         ("Nông nghiệp (B11, B8, B2)", "B11,B08,B02"), ("Như bản cũ (B3, B8, B11)", "B03,B08,B11"),
         ("4 kênh 10 m (B2, B3, B4, B8)", "B02,B03,B04,B08")],
        cloud_property=CLOUD, methods=("least_cloudy", "mosaic"),
    ),
    Dataset(
        "Landsat 9 (quang học, 30 m)", "landsat-c2-l2", 30,
        [("Màu thật (B4, B3, B2)", "red,green,blue"), ("Hồng ngoại màu giả (B5, B4, B3)", "nir08,red,green"),
         ("Hồng ngoại sóng ngắn (B7, B5, B4)", "swir22,nir08,red")],
        cloud_property=CLOUD, filters=["landsat-9"], methods=("least_cloudy", "mosaic"),
    ),
    Dataset(
        "Landsat 8 (quang học, 30 m)", "landsat-c2-l2", 30,
        [("Màu thật (B4, B3, B2)", "red,green,blue"), ("Hồng ngoại màu giả (B5, B4, B3)", "nir08,red,green"),
         ("Hồng ngoại sóng ngắn (B7, B5, B4)", "swir22,nir08,red")],
        cloud_property=CLOUD, filters=["landsat-8"], methods=("least_cloudy", "mosaic"),
    ),
    Dataset(
        "Sentinel-1 (radar, chụp xuyên mây, 10 m)", "sentinel-1-rtc", 10,
        [("Phân cực VV, VH", "vv,vh"), ("Phân cực VV", "vv")],
        bytes_per_pixel=4, methods=("least_cloudy", "mosaic"),
    ),
    Dataset(
        "Độ cao Copernicus DEM (30 m)", "cop-dem-glo-30", 30, [("Độ cao (DEM)", "data")],
        bytes_per_pixel=4, dated=False, methods=("mosaic",),
    ),
]


class FreeImageryDialog(GoogleEarthEngineDialog):
    TITLE = "Tải ảnh vệ tinh miễn phí (không cần tài khoản)"
    SCRIPT = "free_imagery_download.py"
    DATASETS = DATASETS
    SETTINGS = "FreeImagery"
    NEEDS_ACCOUNT = False
    ENV = GUI_ENV
    MAX_DOWNLOAD_MB = None  # no server-side limit: the region is read piece by piece

    def __init__(self, parent=None, map_canvas=None, layer_tree_view=None):
        super().__init__(parent, map_canvas, layer_tree_view)
        self.data_id_edit.setPlaceholderText("ví dụ: S2B_MSIL2A_20250117T032959_R018_T48QWJ_20250117T073102")
        self.advanced_group.setTitle("Nâng cao: tải theo ID ảnh (STAC item)")

    def name(self) -> str:
        return "FreeImagery"

    def get_icon(self):
        return get_icon("Earth.svg")

    def _create_account_group(self) -> QGroupBox:
        group = QGroupBox("1. Nguồn dữ liệu", self)
        form = QFormLayout(group)
        label = QLabel(
            f'<b>Microsoft Planetary Computer</b>: miễn phí, không cần đăng nhập. '
            f'Sentinel-2 L2A, Landsat Collection 2 L2, Sentinel-1 RTC (đã hiệu chỉnh địa hình), '
            f'Copernicus DEM 30 m. Chỉ tải phần ảnh trong vùng quan tâm. '
            f'<a href="{CATALOG_URL}">Xem danh mục dữ liệu</a>',
            self,
        )
        label.setWordWrap(True)
        label.setOpenExternalLinks(True)
        form.addRow(label)
        return group

    def _source_arguments(self) -> list[str]:
        return []

    def _collection_arguments(self) -> list[str]:
        ds = self.dataset()
        args = ["--collection", ds.collection]
        if ds.dated:
            args += ["--start", self.start_date.date().toString("yyyy-MM-dd"),
                     "--end", self.end_date.date().addDays(1).toString("yyyy-MM-dd")]
        if ds.cloud_property:
            args += ["--max_cloud", str(self.cloud_spin.value())]
        if ds.filters:
            args += ["--platform", ",".join(ds.filters)]
        return args

    def _run(self, task: str, args: list[str]):
        # An item ID needs its collection (STAC items are looked up per collection).
        if "--data_id" in args and "--collection" not in args:
            args = [*args, "--collection", self.dataset().collection]
        super()._run(task, args)

    def _explain(self, lines: list[str]) -> str:
        return explain_error(lines, "")
