# Phát hiện tàu & dựng quỹ đạo từ ảnh PlanetScope đa thời gian — Báo cáo nghiên cứu

## 1. Dữ liệu khách hàng đưa

| Ngày (UTC) | Vệ tinh | Kích thước | Ghi chú |
|---|---|---|---|
| 2026-04-04 03:17 | 251f | 11292×8016 | mây 14 %, biển lặng → ảnh tốt nhất |
| 2026-04-07 03:18 | 252d | 11963×8479 | nửa phía tây mây dày; **metadata.json rỗng (0 byte)** |
| 2026-04-08 03:20 | 2540 | 11963×8479 | vùng Labuan; **chói nắng (sun glint) + mây tích nhỏ** trên biển; **metadata.json rỗng** |
| 2026-04-09 03:20 | 251a | 11097×7891 | **file .tif bị hỏng/tải thiếu** (392 MB, lỗi đọc từ hàng 6400) |
| 2026-04-15 03:20 | 251f | 11358×8049 | hơi mù, nước đục |

- Cảm biến: PlanetScope **SuperDove (PSB.SD)**, sản phẩm `3B AnalyticMS_8b`: 8 băng (coastal blue → NIR), 3 m/pixel, UTM 50N, đã orthorectify, giá trị là **bức xạ (radiance)**, chưa phải phản xạ.
- Khu vực: vịnh Brunei / Labuan (115.3–115.7°E, 5.0–5.3°N), có **khu neo đậu tàu lớn (~290 m, phần lớn là tàu chở LNG)** ngoài khơi.
- Các footprint chỉ **chồng lấn một phần**; mỗi ngày chụp một lần vào khoảng 03:18 UTC.

## 2. Ràng buộc quan trọng nhất: "quỹ đạo" nghĩa là gì?

Các ảnh cách nhau **1–6 ngày**. Tàu chạy 12 hải lý/giờ đi được khoảng **530 km mỗi ngày**, xa hơn nhiều so với một cảnh ảnh (~35 km). Vì vậy:

1. **Tàu đang chạy KHÔNG thể nối giữa các ngày** chỉ dựa vào ảnh, vì không có cơ sở nào để biết tàu ngày 04 có phải là tàu ngày 07 hay không.
2. Thứ dựng được từ chính bộ ảnh này:
   - **(a) Quỹ đạo của tàu neo/đậu/chạy chậm qua nhiều ngày**: tàu xoay quanh neo, đổi vị trí neo. Bản prototype đã nối được **22 tàu xuất hiện ở ≥ 2 ngày** trong khu neo, độ lệch vị trí 50–700 m.
   - **(b) Vector chuyển động tức thời trong từng ảnh** (hướng, tốc độ) cho tàu đang chạy. Có thể lấy từ:
     - **Độ lệch giữa các băng phổ của SuperDove**: các băng được chụp tại các thời điểm hơi khác nhau, nên tàu đang chạy bị "tách màu" (hiện tượng cầu vồng). Đo thực tế: tàu neo lệch 1–4 m, tàu chạy lệch 20–60 m. Hướng lệch chính là hướng di chuyển.
     - **Vệt sóng (Kelvin wake)** phía sau tàu cho biết hướng đi, và cả tốc độ nếu đo bước sóng.
   - **(c) Quỹ đạo thật nhiều ngày** chỉ có được khi **ghép với AIS** (hoặc ảnh dày đặc hơn, nhiều ảnh trong một ngày). Lúc đó, AIS cho đường đi, còn ảnh xác nhận vị trí. Tàu **có trên ảnh nhưng không có AIS** là "tàu tắt AIS" (dark vessel), và đây thường mới là thứ khách hàng thực sự cần.

👉 **Cần hỏi lại khách hàng** họ muốn (a), (b) hay (c). Đây là quyết định định hình cả giải pháp.

## 3. Prototype đã chạy (thư mục `shiptrack/`)

