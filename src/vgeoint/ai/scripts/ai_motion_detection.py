#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI Motion Detection Script for vGeoInt_v2
Phát hiện thay đổi lớp phủ mặt đất sử dụng AI/ML
Dựa trên land_cover_change_detection.py và example_usage.py
"""

import sys
import os

# Safe print function for Windows console
def safe_print(text):
    """Safe print that handles Unicode encoding issues on Windows"""
    try:
        print(text)
    except UnicodeEncodeError:
        # Replace problematic characters with ASCII equivalents
        safe_text = (text.replace('🌍', '[EARTH]')
                         .replace('⚠️', '[WARNING]')
                         .replace('❌', '[ERROR]')
                         .replace('✅', '[SUCCESS]')
                         .replace('📊', '[CHART]')
                         .replace('📁', '[FOLDER]')
                         .replace('🎯', '[TARGET]')
                         .replace('🔢', '[NUMBERS]')
                         .replace('🎨', '[ART]')
                         .replace('⚡', '[LIGHTNING]'))
        print(safe_text.encode('ascii', 'replace').decode('ascii'))

# Override built-in print with safe version
import builtins
original_print = builtins.print

def safe_builtin_print(*args, **kwargs):
    """Safe version of print that handles Unicode encoding"""
    try:
        original_print(*args, **kwargs)
    except UnicodeEncodeError:
        # Convert all args to safe strings
        safe_args = []
        for arg in args:
            text = str(arg)
            safe_text = (text.replace('🌍', '[EARTH]')
                            .replace('⚠️', '[WARNING]')
                            .replace('❌', '[ERROR]')
                            .replace('✅', '[SUCCESS]')
                            .replace('📊', '[CHART]')
                            .replace('📁', '[FOLDER]')
                            .replace('🎯', '[TARGET]')
                            .replace('🔢', '[NUMBERS]')
                            .replace('🎨', '[ART]')
                            .replace('⚡', '[LIGHTNING]'))
            safe_args.append(safe_text.encode('ascii', 'replace').decode('ascii'))
        original_print(*safe_args, **kwargs)

builtins.print = safe_builtin_print
import argparse
import numpy as np

try:
    import rasterio
    from rasterio.transform import from_bounds
    from sklearn.ensemble import RandomForestClassifier
    import joblib
    import matplotlib.pyplot as plt
    import matplotlib.image as mpimg
    import pandas as pd
    from matplotlib.colors import ListedColormap, BoundaryNorm
    from matplotlib.patches import Patch
    from collections import defaultdict
    try:
        from PIL import Image
    except ImportError:
        print("⚠️ PIL không có sẵn, một số tính năng ảnh có thể bị hạn chế")
except ImportError as e:
    print(f"Error importing required libraries: {e}")
    print("Please install: pip install rasterio scikit-learn joblib matplotlib pandas pillow")
    sys.exit(1)


class LandCoverChangeDetector:
    """
    Lớp phát hiện thay đổi lớp phủ mặt đất sử dụng AI/ML
    """

    def __init__(self, model_path=None):
        """
        Khởi tạo detector với mô hình đã được huấn luyện (bắt buộc)

        Args:
            model_path (str): Đường dẫn đến file mô hình Random Forest (.joblib) - BẮT BUỘC
        """
        self.model = None
        self.use_ml_model = False

        if not model_path:
            raise ValueError("Đường dẫn mô hình ML là bắt buộc. Vui lòng cung cấp file .joblib")

        if not os.path.exists(model_path):
            raise FileNotFoundError(f"Không tìm thấy file mô hình tại: {model_path}")

        try:
            self.model = joblib.load(model_path)
            self.use_ml_model = True
            print(f"✅ Đã tải mô hình ML từ: {model_path}")
        except Exception as e:
            raise RuntimeError(f"Không thể tải mô hình ML: {e}")

        # Định nghĩa các lớp phân loại
        self.class_names = {
            1: "Đất trống",
            2: "Thảm thực vật",
            3: "Nước",
            4: "Xây dựng"
        }

        # Tạo bảng chú thích biến đổi theo hệ thống ma trận
        self.change_legend = self._create_matrix_change_legend()

    def _create_matrix_change_legend(self):
        """
        Tạo bảng chú thích biến đổi theo hệ thống ma trận
        Mã hóa: before_class * 10 + after_class

        Returns:
            dict: Bảng mapping từ mã ma trận sang mô tả thay đổi
        """
        legend = {}

        # Mã 0 cho no-data/background
        legend[0] = "No Data"

        # Tạo tất cả các tổ hợp 4x4 = 16 tổ hợp
        for before_class, before_name in self.class_names.items():
            for after_class, after_name in self.class_names.items():
                # Mã hóa ma trận: before * 10 + after
                change_code = before_class * 10 + after_class

                if before_class == after_class:
                    # Không có thay đổi
                    legend[change_code] = f"Không đổi: {before_name}"
                else:
                    # Có thay đổi
                    legend[change_code] = f"{before_name} → {after_name}"

        return legend

    def preprocess_image(self, image_path):
        """
        Tiền xử lý ảnh để chuẩn bị cho phân loại

        Args:
            image_path (str): Đường dẫn đến ảnh

        Returns:
            tuple: (ảnh đã xử lý, metadata)
        """
        with rasterio.open(image_path) as src:
            # Đọc tất cả các bands
            image = src.read()

            # Chuyển từ (bands, height, width) sang (height, width, bands)
            image = np.transpose(image, (1, 2, 0))

            # Metadata
            metadata = {
                'transform': src.transform,
                'crs': src.crs,
                'width': src.width,
                'height': src.height,
                'count': src.count
            }

            return image, metadata

    def prepare_features(self, image):
        """
        Chuẩn bị features từ ảnh để đưa vào mô hình ML

        Args:
            image (numpy.ndarray): Ảnh đầu vào

        Returns:
            tuple: (features, valid_mask, (height, width))
        """
        if image.ndim == 3:
            height, width, bands = image.shape
            features = image.reshape(-1, bands)
        else:
            height, width = image.shape
            features = image.reshape(-1, 1)

        # Lọc bỏ các pixel có giá trị NaN hoặc không hợp lệ
        valid_mask = ~np.isnan(features).any(axis=1)

        return features, valid_mask, (height, width)

    def classify_land_cover(self, image_data):
        """
        Phân loại lớp phủ sử dụng ML model (bắt buộc)

        Args:
            image_data (numpy.ndarray): Dữ liệu ảnh (height, width, bands)

        Returns:
            numpy.ndarray: Ảnh đã được phân loại
        """
        if self.use_ml_model and self.model is not None:
            return self._classify_with_ml(image_data)
        else:
            raise ValueError("Cần có mô hình ML để thực hiện phân loại. Vui lòng cung cấp đường dẫn mô hình hợp lệ.")

    def _classify_with_ml(self, image_data):
        """
        Phân loại sử dụng mô hình Machine Learning

        Args:
            image_data (numpy.ndarray): Dữ liệu ảnh

        Returns:
            numpy.ndarray: Ảnh đã được phân loại
        """
        # Chuẩn bị features
        features, valid_mask, (height, width) = self.prepare_features(image_data)

        # Phân loại
        predictions = np.zeros(features.shape[0], dtype=int)
        valid_features = features[valid_mask]

        if len(valid_features) > 0:
            valid_predictions = self.model.predict(valid_features)
            predictions[valid_mask] = valid_predictions

        # Reshape về kích thước ảnh gốc
        classified_image = predictions.reshape(height, width)

        return classified_image

    def _encode_matrix_changes(self, before_classified, after_classified):
        """
        Mã hóa thay đổi theo hệ thống ma trận

        Args:
            before_classified (numpy.ndarray): Ảnh trước đã phân loại
            after_classified (numpy.ndarray): Ảnh sau đã phân loại

        Returns:
            numpy.ndarray: Bản đồ thay đổi với mã ma trận
        """
        change_map = np.zeros_like(before_classified, dtype=np.int16)

        # Áp dụng công thức ma trận: before * 10 + after
        valid_mask = (before_classified > 0) & (after_classified > 0)
        change_map[valid_mask] = (before_classified[valid_mask] * 10 +
                                 after_classified[valid_mask])

        return change_map

    def detect_changes(self, before_path, after_path):
        """
        Phát hiện thay đổi giữa hai ảnh với mã hóa ma trận

        Args:
            before_path (str): Đường dẫn ảnh trước
            after_path (str): Đường dẫn ảnh sau

        Returns:
            tuple: (ảnh trước phân loại, ảnh sau phân loại, bản đồ thay đổi, transform, crs)
        """
        print(f"🔍 Đang phân loại ảnh thời điểm trước: {before_path}")
        before_data, before_meta = self.preprocess_image(before_path)
        before_classified = self.classify_land_cover(before_data)

        print(f"🔍 Đang phân loại ảnh thời điểm sau: {after_path}")
        after_data, after_meta = self.preprocess_image(after_path)
        after_classified = self.classify_land_cover(after_data)

        print("📊 Đang mã hóa bản đồ thay đổi...")
        change_map = self._encode_matrix_changes(before_classified, after_classified)

        return before_classified, after_classified, change_map, before_meta['transform'], before_meta['crs']

    def analyze_changes(self, change_map, pixel_size_m2=100):
        """
        Phân tích thống kê các thay đổi với hệ thống ma trận

        Args:
            change_map (numpy.ndarray): Bản đồ biến động
            pixel_size_m2 (float): Diện tích mỗi pixel (m²)

        Returns:
            pandas.DataFrame: Bảng thống kê thay đổi
        """
        # Đếm số pixel cho mỗi loại thay đổi
        unique_values, counts = np.unique(change_map, return_counts=True)

        # Tạo DataFrame thống kê
        stats_data = []
        valid_pixels = np.sum(counts[unique_values != 0])

        for value, count in zip(unique_values, counts):
            if value == 0:
                continue  # Bỏ qua no-data

            # Tính toán thống kê
            percentage = (count / valid_pixels) * 100 if valid_pixels > 0 else 0
            area_ha = (count * pixel_size_m2) / 10000  # Chuyển m² sang hecta

            # Xác định loại thay đổi
            is_no_change = self._is_no_change(value)
            change_type = "Không đổi" if is_no_change else "Có thay đổi"

            stats_data.append({
                'Mã Ma Trận': value,
                'Mô tả thay đổi': self.change_legend.get(value, f"Không xác định ({value})"),
                'Loại Thay Đổi': change_type,
                'Số Pixel': count,
                'Tỷ lệ (%)': round(percentage, 2),
                'Diện tích (ha)': round(area_ha, 2)
            })

        df_stats = pd.DataFrame(stats_data)
        # Sắp xếp: Không đổi trước, sau đó theo số pixel giảm dần
        df_stats = df_stats.sort_values(['Loại Thay Đổi', 'Số Pixel'],
                                       ascending=[True, False])

        return df_stats

    def _is_no_change(self, change_code):
        """
        Kiểm tra xem mã thay đổi có phải là không đổi không

        Args:
            change_code (int): Mã thay đổi

        Returns:
            bool: True nếu không thay đổi
        """
        if change_code == 0:
            return True

        from_class = change_code // 10
        to_class = change_code % 10
        return from_class == to_class

    def _create_change_colormap(self):
        """
        Tạo colormap tùy chỉnh cho bản đồ thay đổi với màu sắc được định nghĩa bằng code Python
        Sử dụng style unique values như trong QGIS
        """
        # Danh sách tất cả các giá trị thay đổi có thể
        all_values = [0, 11, 12, 13, 14, 21, 22, 23, 24, 31, 32, 33, 34, 41, 42, 43, 44]

        # Định nghĩa bảng màu cho các lớp thay đổi (RGBA)
        # Mỗi loại thay đổi sẽ có một màu riêng biệt (R, G, B, A)
        # Sử dụng màu nhẹ hơn để không chói mắt
        color_mapping = {
            # No Data và các giá trị không đổi
            0: (0, 0, 0, 255),          # Đen - No Data
            11: (128, 128, 128, 255),   # Xám - Không đổi Đất trống
            22: (128, 128, 128, 255),   # Xám - Không đổi Thực vật
            33: (128, 128, 128, 255),   # Xám - Không đổi Nước
            44: (128, 128, 128, 255),   # Xám - Không đổi Xây dựng

            # Thay đổi từ Đất trống (1x)
            12: (144, 238, 144, 255),   # Xanh lá nhạt - Đất trống → Thực vật
            13: (135, 206, 235, 255),   # Xanh da trời nhạt - Đất trống → Nước
            14: (255, 182, 193, 255),   # Hồng nhạt - Đất trống → Xây dựng

            # Thay đổi từ Thực vật (2x)
            21: (255, 218, 185, 255),   # Cam nhạt - Thực vật → Đất trống
            23: (175, 238, 238, 255),   # Cyan nhạt - Thực vật → Nước
            24: (255, 192, 203, 255),   # Hồng phấn - Thực vật → Xây dựng

            # Thay đổi từ Nước (3x)
            31: (210, 180, 140, 255),   # Nâu nhạt - Nước → Đất trống
            32: (152, 251, 152, 255),   # Xanh lá cây nhạt - Nước → Thực vật
            34: (173, 216, 230, 255),   # Xanh dương nhạt - Nước → Xây dựng

            # Thay đổi từ Xây dựng (4x)
            41: (240, 128, 128, 255),   # Đỏ nhạt - Xây dựng → Đất trống
            42: (144, 238, 144, 255),   # Xanh lá nhạt - Xây dựng → Thực vật
            43: (176, 196, 222, 255),   # Xanh thép nhạt - Xây dựng → Nước
        }

        # Chuyển đổi từ RGBA sang hex colors cho matplotlib
        colors = []
        legend_patches = []

        for value in all_values:
            if value in color_mapping:
                r, g, b, a = color_mapping[value]
                hex_color = f'#{r:02x}{g:02x}{b:02x}'
                colors.append(hex_color)

                # Tạo legend patches
                if value == 0:
                    legend_patches.append(Patch(color=hex_color, label='No Data'))
                elif value in [11, 22, 33, 44]:
                    legend_patches.append(Patch(color=hex_color,
                                              label=f'Không đổi ({value})'))
                else:
                    legend_patches.append(Patch(color=hex_color,
                                              label=self.change_legend.get(value, f'Code {value}')))
            else:
                # Default color cho các giá trị không được định nghĩa
                colors.append('#CCCCCC')  # Xám nhạt
                legend_patches.append(Patch(color='#CCCCCC', label=f'Undefined ({value})'))

        # Tạo colormap và normalization
        cmap = ListedColormap(colors)
        norm = BoundaryNorm(boundaries=np.arange(len(all_values) + 1) - 0.5,
                          ncolors=len(all_values))

        return cmap, norm, legend_patches, all_values

    def create_colored_change_map(self, change_map, output_path, transform, crs, pixel_size_m2=100):
        """
        Tạo bản đồ thay đổi với màu sắc khác nhau cho từng loại thay đổi và lưu vào tệp TIFF.
        Sử dụng style unique values như trong QGIS.

        Args:
            change_map (numpy.ndarray): Mảng NumPy của kết quả thay đổi.
            output_path (str): Đường dẫn để lưu tệp TIFF kết quả.
            transform: Transform từ rasterio.
            crs: Coordinate reference system.
            pixel_size_m2 (float): Diện tích mỗi pixel (m²).
        """
        if change_map is None:
            print("❌ Lỗi: Kết quả thay đổi không hợp lệ. Không thể tạo ảnh màu.")
            return None

        # Định nghĩa bảng màu cho các lớp thay đổi (RGBA) - tương tự _create_change_colormap
        # Mỗi loại thay đổi sẽ có một màu riêng biệt (R, G, B, A)
        # Sử dụng màu nhẹ hơn để không chói mắt
        color_map = {
            # No Data và các giá trị không đổi
            0: (0, 0, 0, 255),          # Đen - No Data
            11: (128, 128, 128, 255),   # Xám - Không đổi Đất trống
            22: (128, 128, 128, 255),   # Xám - Không đổi Thực vật
            33: (128, 128, 128, 255),   # Xám - Không đổi Nước
            44: (128, 128, 128, 255),   # Xám - Không đổi Xây dựng

            # Thay đổi từ Đất trống (1x)
            12: (144, 238, 144, 255),   # Xanh lá nhạt - Đất trống → Thực vật
            13: (135, 206, 235, 255),   # Xanh da trời nhạt - Đất trống → Nước
            14: (255, 182, 193, 255),   # Hồng nhạt - Đất trống → Xây dựng

            # Thay đổi từ Thực vật (2x)
            21: (255, 218, 185, 255),   # Cam nhạt - Thực vật → Đất trống
            23: (175, 238, 238, 255),   # Cyan nhạt - Thực vật → Nước
            24: (255, 192, 203, 255),   # Hồng phấn - Thực vật → Xây dựng

            # Thay đổi từ Nước (3x)
            31: (210, 180, 140, 255),   # Nâu nhạt - Nước → Đất trống
            32: (152, 251, 152, 255),   # Xanh lá cây nhạt - Nước → Thực vật
            34: (173, 216, 230, 255),   # Xanh dương nhạt - Nước → Xây dựng

            # Thay đổi từ Xây dựng (4x)
            41: (240, 128, 128, 255),   # Đỏ nhạt - Xây dựng → Đất trống
            42: (144, 238, 144, 255),   # Xanh lá nhạt - Xây dựng → Thực vật
            43: (176, 196, 222, 255),   # Xanh thép nhạt - Xây dựng → Nước
        }

        # Tạo bản sao của dữ liệu thay đổi và chuyển đổi sang uint8
        # Đảm bảo giá trị nằm trong khoảng 0-255 để sử dụng với colormap
        data_uint8 = change_map.astype(np.uint8)

        # Tạo tên file cho ảnh màu với style unique values
        colored_output_path = output_path.replace('.tif', '_colored_unique_values.tif')

        height, width = change_map.shape

        try:
            with rasterio.open(colored_output_path, "w",
                             driver='GTiff',
                             height=height, width=width, count=1,
                             dtype=rasterio.uint8,  # Kiểu dữ liệu uint8 để sử dụng với colormap
                             transform=transform,
                             crs=crs,
                             nodata=0) as dst:  # Giá trị NoData

                # Ghi dữ liệu thay đổi
                dst.write(data_uint8, 1)

                # Áp dụng bảng màu (colormap) cho ảnh
                dst.write_colormap(1, color_map)

                # Thêm thông tin chú thích cho các lớp thay đổi
                dst.update_tags(
                    change_11="Không đổi: Đất trống",
                    change_12="Đất trống → Thực vật",
                    change_13="Đất trống → Nước",
                    change_14="Đất trống → Xây dựng",
                    change_21="Thực vật → Đất trống",
                    change_22="Không đổi: Thực vật",
                    change_23="Thực vật → Nước",
                    change_24="Thực vật → Xây dựng",
                    change_31="Nước → Đất trống",
                    change_32="Nước → Thực vật",
                    change_33="Không đổi: Nước",
                    change_34="Nước → Xây dựng",
                    change_41="Xây dựng → Đất trống",
                    change_42="Xây dựng → Thực vật",
                    change_43="Xây dựng → Nước",
                    change_44="Không đổi: Xây dựng"
                )

            print(f"✅ Bản đồ thay đổi với style unique values đã được lưu tại: {colored_output_path}")

            # Tạo chú giải màu sắc bên dưới ảnh
            combined_tiff_path = self._create_color_legend_image(colored_output_path, change_map, color_map, pixel_size_m2)

            return colored_output_path, combined_tiff_path

        except Exception as e:
            print(f"❌ Lỗi khi tạo bản đồ thay đổi với style unique values: {e}")
            return None

    def _create_color_legend_image(self, colored_output_path, change_map, color_map, pixel_size_m2=100):
        """
        Tạo ảnh chú giải màu sắc cho bản đồ thay đổi

        Args:
            colored_output_path (str): Đường dẫn file ảnh màu
            change_map (numpy.ndarray): Dữ liệu change map
            color_map (dict): Bảng màu sắc
            pixel_size_m2 (float): Diện tích mỗi pixel (m²)
        """
        try:
            import matplotlib.pyplot as plt
            import matplotlib.patches as patches
            from matplotlib.patches import Rectangle

            # Lấy các giá trị thực tế có trong change_map
            unique_values = np.unique(change_map)
            unique_values = unique_values[unique_values != 0]  # Loại bỏ NoData

            if len(unique_values) == 0:
                print("⚠️ Không có dữ liệu thay đổi để tạo chú giải")
                return

            # Tạo figure cho legend
            fig, ax = plt.subplots(figsize=(12, max(3, len(unique_values) * 0.3 + 1)))
            ax.set_xlim(0, 10)
            ax.set_ylim(0, len(unique_values) + 1)

            # Tắt các trục
            ax.set_xticks([])
            ax.set_yticks([])
            ax.spines['top'].set_visible(False)
            ax.spines['right'].set_visible(False)
            ax.spines['bottom'].set_visible(False)
            ax.spines['left'].set_visible(False)

            # Tiêu đề
            plt.title('Chú Giải Màu Sắc - Bản Đồ Thay Đổi Lớp Phủ Mặt Đất',
                     fontsize=14, fontweight='bold', pad=20)

            # Vẽ legend cho từng giá trị
            y_pos = len(unique_values)
            for value in sorted(unique_values):
                if value in color_map:
                    r, g, b, a = color_map[value]
                    color = f'#{r:02x}{g:02x}{b:02x}'

                    # Vẽ hình chữ nhật màu
                    rect = Rectangle((0.5, y_pos - 0.4), 0.8, 0.3,
                                   facecolor=color, edgecolor='black', linewidth=0.5)
                    ax.add_patch(rect)

                    # Thêm text mô tả
                    description = self.change_legend.get(value, f"Mã {value}")

                    # Thêm thông tin diện tích và tỷ lệ
                    pixel_count = np.sum(change_map == value)
                    total_pixels = np.sum(change_map > 0)
                    percentage = (pixel_count / total_pixels * 100) if total_pixels > 0 else 0

                    # Tính diện tích (hecta)
                    area_ha = (pixel_count * pixel_size_m2) / 10000

                    full_text = f"Mã {value}: {description} ({area_ha:.2f} ha - {percentage:.1f}%)"
                    ax.text(1.5, y_pos - 0.25, full_text, fontsize=10, va='center')

                y_pos -= 1

            # Thêm thông tin tổng quan
            total_pixels = np.sum(change_map > 0)
            no_change_pixels = np.sum(np.isin(change_map, [11, 22, 33, 44]))
            change_pixels = total_pixels - no_change_pixels

            # Tính diện tích tổng
            total_area_ha = (total_pixels * pixel_size_m2) / 10000
            no_change_area_ha = (no_change_pixels * pixel_size_m2) / 10000
            change_area_ha = (change_pixels * pixel_size_m2) / 10000

            summary_text = f"""
