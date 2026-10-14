# vGeoInt (Python / PyQGIS)

Bản viết lại của vGeoInt_v2 (C++) bằng Python + PyQGIS (QGIS 4, Qt6). Gồm 3 app: **vGeoInt** (chính), **vGeoCatalog**, **vGeoEngine**.

## Cài từ đầu trên máy Windows mới

Yêu cầu: Windows 10/11 64-bit, khoảng 10 GB trống (15 GB nếu dùng AI). Không cần Visual Studio, OSGeo4W,
Python hay OpenCV cài sẵn: mọi thứ (QGIS, Qt, GDAL, OpenCV...) được Pixi tải vào thư mục `.pixi/` của repo.

### 1. Cài Git và Pixi

Mở **PowerShell** và chạy:

```powershell
winget install --id Git.Git -e
winget install --id prefix-dev.pixi -e
```

Không có `winget` thì tải Git ở https://git-scm.com/download/win và cài Pixi bằng
`iwr -useb https://pixi.sh/install.ps1 | iex`.

**Đóng PowerShell và mở lại** để nhận PATH mới, rồi kiểm tra:

```powershell
git --version
pixi --version
```

Tuỳ chọn: ổ C ít chỗ thì đặt bộ đệm tải của Pixi sang ổ khác (mở lại PowerShell sau khi đặt):

```powershell
setx PIXI_CACHE_DIR D:\pixi-cache
```

### 2. Tải code

```powershell
cd D:\
git clone https://github.com/phamhuuhoang99/vGeoInt_py.git
cd vGeoInt_py
```

### 3. Cài môi trường và chạy

```powershell
pixi install          # lần đầu tải ~2 GB (QGIS, Qt, GDAL, OpenCV...) vào .pixi\
pixi run check-env    # kiểm tra môi trường + build icon (.rcc)
pixi run app          # app chính vGeoInt
```

Các lệnh khác:

```powershell
pixi run catalog      # vGeoCatalog (cần PostgreSQL, xem bước 5)
pixi run engine       # vGeoEngine  (cần PostgreSQL, xem bước 5)
pixi run test         # chạy test
pixi run build-resources   # build lại icon sau khi sửa resources\*.qrc
```

Luôn chạy các lệnh `pixi` trong thư mục `vGeoInt_py` (nơi có `pixi.toml`). Log và lỗi crash được ghi vào
`logs\<app>_log.txt` và `logs\<app>_crash.txt`.

### 4. Dữ liệu không có trong git (tuỳ chọn)

Các thư mục sau quá lớn nên không có trong git. Lấy từ máy/app cũ:

| Thư mục | Nội dung | Cần cho |
|---|---|---|
| `models\` | model AI (`vGeoInt_v2\models` của app cũ) | các chức năng AI |
| `data\catalog\` | bản đồ nền (`vGeoCatalog\data` của app cũ: `Data.shp`, `Data.ras`...) | vGeoCatalog |

Có thể copy vào, hoặc tạo junction tới thư mục sẵn có (trong `cmd`):

```bat
mklink /J models D:\vGeoInt_v2\vGeoInt_v2\models
mklink /J data\catalog D:\vGeoInt_v2\vGeoInt_v2\vGeoCatalog\data
```

Hoặc đặt biến môi trường `VGEOINT_MODELS_DIR` / `VGEOINT_CATALOG_DATA` trỏ tới các thư mục đó.

Phần AI chạy trong môi trường riêng (PyTorch, ultralytics... vài GB):

```powershell
pixi install -e ai
```

### 5. Cơ sở dữ liệu cho vGeoCatalog / vGeoEngine (tuỳ chọn)

App chính không cần database. vGeoCatalog và vGeoEngine cần PostgreSQL + PostGIS.

**Cách 1 (khuyên dùng): Docker.** Cài [Docker Desktop](https://www.docker.com/products/docker-desktop/)
(`winget install --id Docker.DockerDesktop -e`), mở Docker Desktop, rồi trong thư mục `vGeoInt_py`:

```powershell
pixi run db-up      # lần đầu: tạo mật khẩu ngẫu nhiên trong .env, tải image postgis/postgis:16-3.4,
                    # tạo database vGeoCatalog + vGeoEngine có sẵn dữ liệu (~1 phút)