`detect_ships.py`: phát hiện tàu theo luật (không cần huấn luyện)
1. Mặt nạ nước bằng NDWI (green/NIR), ngưỡng Otsu theo từng cảnh, sau đó bỏ các thủy vực nhỏ (sông, ao).
2. Bỏ vùng cách bờ dưới 600 m (bến cảng, cửa sông, sóng vỗ bờ là nguồn báo động giả chính), và bỏ vùng mây.
3. Tìm điểm sáng bất thường trên NIR so với nền cục bộ (kiểu CFAR, ngưỡng theo sigma robust). Gom các mảnh gần nhau thành một tàu.
4. Lọc theo hình dạng (dài ≥ 20 m, thuôn) và SNR ≥ 25.
5. Đo độ lệch tâm giữa nhóm băng "sớm" (coastal/blue/green_i) và nhóm "muộn" (red/rededge/NIR) để ra **hướng di chuyển** và **độ dịch (m)**.
6. Xuất CSV, GeoJSON và ảnh quicklook có khoanh tàu và mũi tên hướng.

`link_tracks.py`: ghép phát hiện giữa các ngày bằng thuật toán Hungarian, cổng 800 m và độ dài tương đồng. Xuất `tracks.geojson` (LineString cho tàu thấy nhiều ngày) để mở trong QGIS hoặc Google Earth.

### Kết quả & đánh giá trung thực

| Cảnh | Số phát hiện | Đánh giá bằng mắt |
|---|---|---|
| 04/04 | 16 | Tốt: gần như toàn bộ là tàu thật trong khu neo |
| 07/04 | 16 | Khá (chỉ phần biển không mây) |
| 08/04 | 237 | **Kém**: đa số là chói nắng hoặc mây tích, chỉ vài chục là tàu thật |
| 15/04 | 31 | Khá: còn báo động giả do sóng nội (internal waves) ở rìa tây; **bỏ sót tàu vỏ tối** |
| 09/04 | – | Không đọc được (file hỏng) |

Hạn chế: phương pháp theo luật **không chịu được** chói nắng, mây tích, sóng nội và tàu vỏ tối, và đang bỏ qua toàn bộ tàu trong cảng hoặc sát bờ. Độ dịch giữa các băng **chưa quy ra hải lý/giờ được**, vì chưa biết chính xác độ trễ thời gian giữa các băng; cần hiệu chỉnh bằng một vài tàu có AIS.

## 4. Giải pháp đề xuất cho bản chính thức

1. **Tiền xử lý**
   - Xin khách hàng bộ file đầy đủ của Planet cho mỗi cảnh: `*_metadata.xml` (hệ số đổi sang phản xạ TOA) và **`*_udm2.tif`** (mặt nạ mây/mù/bóng của Planet), cùng file 09/04 không lỗi và 2 file metadata.json còn thiếu.
   - Mặt nạ đất từ OSM hoặc GSHHG, thay cho NDWI (ổn định hơn, xử lý được cảng).
2. **Bộ phát hiện học sâu**: YOLO-OBB (khung xoay; `ultralytics` đã có sẵn trên máy, GPU RTX 2080 Ti 11 GB là đủ).
   - Cắt ảnh thành tile 640 px chồng lấn, đầu vào RGB+NIR (hoặc chọn 3–4 băng).
   - Dữ liệu huấn luyện: dùng CFAR hiện tại **tạo nhãn sơ bộ**, rồi sửa tay khoảng 300–1000 tàu trên chính các cảnh này và các cảnh Planet khác. Có thể bổ sung tập *Planet "Ships in Satellite Imagery"* (Kaggle, 3 m) để tiền huấn luyện hoặc làm bộ lọc phân loại.
   - Thêm lớp "âm tính khó" (glint, mây vụn, sóng nội, giàn khoan, phao) để giảm báo động giả.
3. **Thuộc tính tàu**: chiều dài và rộng (từ khung xoay), hướng thân, vector chuyển động từ độ lệch băng (đã có code), vệt sóng.
4. **Dựng quỹ đạo**
   - Tàu neo/chậm: ghép theo vị trí và kích thước qua các ngày (đã có code).
   - Tàu chạy: vector tức thời trên từng ảnh; nếu có **AIS** thì nội suy vị trí AIS tại đúng giờ chụp, ghép bằng Hungarian, rồi vẽ đường AIS kèm điểm xác nhận từ ảnh, đồng thời gắn cờ tàu không có AIS.
5. **Đầu ra**: GeoJSON/KML/Shapefile, bản đồ HTML tương tác (Leaflet) và bảng thống kê.