Tổng quan:
• Tổng diện tích: {total_area_ha:.2f} ha
• Không thay đổi: {no_change_area_ha:.2f} ha ({no_change_pixels/total_pixels*100:.1f}%)
• Có thay đổi: {change_area_ha:.2f} ha ({change_pixels/total_pixels*100:.1f}%)
            """.strip()

            ax.text(0.5, -0.5, summary_text, fontsize=9, va='top',
                   bbox=dict(boxstyle="round,pad=0.3", facecolor='lightgray', alpha=0.7))

            # Tạo legend tạm thời trong memory (không lưu file)
            import io
            buf = io.BytesIO()
            plt.tight_layout()
            plt.savefig(buf, format='png', dpi=300, bbox_inches='tight',
                       facecolor='white', edgecolor='none')
            buf.seek(0)
            plt.close()

            print(f"✅ Đã tạo chú giải màu sắc trong memory")

            # Tạo ảnh kết hợp (ảnh chính + legend) - chỉ file TIFF
            combined_tiff_path = self._create_combined_image_with_legend(colored_output_path, buf)

            return combined_tiff_path

        except Exception as e:
            print(f"❌ Lỗi khi tạo chú giải màu sắc: {e}")
            return None

    def _create_combined_image_with_legend(self, colored_output_path, legend_buffer):
        """
        Tạo ảnh kết hợp giữa bản đồ màu và chú giải

        Args:
            colored_output_path (str): Đường dẫn file ảnh màu
            legend_buffer (io.BytesIO): Buffer chứa ảnh legend
        """
        try:
            import matplotlib.pyplot as plt
            import matplotlib.image as mpimg
            from PIL import Image
            import rasterio
            from rasterio.transform import from_bounds

            # Đọc dữ liệu raster
            with rasterio.open(colored_output_path) as src:
                raster_data = src.read(1)
                colormap = src.colormap(1)
                original_transform = src.transform
                original_crs = src.crs

            # Chuyển đổi raster thành ảnh RGB
            rgb_array = np.zeros((raster_data.shape[0], raster_data.shape[1], 3), dtype=np.uint8)
            for value, (r, g, b, a) in colormap.items():
                mask = raster_data == value
                rgb_array[mask] = [r, g, b]

            # Đọc legend từ buffer
            from PIL import Image
            legend_buffer.seek(0)
            legend_pil = Image.open(legend_buffer)
            legend_img = np.array(legend_pil) / 255.0  # Normalize về 0-1 cho matplotlib

            # Tạo figure kết hợp
            fig = plt.figure(figsize=(16, 12))

            # Vẽ bản đồ chính (70% diện tích)
            ax_main = plt.subplot2grid((4, 1), (0, 0), rowspan=3)
            ax_main.imshow(rgb_array)
            ax_main.set_title('Bản Đồ Thay Đổi Lớp Phủ Mặt Đất', fontsize=16, fontweight='bold')
            ax_main.set_xlabel('Pixel X')
            ax_main.set_ylabel('Pixel Y')

            # Vẽ legend (30% diện tích)
            ax_legend = plt.subplot2grid((4, 1), (3, 0))
            ax_legend.imshow(legend_img)
            ax_legend.axis('off')

            plt.tight_layout()

            # Chỉ tạo ảnh kết hợp TIFF với georeference (không lưu PNG)
            combined_tiff_path = self._create_combined_geotiff(
                rgb_array, legend_img, original_transform, original_crs, colored_output_path
            )

            if combined_tiff_path:
                print(f"✅ Đã tạo ảnh kết hợp GeoTIFF tại: {combined_tiff_path}")
                plt.close()
                return combined_tiff_path

            plt.close()
            return None

        except Exception as e:
            print(f"❌ Lỗi khi tạo ảnh kết hợp: {e}")
            return None

    def _create_combined_geotiff(self, rgb_array, legend_img, original_transform, original_crs, colored_output_path):
        """
        Tạo file GeoTIFF kết hợp bản đồ và legend với georeference

        Args:
            rgb_array (numpy.ndarray): Dữ liệu RGB của bản đồ
            legend_img (numpy.ndarray): Ảnh legend
            original_transform: Transform gốc
            original_crs: CRS gốc
            colored_output_path (str): Đường dẫn file gốc
        """
        try:
            # Resize legend để phù hợp với chiều rộng của bản đồ
            from PIL import Image

            # Chuyển legend thành PIL Image và resize
            legend_pil = Image.fromarray((legend_img * 255).astype(np.uint8))
            legend_height = int(rgb_array.shape[0] * 0.3)  # Legend chiếm 30% chiều cao
            legend_resized = legend_pil.resize((rgb_array.shape[1], legend_height), Image.Resampling.LANCZOS)
            legend_array = np.array(legend_resized)

            # Nếu legend có 4 channels (RGBA), chuyển về 3 channels (RGB)
            if legend_array.shape[2] == 4:
                # Composite với nền trắng
                alpha = legend_array[:, :, 3:4] / 255.0
                legend_rgb = legend_array[:, :, :3] * alpha + 255 * (1 - alpha)
                legend_array = legend_rgb.astype(np.uint8)
            elif legend_array.shape[2] == 3:
                # Đã là RGB, không cần thay đổi
                pass

            # Kết hợp bản đồ và legend theo chiều dọc
            combined_height = rgb_array.shape[0] + legend_height
            combined_array = np.zeros((combined_height, rgb_array.shape[1], 3), dtype=np.uint8)

            # Đặt bản đồ ở phía trên
            combined_array[:rgb_array.shape[0], :, :] = rgb_array

            # Đặt legend ở phía dưới
            combined_array[rgb_array.shape[0]:, :, :] = legend_array

            # Tính toán transform mới cho ảnh kết hợp
            # Tỷ lệ thay đổi pixel size để giữ nguyên tọa độ địa lý
            scale_factor = combined_height / rgb_array.shape[0]
            new_pixel_size_x = original_transform.a * scale_factor
            new_pixel_size_y = original_transform.e * scale_factor

            # Transform mới với pixel size được điều chỉnh
            new_transform = rasterio.transform.Affine(
                new_pixel_size_x, original_transform.b, original_transform.c,
                original_transform.d, new_pixel_size_y, original_transform.f
            )

            # Lưu file GeoTIFF
            combined_tiff_path = colored_output_path.replace('.tif', '_with_legend.tif')

            with rasterio.open(
                combined_tiff_path, 'w',
                driver='GTiff',
                height=combined_height,
                width=rgb_array.shape[1],
                count=3,
                dtype=rasterio.uint8,
                crs=original_crs,
                transform=new_transform,
                compress='lzw'
            ) as dst:
                # Ghi 3 bands RGB
                for i in range(3):
                    dst.write(combined_array[:, :, i], i + 1)

                # Thêm metadata
                dst.update_tags(
                    title="Bản đồ thay đổi lớp phủ mặt đất với chú giải",
                    description="Kết hợp bản đồ thay đổi và chú giải màu sắc",
                    created_by="vGeoInt_v2 AI Motion Detection"
                )

            return combined_tiff_path

        except Exception as e:
            print(f"❌ Lỗi khi tạo GeoTIFF kết hợp: {e}")
            return None

    def visualize_results(self, before_classified, after_classified, change_map, save_path=None):
        """
        Trực quan hóa kết quả phát hiện thay đổi với colormap tùy chỉnh

        Args:
            before_classified (numpy.ndarray): Ảnh trước đã phân loại
            after_classified (numpy.ndarray): Ảnh sau đã phân loại
            change_map (numpy.ndarray): Bản đồ biến động
            save_path (str): Đường dẫn lưu ảnh (optional)
        """
        # Tạo colormap tùy chỉnh
        cmap, norm, legend_patches, all_values = self._create_change_colormap()

        fig, axes = plt.subplots(2, 2, figsize=(18, 14))

        # Ảnh trước phân loại
        im1 = axes[0, 0].imshow(before_classified, cmap='viridis')
        axes[0, 0].set_title('Phân loại thời điểm trước', fontsize=12, fontweight='bold')
        axes[0, 0].set_xlabel('Pixel X')
        axes[0, 0].set_ylabel('Pixel Y')
        plt.colorbar(im1, ax=axes[0, 0], shrink=0.7)

        # Ảnh sau phân loại
        im2 = axes[0, 1].imshow(after_classified, cmap='viridis')
        axes[0, 1].set_title('Phân loại thời điểm sau', fontsize=12, fontweight='bold')
        axes[0, 1].set_xlabel('Pixel X')
        axes[0, 1].set_ylabel('Pixel Y')
        plt.colorbar(im2, ax=axes[0, 1], shrink=0.7)

        # Bản đồ biến động với colormap tùy chỉnh
        change_map_indexed = np.zeros_like(change_map)
        for i, value in enumerate(all_values):
            change_map_indexed[change_map == value] = i

        im3 = axes[1, 0].imshow(change_map_indexed, cmap=cmap, norm=norm)
        axes[1, 0].set_title('Bản đồ biến động (Màu xám: Không đổi)', fontsize=12, fontweight='bold')
        axes[1, 0].set_xlabel('Pixel X')
        axes[1, 0].set_ylabel('Pixel Y')

        # Histogram các loại thay đổi
        unique_values, counts = np.unique(change_map, return_counts=True)
        bar_colors = []
        for val in unique_values:
            if val in all_values:
                idx = all_values.index(val)
                bar_colors.append(cmap.colors[idx])
            else:
                bar_colors.append('#CCCCCC')

        bars = axes[1, 1].bar(unique_values, counts, color=bar_colors, edgecolor='black', linewidth=0.5)
        axes[1, 1].set_title('Histogram các loại thay đổi', fontsize=12, fontweight='bold')
        axes[1, 1].set_xlabel('Mã thay đổi')
        axes[1, 1].set_ylabel('Số pixel')
        axes[1, 1].tick_params(axis='x', rotation=45)

        # Thêm nhãn cho các cột
        for bar, val in zip(bars, unique_values):
            height = bar.get_height()
            if val in self.change_legend:
                label = self.change_legend[val]
                if len(label) > 20:
                    label = label[:17] + "..."
                axes[1, 1].text(bar.get_x() + bar.get_width()/2., height + counts.max()*0.01,
                               f'{val}\n{label}', ha='center', va='bottom', fontsize=7, rotation=0)

        plt.tight_layout()

        if save_path:
            plt.savefig(save_path, dpi=300, bbox_inches='tight')
            print(f"Đã lưu kết quả trực quan hóa tại: {save_path}")

        # In thống kê
        self._print_change_statistics(change_map)

    def _print_change_statistics(self, change_map):
        """In thống kê màu sắc bảng đồ thay đổi"""
        unique_values, counts = np.unique(change_map, return_counts=True)

        print("\n" + "="*80)
        print("🎨 THỐNG KÊ MÀU SẮC BẢNG ĐỒ THAY ĐỔI")
        print("="*80)
        print("🔘 MÀU XÁM: Không thay đổi (11, 22, 33, 44)")
        print("🌈 MÀU RIÊNG BIỆT: Mỗi loại thay đổi có màu khác nhau")
        print("\n📊 PHÂN BỐ PIXEL:")

        no_change_count = 0
        change_count = 0

        for val, count in zip(unique_values, counts):
            if val in [11, 22, 33, 44]:
                no_change_count += count
            elif val != 0:  # Loại trừ No Data
                change_count += count

        total_pixels = no_change_count + change_count
        if total_pixels > 0:
            print(f"   • Không thay đổi: {no_change_count:,} pixel ({no_change_count/total_pixels*100:.1f}%)")
            print(f"   • Có thay đổi: {change_count:,} pixel ({change_count/total_pixels*100:.1f}%)")
            print(f"   • Tổng cộng: {total_pixels:,} pixel")
        print("="*80)

    def save_change_map(self, change_map, output_path, transform, crs, pixel_size_m2=100):
        """
        Lưu bản đồ thay đổi với nhiều format khác nhau

        Args:
            change_map (numpy.ndarray): Bản đồ thay đổi
            output_path (str): Đường dẫn file đầu ra
            transform: Transform từ rasterio
            crs: Coordinate reference system
            pixel_size_m2 (float): Diện tích mỗi pixel (m²)
        """
        height, width = change_map.shape

        # Tạo bản đồ thay đổi với màu sắc (style unique values)
        colored_path = self.create_colored_change_map(change_map, output_path, transform, crs, pixel_size_m2)

        return colored_path



    def get_change_matrix_table(self):
        """
        Trả về bảng ma trận thay đổi dưới dạng DataFrame

        Returns:
            pandas.DataFrame: Ma trận thay đổi 4x4
        """
        matrix_data = []
        classes = [1, 2, 3, 4]
        class_names = ["Đất trống", "Thảm thực vật", "Nước", "Xây dựng"]

        for i, from_class in enumerate(classes):
            row_data = {'Từ\\Đến': class_names[i]}
            for j, to_class in enumerate(classes):
                change_code = from_class * 10 + to_class
                row_data[class_names[j]] = change_code
            matrix_data.append(row_data)

        return pd.DataFrame(matrix_data)

    def print_change_matrix(self):
        """In bảng ma trận mã hóa"""
        print("\n🔢 BẢNG MA TRẬN MÃ HÓA THAY ĐỔI")
        print("=" * 60)

        matrix_df = self.get_change_matrix_table()
        print(matrix_df.to_string(index=False))

        print(f"\n📋 CHÚ THÍCH:")
        print("   • Mã có 2 chữ số: XY")
        print("   • X = Lớp trước (1-4)")
        print("   • Y = Lớp sau (1-4)")
        print("   • Đường chéo (11,22,33,44) = Không thay đổi")
        print("   • Ngoài đường chéo = Có thay đổi")

        print(f"\n🎯 VÍ DỤ:")
        print("   • Mã 12: Đất trống → Thảm thực vật")
        print("   • Mã 33: Nước → Nước (không đổi)")
        print("   • Mã 41: Xây dựng → Đất trống")


def main():
    """
    Hàm chính - Enhanced version based on example_usage.py
    """
    # Fix Windows console encoding issues
    import sys
    import os
    if os.name == 'nt':  # Windows
        try:
            # Set console to UTF-8
            os.system('chcp 65001 > nul')
            sys.stdout.reconfigure(encoding='utf-8', errors='replace')
            sys.stderr.reconfigure(encoding='utf-8', errors='replace')
        except:
            # Fallback if reconfigure fails
            import codecs
            sys.stdout = codecs.getwriter('utf-8')(sys.stdout.detach(), errors='replace')
            sys.stderr = codecs.getwriter('utf-8')(sys.stderr.detach(), errors='replace')

    parser = argparse.ArgumentParser(description='AI Motion Detection for vGeoInt_v2 - ML Only Version')
    parser.add_argument('--before', required=True, help='Đường dẫn ảnh trước')
    parser.add_argument('--after', required=True, help='Đường dẫn ảnh sau')
    parser.add_argument('--output', required=True, help='Đường dẫn file kết quả')
    parser.add_argument('--model', required=True, help='Đường dẫn đến mô hình ML (.joblib) - BẮT BUỘC')
    parser.add_argument('--stats', action='store_true', help='Tạo file thống kê')
    parser.add_argument('--summary', action='store_true', help='Hiển thị tóm tắt')
    parser.add_argument('--visualize', action='store_true', help='Tạo biểu đồ trực quan')

    args = parser.parse_args()

    # Kiểm tra file input
    if not os.path.exists(args.before):
        print(f"❌ Không tìm thấy ảnh trước tại: {args.before}")
        sys.exit(1)

    if not os.path.exists(args.after):
        print(f"❌ Không tìm thấy ảnh sau tại: {args.after}")
        sys.exit(1)

    try:
        print("=== HE THONG PHAT HIEN THAY DOI LOP PHU MAT DAT - PHIEN BAN AI/ML ===")
        print("=" * 80)
        print("*** CHI SU DUNG MO HINH MACHINE LEARNING - KHONG CO FALLBACK METHOD ***")
        print("=" * 80)

        # Khởi tạo detector
        detector = LandCoverChangeDetector(args.model)

        # Hiển thị bảng chú thích
        if args.summary:
            print("\nBẢNG CHÚ THÍCH BIẾN ĐỔI:")
            print("=" * 60)
            for value, description in sorted(detector.change_legend.items()):
                if value != 0:  # Bỏ qua No Data
                    change_type = "Không đổi" if detector._is_no_change(value) else "Có thay đổi"
                    print(f"Giá trị {value:2d}: {description:30s} [{change_type}]")
            print()

        # Thực hiện phát hiện thay đổi
        print("🔍 Bắt đầu quá trình phát hiện thay đổi...")
        before_classified, after_classified, change_map, transform, crs = detector.detect_changes(
            args.before, args.after
        )

        # Lưu kết quả chính
        # Tính pixel size từ transform (m²)
        pixel_size_x = abs(transform.a)  # Kích thước pixel theo x (đơn vị map units)
        pixel_size_y = abs(transform.e)  # Kích thước pixel theo y (đơn vị map units)
        pixel_size_m2 = pixel_size_x * pixel_size_y  # Diện tích pixel (m²)

        colored_output_path, combined_tiff_path = detector.save_change_map(
            change_map, args.output, transform, crs, pixel_size_m2
        )

        # In đường dẫn outputs để C++ có thể đọc
        if colored_output_path:
            print(f"COLORED_OUTPUT_PATH: {colored_output_path}")

        if combined_tiff_path:
            print(f"COMBINED_TIFF_PATH: {combined_tiff_path}")

        # Phân tích thống kê nếu được yêu cầu
        if args.stats:
            print("📊 Đang phân tích thống kê...")
            stats_df = detector.analyze_changes(change_map)

            # Lưu thống kê
            stats_path = args.output.replace('.tif', '_statistics.csv')
            stats_df.to_csv(stats_path, index=False, encoding='utf-8-sig')

            print(f"\n📈 THỐNG KÊ THAY ĐỔI LỚP PHỦ MẶT ĐẤT:")
            print("=" * 80)
            print(stats_df.head(10).to_string(index=False))
            print(f"\n💾 Đã lưu thống kê chi tiết tại: {stats_path}")

        # # Trực quan hóa kết quả
        # if args.visualize:
        #     print("🎨 Đang tạo biểu đồ trực quan...")
        #     viz_path = args.output.replace('.tif', '_visualization.png')
        #     detector.visualize_results(
        #         before_classified, after_classified, change_map,
        #         save_path=viz_path
        #     )

        # Tóm tắt nếu được yêu cầu
        if args.summary:
            unique_values, counts = np.unique(change_map, return_counts=True)

            # Tính toán các pixel không thay đổi vs có thay đổi
            no_change_pixels = 0
            change_pixels = 0

            for val, count in zip(unique_values, counts):
                if val in [11, 22, 33, 44]:  # Ma trận đường chéo = không đổi
                    no_change_pixels += count
                elif val != 0:  # Bỏ qua No Data
                    change_pixels += count

            total_pixels = no_change_pixels + change_pixels

            print(f"\n📋 TÓM TẮT KẾT QUẢ:")
            print("=" * 50)
            print(f"Kích thước ảnh: {change_map.shape}")
            print(f"Tổng số pixel: {total_pixels:,}")
            print(f"Pixel không thay đổi: {no_change_pixels:,} ({no_change_pixels/total_pixels*100:.2f}%)")
            print(f"Pixel có thay đổi: {change_pixels:,} ({change_pixels/total_pixels*100:.2f}%)")

            # Top 5 thay đổi phổ biến nhất (nếu có stats)
            if args.stats:
                stats_df = detector.analyze_changes(change_map)
                change_stats = stats_df[stats_df['Loại Thay Đổi'] == 'Có thay đổi']

                if not change_stats.empty:
                    print(f"\n🏆 TOP 5 THAY ĐỔI PHỔ BIẾN NHẤT:")
                    print("-" * 40)
                    top_changes = change_stats.head(5)
                    for _, row in top_changes.iterrows():
                        print(f"• {row['Mô tả thay đổi']}: {row['Tỷ lệ (%)']}% ({row['Diện tích (ha)']} ha)")

        # In bảng ma trận mã hóa
        if args.summary:
            detector.print_change_matrix()

        print(f"\n✅ Hoàn thành! Kết quả chính lưu tại: {args.output}")

    except Exception as e:
        print(f"*** LOI: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
if __name__ == "__main__":
    main()