pixi run catalog
pixi run engine
pixi run db-down    # dừng server (dữ liệu vẫn giữ trong volume vgeoint-pgdata)
```

- Server chạy ở `127.0.0.1:5432`, container `vgeoint-postgis`, tự khởi động lại cùng Docker Desktop.
  Cổng 5432 đã bị chiếm (đang cài PostgreSQL khác) thì thêm `VGEOINT_DB_PORT=5433` vào `.env` trước khi
  `pixi run db-up`.
- App đọc mật khẩu từ `.env` (không có trong git) nên không hỏi mật khẩu. Không xoá file này khi còn dùng
  volume cũ.
- Xoá hẳn dữ liệu để tạo lại từ `sql\`: `docker compose down -v` rồi `pixi run db-up`.
- Hai database được nạp từ bản dump của bộ cài cũ:
  - `vGeoCatalog` ← `sql\catalog\init_vgeocatalog.sql`: 2 thư viện, 13 ảnh đã quét, bản đồ nước/vùng.
    Đường dẫn ảnh là đường dẫn trên máy cũ (`D:/...`): quét lại thư mục trong vGeoCatalog nếu khác máy.
  - `vGeoEngine` ← `sql\engine\init_vgeoengine.sql`: nhóm/loại/kiểu đối tượng, máy bay, tàu, xe tăng,
    tên lửa, 438 ảnh, 28 video, 164 tài liệu, tài khoản `admin` và `user`. Đường dẫn media có dạng
    `vGeoInt_DB/...` nên cần thư mục `vGeoInt_DB` của bộ cài cũ để mở ảnh/video/tài liệu gốc (ảnh thu nhỏ
    đã nằm sẵn trong database).
- Các script `sql\catalog\*.sql`, `sql\engine\*.sql` khác là schema rỗng (dùng cho test và cách 2).

**Cách 2: cài PostgreSQL trực tiếp.**

1. Cài PostgreSQL (https://www.postgresql.org/download/windows/), trong Stack Builder chọn thêm
   **PostGIS**. Nhớ mật khẩu user `postgres`.
2. Tạo 2 database từ các script trong `sql\` (PowerShell, trong thư mục `vGeoInt_py`; sửa số phiên bản
   trong đường dẫn `bin` cho đúng):

   ```powershell
   $env:Path += ";C:\Program Files\PostgreSQL\16\bin"
   $env:PGPASSWORD = "<mật khẩu postgres>"
   $env:PGCLIENTENCODING = "utf-8"

   createdb -U postgres vGeoCatalog
   foreach ($f in "command", "Countries", "Regions") { psql -U postgres -d vGeoCatalog -q -f "sql\catalog\$f.sql" }

   createdb -U postgres vGeoEngine
   foreach ($f in "Group", "Class", "Type", "Object", "Note", "Image", "ImageDetail", "Video", "VideoDetail",
                  "Document", "DocumentDetail", "Account", "Aircraft", "Ship", "Tank", "Rocket") {
       psql -U postgres -d vGeoEngine -q -f "sql\engine\$f.sql"
   }
   ```

3. Chạy `pixi run catalog` / `pixi run engine`: lần đầu app hỏi mật khẩu database và lưu lại.

vGeoEngine có sẵn tài khoản `admin` (mật khẩu như app cũ).

Thứ tự app lấy thông tin kết nối: biến môi trường `VGEOINT_DB_HOST`, `VGEOINT_DB_PORT`, `VGEOINT_DB_NAME`,
`VGEOINT_DB_USER`, `VGEOINT_DB_PASSWORD` → mật khẩu đã nhập trong app → file `.env` → mặc định
(`localhost:5432`, user `postgres`).

Test database (`pixi run test`) tự dựng PostGIS trong **Docker** (`postgis/postgis:16-3.4`); không có
Docker Desktop thì các test đó bị bỏ qua.

### Lỗi thường gặp

- `pixi : The term 'pixi' is not recognized`: chưa mở lại PowerShell sau khi cài Pixi.
- `could not find pixi.toml`: đang đứng sai thư mục, `cd` vào `vGeoInt_py`.
- Không thấy icon trên toolbar: chạy `pixi run build-resources`.
- Chức năng AI báo thiếu môi trường / model: chạy `pixi install -e ai` và kiểm tra thư mục `models\` (bước 4).

## Cấu trúc

- `src/vgeoint/app|catalog|engine`: code 3 app
- `src/vgeoint/ai/scripts`: các script AI (chạy subprocess)
- `ui/`: file Qt Designer gốc, dùng lại nguyên vẹn
- `resources/`: icon/ảnh, `.qrc` được compile thành `.rcc` lúc chạy (`pixi run build-resources`)
- `sql/`: script PostgreSQL

## Môi trường AI

Các dialog AI chạy script trong `src/vgeoint/ai/scripts` bằng python của môi trường `ai`
(`vgeoint.ai.runner.ScriptRunner`), model lấy từ `models/` (xem bước 4 ở trên).

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