## 5. Câu hỏi cần hỏi khách hàng
1. "Quỹ đạo" là đường đi nhiều ngày (cần AIS), hay hướng/tốc độ trên từng ảnh, hay chỉ theo dõi tàu neo?
2. Họ có hoặc có thể mua dữ liệu AIS cho vùng và thời gian này không?
3. Gửi lại bộ dữ liệu Planet đầy đủ (udm2, metadata.xml), file ngày 09/04 và 2 metadata.json bị rỗng.
4. Có cần phát hiện tàu trong cảng hoặc sát bờ, và tàu nhỏ (< 20 m, tức là < 7 pixel, gần giới hạn của ảnh 3 m) không?

## Cách chạy
```
python shiptrack/detect_ships.py SIMILARITY_SEARCH shiptrack/out
python shiptrack/link_tracks.py shiptrack/out
```

---

## 6. Cập nhật: bỏ ảnh lỗi + mô hình YOLO-OBB

**Dữ liệu dùng**: 04/04, 07/04, 15/04. Ảnh 09/04 (hỏng) và 08/04 (chói nắng) đã được chuyển vào `SIMILARITY_SEARCH/_excluded/`, không xoá.

### Quy trình (trong `shiptrack/`)
| Bước | Script | Việc làm |
|---|---|---|
| 1 | `make_labels.py` | CFAR đề xuất ứng viên khung xoay, xuất ảnh ghép để duyệt bằng mắt |
| 2 | `labels/labels_accepted.json`, `labels_added.json` | Nhãn đã duyệt: 39 tàu từ CFAR + 4 tàu do mô hình v1 tìm ra (vòng active learning) |
| 3 | `build_dataset.py` | Cắt tile 640 px (NIR-R-G); chỉ lấy tile biển đã gán nhãn đầy đủ, cộng tile đất/mây làm mẫu âm |
| 4 | `train_obb.py` | Fine-tune YOLO11s-OBB (tiền huấn luyện DOTA), xoay 0–180°, lật, mosaic; ~13 phút trên RTX 2080 Ti |
| 5 | `predict_scene.py` | Trượt cửa sổ trên cả cảnh, NMS khung xoay, bỏ phát hiện cách nước > 300 m, xuất CSV/GeoJSON (đa giác tàu) |
| 6 | `link_tracks.py`, `plot_tracks.py` | Ghép tàu giữa các ngày và vẽ bản đồ `pred_v2/tracks_overview.png` |

Trọng số: `runs/obb/runs/ships_v2/weights/best.pt`.

### Kết quả
- **Tập kiểm định** (cảnh 15/04, không dùng để huấn luyện, 14 tàu): precision 0.91, recall 0.86, mAP50 0.95. **Chỉ có 14 tàu nên con số này dao động lớn; chưa phải độ chính xác cam kết.**
- **Toàn cảnh** (ngưỡng 0.25): 04/04 có 16 tàu, 07/04 có 13 tàu, 15/04 có 23 tàu.
  - Ngoài khơi: không thấy báo động giả, và mọi tàu đã gán nhãn đều được tìm lại.
  - Ngày 15/04 có 6 báo động giả, toàn bộ là công trình ven bờ (cầu cảng, hàng phao, kè).
  - Mô hình tìm được thêm tàu đậu cạnh cầu cảng và một tàu nhỏ đang chạy.
- **Quỹ đạo**: 14 tàu xuất hiện ở ≥ 2 ngày, đều ở khu neo, phần lớn là tàu LNG ~250–290 m.
  - Giữa 04/04 và 15/04, hầu hết các tàu dịch cùng hướng, khoảng 100–150 m.
  - Đã kiểm tra trên đất liền: hai ảnh lệch định vị nhau dưới 1 m. Vậy độ dịch này là **chuyển động thật**: tàu xoay quanh neo theo dòng triều, không phải sai số ảnh.

### Hạn chế còn lại
- Dữ liệu huấn luyện rất ít (~43 tàu, 3 cảnh), nên mô hình chưa gặp chói nắng, sóng lớn, tàu nhỏ hay cảng đông đúc. Để dùng thực tế cần thêm cảnh Planet và nhãn (khoảng 500+ tàu).
- **Hướng/tốc độ từ độ lệch băng chưa tin cậy được**: tàu số 4 đứng yên giữa hai ngày nhưng vẫn lệch băng 21–31 m. Độ lệch này còn bị ảnh hưởng bởi màu sắc và kết cấu tàu, nên phải hiệu chỉnh bằng AIS trước khi dùng.
- Tàu đang chạy vẫn không nối được giữa các ngày. Kết luận ở mục 2 không đổi: cần AIS.
