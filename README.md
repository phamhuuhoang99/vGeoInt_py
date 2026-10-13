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

## Môi trường AI

```bash
pixi install -e ai      # PyTorch, ultralytics, rasterio, onnxruntime... (vài GB)
```

Các dialog AI chạy script trong `src/vgeoint/ai/scripts` bằng python của môi trường `ai`
(`vgeoint.ai.runner.ScriptRunner`). Model đặt trong `models/` — có thể là junction tới thư mục
models sẵn có, ví dụ: `mklink /J models ..\vGeoInt_v2\vGeoInt_v2\models` — hoặc đặt biến
`VGEOINT_MODELS_DIR`.

Test chạy model thật: `pixi run pytest -m slow`.

## Đóng gói bộ cài (Windows)

Cần Inno Setup 6 (`C:\Program Files (x86)\Inno Setup 6\ISCC.exe`).

```bash
pixi run -e package package          # dist/vGeoInt-Setup-<version>.exe   (~0,9 GB)
pixi run -e package package --ai     # dist/vGeoInt-AI-Setup-<version>.exe (~1,4 GB)
pixi run -e package package --all    # cả hai
```

- **vGeoInt-Setup**: 3 app + môi trường QGIS (`pixi-pack` môi trường `runtime`) + bản đồ nền vGeoCatalog.
  Cài cho người dùng hiện tại (không cần quyền admin), tạo shortcut vGeoInt / vGeoCatalog / vGeoEngine.
  Khi cài, `pixi-unpack` giải nén môi trường vào `<thư mục cài>\env` và `make_launch_env.py` ghi lại
  biến môi trường; shortcut chạy `env\pythonw.exe launcher.pyw <module>`.
- **vGeoInt-AI-Setup**: môi trường `ai` + thư mục `models/`, tự cài vào thư mục của vGeoInt đã cài
  (`envs\ai`, `models`). Không cài gói này thì các chức năng AI báo "Chưa cài gói AI".
- Máy đích không cần Python, OSGeo4W hay Visual Studio. vGeoCatalog / vGeoEngine cần một server
  PostgreSQL + PostGIS (mật khẩu được hỏi lần đầu, hoặc đặt biến `VGEOINT_DB_PASSWORD`).
