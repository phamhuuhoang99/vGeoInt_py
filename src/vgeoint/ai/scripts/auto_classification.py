#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Auto Classification Script for vGeoInt_v2
Phân loại tự động ảnh vệ tinh sử dụng mô hình Random Forest
Hỗ trợ phân loại thành các lớp: Dân cư, Thực vật, Giao thông, Thủy hệ
"""

import argparse
import sys
import os
import numpy as np
import warnings
import time
import locale
from pathlib import Path

# Set UTF-8 encoding for Windows console
if sys.platform.startswith('win'):
    try:
        # Try to set UTF-8 encoding for stdout/stderr
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except (AttributeError, OSError):
        # Fallback for older Python versions
        import codecs
        sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, errors='replace')
        sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, errors='replace')

warnings.filterwarnings('ignore')

def log_progress(message, flush=True):
    """Print progress message with safe encoding handling"""
    try:
        # Replace Unicode symbols with ASCII alternatives for better compatibility
        safe_message = message.replace('✓', '[OK]').replace('❌', '[ERROR]').replace('⚠️', '[WARN]')
        print(safe_message, flush=flush)
    except UnicodeEncodeError:
        # Fallback to ASCII-only characters
        ascii_message = message.encode('ascii', errors='replace').decode('ascii')
        print(ascii_message, flush=flush)

def log_error(message, flush=True):
    """Print error message with safe encoding handling"""
    try:
        safe_message = message.replace('✓', '[ERROR]').replace('❌', '[ERROR]').replace('⚠️', '[WARN]')
        print(safe_message, file=sys.stderr, flush=flush)
    except UnicodeEncodeError:
        ascii_message = message.encode('ascii', errors='replace').decode('ascii')
        print(ascii_message, file=sys.stderr, flush=flush)

# Check dependencies with better error handling
DEPENDENCIES_AVAILABLE = True
missing_deps = []

try:
    from joblib import load
    log_progress("[OK] Joblib loaded successfully")
except ImportError as e:
    missing_deps.append("joblib")
    log_error(f"Missing Joblib: {e}")

try:
    import rasterio
    log_progress("[OK] Rasterio loaded successfully")
except ImportError as e:
    missing_deps.append("rasterio")
    log_error(f"Missing Rasterio: {e}")

try:
    from sklearn.ensemble import RandomForestClassifier
    log_progress("[OK] Scikit-learn loaded successfully")
except ImportError as e:
    missing_deps.append("scikit-learn")
    log_error(f"Missing Scikit-learn: {e}")

if missing_deps:
    DEPENDENCIES_AVAILABLE = False
    log_error(f"Missing dependencies: {', '.join(missing_deps)}")
    log_error("Please install required packages:")
    log_error("pip install joblib rasterio scikit-learn numpy")
else:
    log_progress("[OK] All Python dependencies loaded successfully")


def load_model(model_path):
    """
    Tải mô hình Random Forest đã huấn luyện từ đường dẫn đã cho.

    Args:
        model_path (str): Đường dẫn đến tệp mô hình (.joblib).

    Returns:
        sklearn.ensemble.RandomForestClassifier: Mô hình Random Forest đã tải.
    """
    try:
        model = load(model_path)
        log_progress(f"[OK] Mô hình đã được tải thành công từ: {model_path}")
        return model
    except FileNotFoundError:
        log_error(f"Lỗi: Không tìm thấy tệp mô hình tại đường dẫn: {model_path}")
        return None
    except Exception as e:
        log_error(f"Lỗi khi tải mô hình từ {model_path}: {e}")
        return None


def load_tiff_image_with_rasterio(tif_path):
    """
    Tải ảnh TIFF nhiều kênh bằng Rasterio và trả về dưới dạng mảng NumPy.

    Args:
        tif_path (str): Đường dẫn đến tệp ảnh TIFF.

    Returns:
        tuple: (numpy.ndarray, dict, rasterio.DatasetReader) - Mảng NumPy của ảnh,
               profile (metadata) của ảnh, và đối tượng rasterio DatasetReader.
    """
    try:
        with rasterio.open(tif_path) as src:
            # Đọc tất cả các kênh. rasterio đọc theo định dạng (bands, rows, cols).
            # Chuyển đổi sang (rows, cols, bands) để phù hợp với NumPy và scikit-learn.
            img = src.read().transpose((1, 2, 0))
            profile = src.profile  # Lấy profile (metadata) của ảnh gốc
            log_progress(
                f"[OK] Ảnh TIFF đã được tải thành công từ: {tif_path} với kích thước {img.shape}"
            )
            return (
                img,
                profile,
                src,
            )  # Trả về cả đối tượng src để lấy thông tin như NoDataValue nếu cần
    except rasterio.errors.RasterioIOError as e:
        log_error(f"Lỗi Rasterio khi tải ảnh từ {tif_path}: {e}")
        return None, None, None
    except Exception as e:
        log_error(f"Lỗi khi tải ảnh TIFF từ {tif_path}: {e}")
        return None, None, None


def classify_image(img, model):
    """
    Phân loại ảnh đầu vào bằng mô hình đã huấn luyện.

    Args:
        img (numpy.ndarray): Mảng NumPy của ảnh đầu vào (rows, cols, bands).
        model (sklearn.ensemble.RandomForestClassifier): Mô hình Random Forest đã tải.

    Returns:
        numpy.ndarray: Mảng NumPy của kết quả phân loại (rows, cols).
    """
    if model is None:
        log_error("Lỗi: Mô hình không được tải. Không thể phân loại.")
        return None
    if img is None:
        log_error("Lỗi: Ảnh đầu vào không hợp lệ. Không thể phân loại.")
        return None

    # Lấy kích thước ảnh
    rows, cols, bands = img.shape
    log_progress(f"Kích thước ảnh: {rows}x{cols} với {bands} kênh.")

    # Định dạng lại ảnh thành mảng 2D (pixel x kênh)
    # Chuyển đổi sang float để tránh lỗi kiểu dữ liệu với scikit-learn nếu cần
    img_reshaped = img.reshape(-1, bands).astype(np.float32)

    try:
        log_progress("Đang phân loại ảnh... (quá trình này có thể mất vài phút)")
        start_time = time.time()
        # Phân loại từng pixel
        class_prediction = model.predict(img_reshaped)
        elapsed_time = time.time() - start_time
        log_progress(f"[OK] Phân loại ảnh hoàn tất trong {elapsed_time:.2f} giây.")
        # Chuyển kết quả phân loại về kích thước ban đầu
        return class_prediction.reshape(rows, cols)
    except Exception as e:
        log_error(f"Lỗi khi phân loại ảnh: {e}")
        return None


def apply_mask(class_prediction, mask):
    """
    Áp dụng mặt nạ (mask) để gán giá trị NaN cho các pixel không hợp lệ.

    Args:
        class_prediction (numpy.ndarray): Mảng kết quả phân loại.
        mask (numpy.ndarray): Mảng mặt nạ boolean (True cho pixel hợp lệ).

    Returns:
        numpy.ndarray: Mảng kết quả phân loại đã áp dụng mặt nạ.
    """
    if class_prediction is None or mask is None:
        log_error(
            "Lỗi: Kết quả phân loại hoặc mặt nạ không hợp lệ. Không thể áp dụng mặt nạ."
        )
        return None
    log_progress("Áp dụng mặt nạ cho kết quả phân loại.")
    return np.where(mask, class_prediction, np.nan)


def save_classification_with_rasterio(classification, original_profile, output_path):
    """
    Lưu kết quả phân loại vào tệp TIFF mới bằng Rasterio.

    Args:
        classification (numpy.ndarray): Mảng NumPy của kết quả phân loại.
        original_profile (dict): Profile (metadata) của ảnh gốc từ rasterio.
        output_path (str): Đường dẫn để lưu tệp TIFF kết quả.
    """
    if classification is None or original_profile is None:
        log_error(
            "Lỗi: Kết quả phân loại hoặc profile ảnh gốc không hợp lệ. Không thể lưu."
        )
        return

    # Cập nhật profile cho ảnh đầu ra
    out_profile = original_profile.copy()
    out_profile.update(
        dtype=rasterio.float32,  # Kiểu dữ liệu của kết quả phân loại
        count=1,  # Chỉ có một kênh đầu ra (kết quả phân loại)
        nodata=-9999,  # Giá trị NoData
    )

    try:
        with rasterio.open(output_path, "w", **out_profile) as dst:
            dst.write(
                classification.astype(rasterio.float32), 1
            )  # Ghi mảng vào kênh đầu tiên
            
            # Thêm thông tin chú thích cho các lớp phân loại
            dst.update_tags(
                class_1="Dân cư",
                class_2="Thực vật",
                class_3="Giao thông",
                class_4="Thủy hệ"
            )
            
        log_progress(f"[OK] Kết quả phân loại đã được lưu tại: {output_path}")
        return output_path
    except Exception as e:
        log_error(f"Lỗi khi lưu kết quả phân loại vào {output_path}: {e}")
        return None


def create_colored_classification(classification, original_profile, output_path):
    """
    Tạo ảnh phân loại với màu sắc khác nhau cho từng lớp và lưu vào tệp TIFF.
    Sử dụng style unique values như trong QGIS.
    
    Args:
        classification (numpy.ndarray): Mảng NumPy của kết quả phân loại.
        original_profile (dict): Profile (metadata) của ảnh gốc từ rasterio.
        output_path (str): Đường dẫn để lưu tệp TIFF kết quả.
    """
    if classification is None or original_profile is None:
        log_error("Lỗi: Kết quả phân loại hoặc profile ảnh gốc không hợp lệ. Không thể tạo ảnh màu.")
        return
    
    # Định nghĩa bảng màu cho các lớp phân loại (RGBA)
    # Mỗi lớp sẽ có một màu riêng biệt (R, G, B, A)
    # 1: Dân cư - Màu đỏ
    # 2: Thực vật - Màu xanh lá
    # 3: Giao thông - Màu vàng
    # 4: Thủy hệ - Màu xanh dương
    # Tạo color_map với màu nhẹ hơn để không chói mắt
    # Giảm độ đậm của màu bằng cách giảm giá trị RGB
    color_map = {
        1: (180, 0, 0, 255),      # Đỏ nhạt - Dân cư
        2: (0, 180, 0, 255),      # Xanh lá nhạt - Thực vật
        3: (180, 180, 0, 255),    # Vàng nhạt - Giao thông
        4: (0, 0, 180, 255)       # Xanh dương nhạt - Thủy hệ
    }
    
    # Tạo bản sao của dữ liệu phân loại và chuyển đổi sang uint8
    # Đảm bảo giá trị nằm trong khoảng 0-255 để sử dụng với colormap
    data_uint8 = classification.astype(np.uint8)
    
    # Tạo tên file cho ảnh màu với style unique values
    colored_output_path = output_path.replace('.tif', '_unique_values.tif')
    
    # Cập nhật profile cho ảnh đầu ra
    out_profile = original_profile.copy()
    out_profile.update(
        dtype=rasterio.uint8,  # Kiểu dữ liệu uint8 để sử dụng với colormap
        count=1,              # Chỉ có một kênh đầu ra
        nodata=0              # Giá trị NoData
    )
    
    try:
        with rasterio.open(colored_output_path, "w", **out_profile) as dst:
            # Ghi dữ liệu phân loại
            dst.write(data_uint8, 1)
            
            # Áp dụng bảng màu (colormap) cho ảnh
            dst.write_colormap(1, color_map)
            
            # Thêm thông tin chú thích cho các lớp phân loại
            dst.update_tags(
                class_1="Dân cư",
                class_2="Thực vật",
                class_3="Giao thông",
                class_4="Thủy hệ"
            )
            
        log_progress(f"[OK] Ảnh phân loại với style unique values đã được lưu tại: {colored_output_path}")
        return colored_output_path
    except Exception as e:
        log_error(f"Lỗi khi tạo ảnh phân loại với style unique values: {e}")
        return None


def process_image(tif_path, model_path, output_path):
    """
    Quy trình đầy đủ để tải ảnh, phân loại và lưu kết quả.

    Args:
        tif_path (str): Đường dẫn đến tệp ảnh TIFF đầu vào.
        model_path (str): Đường dẫn đến tệp mô hình Random Forest (.joblib).
        output_path (str): Đường dẫn để lưu tệp TIFF kết quả phân loại.

    Returns:
        numpy.ndarray or None: Mảng NumPy của kết quả phân loại đã áp dụng mặt nạ, hoặc None nếu có lỗi.
    """
    log_progress(f"\n--- Bắt đầu xử lý ảnh: {os.path.basename(tif_path)} ---")

    # Tải mô hình
    model = load_model(model_path)
    if model is None:
        return None

    # Tải ảnh TIFF
    # Hàm này giờ trả về img, profile và src_ds
    img, img_profile, img_src_ds = load_tiff_image_with_rasterio(tif_path)
    if img is None or img_profile is None:
        return None

    # Lấy thông tin kích thước và tạo mặt nạ (mask)
    # Giả định kênh đầu tiên là kênh hợp lệ để tạo mặt nạ (pixel > 0 là hợp lệ)
    rows, cols, bands = img.shape
    mask = img[:, :, 0] > 0

    # Phân loại ảnh
    class_prediction = classify_image(img, model)
    if class_prediction is None:
        return None

    # Áp dụng mặt nạ
    class_prediction_masked = apply_mask(class_prediction, mask)
    if class_prediction_masked is None:
        return None

    # Lưu kết quả phân loại
    saved_path = save_classification_with_rasterio(class_prediction_masked, img_profile, output_path)
    if saved_path is None:
        return None

    log_progress(f"--- Kết thúc xử lý ảnh: {os.path.basename(tif_path)} ---\n")
    return class_prediction_masked


def main():
    parser = argparse.ArgumentParser(description="Phân loại tự động ảnh vệ tinh sử dụng Random Forest")
    parser.add_argument(
        "--input", "-i", required=True, help="Đường dẫn đến ảnh TIFF đầu vào"
    )
    parser.add_argument(
        "--model", "-m", required=True, help="Đường dẫn đến mô hình Random Forest (.joblib)"
    )
    parser.add_argument(
        "--output", "-o", required=True, help="Đường dẫn để lưu kết quả phân loại"
    )
    parser.add_argument(
        "--colored", "-c", action="store_true", help="Tạo ảnh phân loại với màu sắc"
    )

    args = parser.parse_args()

    if not DEPENDENCIES_AVAILABLE:
        log_error("Không thể tiếp tục do thiếu các thư viện cần thiết.")
        sys.exit(1)

    # Kiểm tra đường dẫn đầu vào
    if not os.path.exists(args.input):
        log_error(f"Lỗi: Tệp ảnh đầu vào không tồn tại tại: {args.input}")
        sys.exit(1)

    if not os.path.exists(args.model):
        log_error(f"Lỗi: Tệp mô hình không tồn tại tại: {args.model}")
        sys.exit(1)

    # Tạo thư mục đầu ra nếu chưa tồn tại
    output_dir = os.path.dirname(args.output)
    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir)
        log_progress(f"Đã tạo thư mục đầu ra: {output_dir}")

    # Xử lý ảnh
    classification_result = process_image(args.input, args.model, args.output)

    if classification_result is not None:
        log_progress("\nQuy trình phân loại hoàn tất. Kết quả được lưu vào tệp TIFF.")
        
        # Tạo ảnh phân loại với style unique values nếu được yêu cầu
        if args.colored:
            # Tải ảnh đã phân loại để lấy profile
            _, img_profile, _ = load_tiff_image_with_rasterio(args.output)
            if img_profile is not None:
                # Tạo ảnh phân loại với style unique values
                colored_output_path = create_colored_classification(
                    classification_result, img_profile, args.output
                )
                if colored_output_path:
                    log_progress("\nĐã tạo ảnh phân loại với style unique values và chú thích:")
                    log_progress("1: Dân cư (Đỏ nhạt)")
                    log_progress("2: Thực vật (Xanh lá nhạt)")
                    log_progress("3: Giao thông (Vàng nhạt)")
                    log_progress("4: Thủy hệ (Xanh dương nhạt)")
    else:
        log_error("\nQuy trình phân loại gặp lỗi.")
        sys.exit(1)


if __name__ == "__main__":
    main()