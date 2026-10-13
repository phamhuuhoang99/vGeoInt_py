#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Ship Detection Script for vGeoInt_v2
Detects ships in images using YOLO model and outputs results as Shapefile or annotated image
Enhanced with detailed logging for real-time progress tracking
Fixed Unicode encoding issues for Windows console
"""

import argparse
import sys
import os
import cv2
import numpy as np
from pathlib import Path
import warnings
import time
import locale

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
        safe_message = message.replace('✓', '[OK]').replace('❌', '[ERROR]').replace('⚠️', '[WARN]')
        print(safe_message, file=sys.stderr, flush=flush)
    except UnicodeEncodeError:
        ascii_message = message.encode('ascii', errors='replace').decode('ascii')
        print(ascii_message, file=sys.stderr, flush=flush)

# Check dependencies with better error handling
DEPENDENCIES_AVAILABLE = True
missing_deps = []

try:
    import torch
    log_progress("[OK] PyTorch loaded successfully")
except ImportError as e:
    missing_deps.append("torch")
    log_error(f"Missing PyTorch: {e}")

try:
    from ultralytics import YOLO
    log_progress("[OK] Ultralytics YOLO loaded successfully")
except ImportError as e:
    missing_deps.append("ultralytics")
    log_error(f"Missing Ultralytics: {e}")

try:
    import rasterio
    log_progress("[OK] Rasterio loaded successfully")
except ImportError as e:
    missing_deps.append("rasterio")
    log_error(f"Missing Rasterio: {e}")

try:
    import geopandas as gpd
    from shapely.geometry import box
    import pandas as pd
    log_progress("[OK] GeoPandas and Shapely loaded successfully")
except ImportError as e:
    missing_deps.append("geopandas/shapely")
    log_error(f"Missing GeoPandas/Shapely: {e}")

if missing_deps:
    DEPENDENCIES_AVAILABLE = False
    log_error(f"Missing dependencies: {', '.join(missing_deps)}")
    log_error("Please install required packages:")
    log_error("pip install torch ultralytics opencv-python rasterio geopandas shapely pandas")
else:
    log_progress("[OK] All Python dependencies loaded successfully")

def is_geotiff(image_path):
    """Check if image is a GeoTIFF with coordinate information"""
    try:
        log_progress(f"Checking if {os.path.basename(image_path)} is a GeoTIFF...")
        with rasterio.open(image_path) as src:
            has_crs = src.crs is not None
            has_transform = src.transform is not None
            result = has_crs and has_transform
            if result:
                log_progress(f"[OK] Confirmed GeoTIFF with CRS: {src.crs}")
            else:
                log_progress("[OK] Regular image file detected")
            return result
    except Exception as e:
        log_progress(f"Could not read spatial info: {e}")
        return False

def load_model(model_path):
    """Load YOLO model with CPU optimization and safe logging"""
    try:
        log_progress(f"Loading model: {model_path}")

        # Check if model file exists
        if not os.path.exists(model_path):
            log_error(f"Model file not found: {model_path}")
            return None

        model_size = os.path.getsize(model_path) / (1024 * 1024)  # MB
        log_progress(f"Model size: {model_size:.1f} MB")

        start_time = time.time()

        # Use ultralytics YOLO with CPU optimization
        log_progress("Initializing YOLO model with ultralytics...")

        # Force CPU usage for consistent behavior
        device = 'cpu'
        log_progress(f"Using device: {device}")

        model = YOLO(model_path)

        # Optimize for CPU inference
        if hasattr(model, 'model'):
            # Set model to evaluation mode for better CPU performance
            model.model.eval()

            # Enable CPU optimizations
            try:
                import torch
                torch.set_num_threads(os.cpu_count())  # Use all CPU cores
                log_progress(f"Using {os.cpu_count()} CPU threads")

                # Enable CPU optimizations if available
                if hasattr(torch.backends, 'mkldnn') and torch.backends.mkldnn.is_available():
                    torch.backends.mkldnn.enabled = True
                    log_progress("[OK] MKL-DNN acceleration enabled")

            except Exception as opt_error:
                log_progress(f"CPU optimization setup: {opt_error}")

        load_time = time.time() - start_time

        log_progress(f"[OK] Model loaded successfully in {load_time:.2f} seconds")
        log_progress(f"Model type: {type(model).__name__}")

        # Test model with a dummy prediction to ensure it's working
        try:
            log_progress("Testing model with dummy input...")
            # Create a small test image for CPU testing
            test_img = np.zeros((320, 320, 3), dtype=np.uint8)  # Smaller test image for CPU
            test_results = model(test_img, verbose=False, device=device)
            log_progress("[OK] Model test successful on CPU")
        except Exception as test_error:
            log_error(f"Model test failed: {test_error}")
            return None

        return model

    except Exception as e:
        log_error(f"Error loading model: {e}")
        log_error(f"Error type: {type(e).__name__}")
        return None

def detect_ships(model, image_path, confidence_threshold=0.5):
    """Detect ships in image using YOLO model with safe logging"""
    try:
        log_progress(f"Processing image: {image_path}")

        # Check image file
        if not os.path.exists(image_path):
            log_error(f"Image file not found: {image_path}")
            return []

        # Get image info using cv2 first
        try:
            img = cv2.imread(image_path)
            if img is None:
                log_error(f"Could not read image with OpenCV: {image_path}")
                return []
            height, width = img.shape[:2]
            log_progress(f"Image dimensions: {width}x{height}")
            log_progress(f"Image channels: {img.shape[2] if len(img.shape) > 2 else 1}")
        except Exception as e:
            log_error(f"Error reading image info: {e}")
            return []

        log_progress(f"Running inference with confidence threshold: {confidence_threshold}")
        start_time = time.time()

        # Run inference with ultralytics YOLO
        try:
            results = model(image_path, conf=confidence_threshold, verbose=False)
            inference_time = time.time() - start_time
            log_progress(f"[OK] Inference completed in {inference_time:.2f} seconds")
        except Exception as inference_error:
            log_error(f"Inference failed: {inference_error}")
            log_error(f"Inference error type: {type(inference_error).__name__}")
            return []

        detections = []

        # Process results from ultralytics YOLO
        for result in results:
            if result.boxes is not None and len(result.boxes) > 0:
                log_progress(f"Found {len(result.boxes)} potential detections")

                for i, box in enumerate(result.boxes):
                    try:
                        # Get bounding box coordinates (xyxy format)
                        coords = box.xyxy[0].cpu().numpy()
                        x1, y1, x2, y2 = coords

                        # Get confidence and class
                        confidence = float(box.conf[0].cpu().numpy())
                        class_id = int(box.cls[0].cpu().numpy())

                        # Calculate detection area
                        width_px = abs(x2 - x1)
                        height_px = abs(y2 - y1)
                        area_px = width_px * height_px

                        detection = {
                            'x1': float(x1),
                            'y1': float(y1),
                            'x2': float(x2),
                            'y2': float(y2),
                            'confidence': confidence,
                            'class_id': class_id,
                            'area_pixels': area_px
                        }

                        detections.append(detection)
                        log_progress(f"  Detection {i+1}: confidence={confidence:.3f}, area={area_px:.0f}px2")

                    except Exception as box_error:
                        log_error(f"Error processing detection {i+1}: {box_error}")
                        continue
            else:
                log_progress("No detections found in this result")

        log_progress(f"Total ships detected: {len(detections)}")

        if len(detections) == 0:
            log_progress("No ships detected in the image")
        else:
            # Sort by confidence
            detections.sort(key=lambda x: x['confidence'], reverse=True)
            best_detection = detections[0]
            log_progress(f"Best detection: confidence={best_detection['confidence']:.3f}")

        return detections

    except Exception as e:
        log_error(f"Error during detection: {e}")
        log_error(f"Detection error type: {type(e).__name__}")
        return []

def create_shapefile(detections, image_path, output_path):
    """Create shapefile from detections for GeoTIFF input with safe logging"""
    try:
        log_progress("Input is GeoTIFF - creating shapefile output")
        log_progress(f"Reading spatial information from: {os.path.basename(image_path)}")

        with rasterio.open(image_path) as src:
            transform = src.transform
            crs = src.crs
            bounds = src.bounds
            pixel_size = src.res

            log_progress(f"CRS: {crs}")
            log_progress(f"Pixel size: {pixel_size[0]:.6f} x {pixel_size[1]:.6f}")
            log_progress(f"Image bounds: {bounds}")

        geometries = []
        attributes = []

        log_progress(f"Converting {len(detections)} detections to geographic coordinates...")

        for i, detection in enumerate(detections):
            # Convert pixel coordinates to geographic coordinates
            x1, y1 = rasterio.transform.xy(transform, detection['y1'], detection['x1'])
            x2, y2 = rasterio.transform.xy(transform, detection['y2'], detection['x2'])

            # Create bounding box geometry
            min_x, max_x = min(x1, x2), max(x1, x2)
            min_y, max_y = min(y1, y2), max(y1, y2)
            geometry = box(min_x, min_y, max_x, max_y)

            # Calculate real-world area
            area_sqm = geometry.area
            width_m = max_x - min_x
            height_m = max_y - min_y

            geometries.append(geometry)

            attributes.append({
                'ship_id': i + 1,
                'confidence': round(detection['confidence'], 4),
                'class_id': detection['class_id'],
                'area_sqm': round(area_sqm, 2),
                'width_m': round(width_m, 2),
                'height_m': round(height_m, 2),
                'area_pixels': int(detection['area_pixels'])
            })

            log_progress(f"  Ship {i+1}: {width_m:.1f}m x {height_m:.1f}m, area={area_sqm:.1f}m2")

        if geometries:
            log_progress("Creating GeoDataFrame...")
            # Create GeoDataFrame
            gdf = gpd.GeoDataFrame(attributes, geometry=geometries, crs=crs)

            # Ensure output directory exists
            output_dir = os.path.dirname(output_path)
            if not os.path.exists(output_dir):
                os.makedirs(output_dir)
                log_progress(f"Created output directory: {output_dir}")

            log_progress(f"Saving shapefile: {output_path}")
            # Save as shapefile
            gdf.to_file(output_path, driver='ESRI Shapefile')

            # Verify output files
            base_name = os.path.splitext(output_path)[0]
            expected_files = ['.shp', '.shx', '.dbf', '.prj']
            created_files = []

            for ext in expected_files:
                file_path = base_name + ext
                if os.path.exists(file_path):
                    size_kb = os.path.getsize(file_path) / 1024
                    created_files.append(f"{os.path.basename(file_path)} ({size_kb:.1f} KB)")

            log_progress(f"Shapefile created: {output_path}")
            log_progress(f"Created files: {', '.join(created_files)}")
            log_progress(f"Total ships detected: {len(detections)}")

        else:
            log_progress("No ships detected - creating empty shapefile")
            # Create empty shapefile
            empty_gdf = gpd.GeoDataFrame(
                columns=['ship_id', 'confidence', 'class_id', 'area_sqm', 'width_m', 'height_m', 'area_pixels'],
                geometry=[], crs=crs
            )
            empty_gdf.to_file(output_path, driver='ESRI Shapefile')
            log_progress(f"Empty shapefile created: {output_path}")

    except Exception as e:
        log_error(f"Error creating shapefile: {e}")
        sys.exit(1)

def create_annotated_image(detections, image_path, output_path):
    """Create annotated image with bounding boxes for regular images with safe logging"""
    try:
        log_progress("Input is regular image - creating annotated image output")
        log_progress(f"Loading image: {os.path.basename(image_path)}")

        # Load image
        image = cv2.imread(image_path)
        if image is None:
            log_error(f"Error loading image: {image_path}")
            sys.exit(1)

        original_height, original_width = image.shape[:2]
        log_progress(f"Original image size: {original_width}x{original_height}")

        # Ensure output directory exists
        output_dir = os.path.dirname(output_path)
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
            log_progress(f"Created output directory: {output_dir}")

        log_progress(f"Drawing {len(detections)} bounding boxes...")

        # Draw bounding boxes
        for i, detection in enumerate(detections):
            x1, y1, x2, y2 = int(detection['x1']), int(detection['y1']), int(detection['x2']), int(detection['y2'])
            confidence = detection['confidence']

            # Ensure coordinates are within image bounds
            x1 = max(0, min(x1, original_width))
            x2 = max(0, min(x2, original_width))
            y1 = max(0, min(y1, original_height))
            y2 = max(0, min(y2, original_height))

            # Calculate box dimensions
            box_width = abs(x2 - x1)
            box_height = abs(y2 - y1)

            # Draw rectangle with thickness based on image size
            thickness = max(1, min(original_width, original_height) // 500)
            cv2.rectangle(image, (x1, y1), (x2, y2), (0, 255, 0), thickness)

            # Draw label with adaptive font size
            label = f"Ship {i+1}: {confidence:.2f}"
            font_scale = max(0.4, min(original_width, original_height) / 2000)
            font_thickness = max(1, thickness // 2)

            label_size = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, font_scale, font_thickness)[0]

            # Draw label background
            label_y = max(y1 - 5, label_size[1] + 5)
            cv2.rectangle(image, (x1, label_y - label_size[1] - 5),
                         (x1 + label_size[0] + 5, label_y + 5), (0, 255, 0), -1)

            # Draw label text
            cv2.putText(image, label, (x1 + 2, label_y),
                       cv2.FONT_HERSHEY_SIMPLEX, font_scale, (0, 0, 0), font_thickness)

            log_progress(f"  Drew box {i+1}: ({x1},{y1}) to ({x2},{y2}), size={box_width}x{box_height}")

        # Save annotated image
        log_progress(f"Saving annotated image: {output_path}")
        success = cv2.imwrite(output_path, image)

        if success:
            # Verify output file
            if os.path.exists(output_path):
                output_size_kb = os.path.getsize(output_path) / 1024
                log_progress(f"Annotated image created: {output_path}")
                log_progress(f"Output file size: {output_size_kb:.1f} KB")
                log_progress(f"Total ships detected: {len(detections)}")
            else:
                log_error("Output file was not created successfully")
                sys.exit(1)
        else:
            log_error(f"Failed to save image to: {output_path}")
            sys.exit(1)

    except Exception as e:
        log_error(f"Error creating annotated image: {e}")
        sys.exit(1)

def main():
    parser = argparse.ArgumentParser(description='Ship Detection using YOLO - Windows Console Compatible')
    parser.add_argument('--input', required=True, help='Input image path')
    parser.add_argument('--model', required=True, help='YOLO model path (.pt file)')
    parser.add_argument('--output', required=True, help='Output file path')
    parser.add_argument('--confidence', type=float, default=0.5, help='Confidence threshold (0.1-1.0)')

    args = parser.parse_args()

    log_progress("=== vGeoInt_v2 Ship Detection Started ===")
    log_progress("Script version: 2.1 (Windows Console Compatible)")
    log_progress(f"Input: {args.input}")
    log_progress(f"Model: {args.model}")
    log_progress(f"Output: {args.output}")
    log_progress(f"Confidence threshold: {args.confidence}")

    # Check dependencies
    if not DEPENDENCIES_AVAILABLE:
        log_error("Required dependencies are not available")
        sys.exit(1)

    # Validate inputs
    log_progress("Validating input parameters...")

    if not os.path.exists(args.input):
        log_error(f"Input file not found: {args.input}")
        sys.exit(1)
    log_progress(f"[OK] Input file exists: {os.path.basename(args.input)}")

    if not os.path.exists(args.model):
        log_error(f"Model file not found: {args.model}")
        sys.exit(1)
    log_progress(f"[OK] Model file exists: {os.path.basename(args.model)}")

    if not (0.1 <= args.confidence <= 1.0):
        log_error("Confidence must be between 0.1 and 1.0")
        sys.exit(1)
    log_progress(f"[OK] Confidence threshold is valid: {args.confidence}")

    # Load and validate model
    model = load_model(args.model)
    if model is None:
        log_error("Failed to load YOLO model")
        sys.exit(1)

    # Perform detection
    log_progress("Starting ship detection process...")
    detections = detect_ships(model, args.input, args.confidence)

    if not detections:
        log_progress("No ships detected in the image")
        # Create empty output file
        if args.output.endswith('.shp'):
            log_progress("Creating empty shapefile...")
            try:
                empty_gdf = gpd.GeoDataFrame(
                    columns=['ship_id', 'confidence', 'class_id', 'area_sqm', 'width_m', 'height_m', 'area_pixels'],
                    geometry=[], crs='EPSG:4326'
                )
                empty_gdf.to_file(args.output, driver='ESRI Shapefile')
                log_progress(f"Empty shapefile created: {args.output}")
            except Exception as e:
                log_error(f"Error creating empty shapefile: {e}")
        else:
            log_progress("Creating copy of original image...")
            try:
                import shutil
                shutil.copy2(args.input, args.output)
                log_progress(f"Original image copied to: {args.output}")
            except Exception as e:
                log_error(f"Error copying image: {e}")

        log_progress("Ship detection completed (no detections)")
        sys.exit(0)

    # Generate output based on input type
    log_progress("Generating output file...")
    if is_geotiff(args.input):
        create_shapefile(detections, args.input, args.output)
    else:
        create_annotated_image(detections, args.input, args.output)

    log_progress("Ship detection completed successfully!")
    log_progress("=== Process Finished ===")

if __name__ == "__main__":
    main()