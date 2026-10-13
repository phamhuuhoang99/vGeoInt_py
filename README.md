# vGeoInt (Python / PyQGIS)

Bản viết lại của vGeoInt_v2 (C++) bằng Python + PyQGIS (QGIS 4, Qt6). Gồm 3 app: **vGeoInt** (chính), **vGeoCatalog**, **vGeoEngine**.

## Cài đặt

Chỉ cần [Pixi](https://pixi.sh) (`winget install prefix-dev.pixi`). Không cần Visual Studio, OSGeo4W hay OpenCV cài sẵn.

```bash
pixi install          # tải QGIS, Qt, GDAL, OpenCV... vào .pixi/
pixi run check-env    # kiểm tra môi trường
pixi run app          # chạy app chính
pixi run catalog      # vGeoCatalog
pixi run engine       # vGeoEngine
pixi run test         # chạy test
```

Phần AI chạy trong môi trường riêng: `pixi install -e ai`.

Model weights không nằm trong git. Đặt vào `models/` hoặc trỏ biến môi trường `VGEOINT_MODELS_DIR` tới thư mục models của app cũ.

## Cấu trúc

- `src/vgeoint/app|catalog|engine`: code 3 app
- `src/vgeoint/ai/scripts`: các script AI (chạy subprocess)
- `ui/`: file Qt Designer gốc, dùng lại nguyên vẹn
- `resources/`: icon/ảnh, `.qrc` được compile thành `.rcc` lúc chạy (`pixi run build-resources`)
- `sql/`: script PostgreSQL
