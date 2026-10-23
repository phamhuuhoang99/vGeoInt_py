#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Building Segmentation Script for vGeoInt_v2
Segments buildings in images using UNet model and outputs prediction masks as images or GeoTIFF
Enhanced with detailed logging for real-time progress tracking
Compatible with Windows console encoding
"""

import torch
import numpy as np
import cv2
import os
import sys
import argparse
import time
from PIL import Image
import matplotlib.pyplot as plt

# ----- Bổ sung nếu cần -----
import pandas as pd

# Check for segmentation_models_pytorch availability
try:
    import segmentation_models_pytorch as smp
    SMP_AVAILABLE = True
except ImportError:
    SMP_AVAILABLE = False
    print("Warning: segmentation_models_pytorch not available")

# For GeoTIFF handling
try:
    import rasterio
    from rasterio.transform import from_bounds
    import rasterio.crs
    RASTERIO_AVAILABLE = True
except ImportError:
    RASTERIO_AVAILABLE = False

# Machine-readable events for vGeoInt (no-ops when run outside the app).
try:
    from vgeoint.ai.scripts._events import result
except ImportError:
    def result(**kwargs):
        pass

try:
    from vgeoint.ai.scripts._device import resolve_device
except ImportError:  # stand-alone run outside the app: no GPU check
    def resolve_device(requested="auto", log=print):
        import torch
        return "cuda:0" if requested != "cpu" and torch.cuda.is_available() else "cpu"

# Filled during processing, reported in the final result event.
_STATS = {"seconds": None}

# Set UTF-8 encoding for Windows console


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

def load_model(model_path, device="cpu"):
    """Load UNet model from file with enhanced error handling"""
    try:
        log_progress(f"Loading model from: {model_path}")

        # Check if model file exists
        if not os.path.exists(model_path):
            log_error(f"Model file not found: {model_path}")
            return None

        # Check file size
        file_size = os.path.getsize(model_path)
        if file_size == 0:
            log_error(f"Model file is empty: {model_path}")
            return None

        log_progress(f"Model file size: {file_size / (1024*1024):.2f} MB")

        log_progress(f"Using device: {device}")

        # Load the model with enhanced error handling
        try:
            log_progress("Attempting to load model...")

            # Load model with appropriate map_location (device is resolved by main: "cuda:N" or "cpu")
            model = torch.load(model_path, map_location=device, weights_only=False)

            log_progress("Model loaded from file successfully")

        except Exception as load_error:
            log_error(f"Failed to load model file: {str(load_error)}")
            log_progress("Trying alternative loading method...")

            try:
                # Try loading with weights_only=True for security
                model = torch.load(model_path, map_location='cpu', weights_only=True)
                log_progress("Model loaded with weights_only=True")
            except Exception as alt_error:
                log_error(f"Alternative loading also failed: {str(alt_error)}")
                return None

        # Handle different model formats
        if isinstance(model, dict):
            log_progress("Loaded state dict, creating UNet model...")

            if not SMP_AVAILABLE:
                log_error("segmentation_models_pytorch not available but state dict found")
                log_error("Please install segmentation_models_pytorch: pip install segmentation-models-pytorch")
                return None

            try:
                # Create UNet model - adjust architecture as needed
                model_obj = smp.Unet(
                    encoder_name="resnet34",
                    encoder_weights=None,  # Don't load pretrained weights
                    in_channels=3,
                    classes=2  # background, building
                )

                # Load state dict with strict=False to handle potential key mismatches
                missing_keys, unexpected_keys = model_obj.load_state_dict(model, strict=False)

                if missing_keys:
                    log_progress(f"Missing keys in state dict: {len(missing_keys)}")
                if unexpected_keys:
                    log_progress(f"Unexpected keys in state dict: {len(unexpected_keys)}")

                model = model_obj
                log_progress("UNet model created and state dict loaded")

            except Exception as model_create_error:
                log_error(f"Failed to create UNet model: {str(model_create_error)}")
                return None

        elif hasattr(model, 'eval'):
            log_progress("Loaded complete model object")
        else:
            log_error(f"Unknown model format: {type(model)}")
            return None

        # Move model to device and set to evaluation mode
        try:
            model = model.to(device)
            model.eval()
            log_progress(f"Model moved to {device} and set to evaluation mode")
        except Exception as device_error:
            log_error(f"Failed to move model to device: {str(device_error)}")
            return None

        log_progress(f"Model loaded successfully on {device}")
        return model

    except Exception as e:
        log_error(f"Unexpected error loading model: {str(e)}")
        import traceback
        log_error(f"Traceback: {traceback.format_exc()}")
        return None

def save_prediction_as_geotiff(pred_colored, output_path, reference_image_path=None):
    """Save the prediction mask as a GeoTIFF file that can be loaded in QGIS"""
    try:
        log_progress(f"Saving prediction mask to: {output_path}")

        if RASTERIO_AVAILABLE and reference_image_path and os.path.exists(reference_image_path):
            try:
                # Try to copy geospatial information from reference image
                with rasterio.open(reference_image_path) as src:
                    profile = src.profile.copy()
                    profile.update({
                        'count': 3,  # RGB
                        'dtype': 'uint8',
                        'height': pred_colored.shape[0],
                        'width': pred_colored.shape[1]
                    })

                    # Save as GeoTIFF with spatial reference
                    with rasterio.open(output_path, 'w', **profile) as dst:
                        # Convert from HWC to CHW format for rasterio
                        pred_rgb_chw = np.transpose(pred_colored, (2, 0, 1))
                        for i in range(3):
                            dst.write(pred_rgb_chw[i], i + 1)

                    log_progress(f"Successfully saved GeoTIFF with spatial reference: {output_path}")
                    return True

            except Exception as e:
                log_progress(f"Failed to save as GeoTIFF with spatial reference: {e}")
                # Fall back to basic TIFF

        # Fallback: Save as regular TIFF using PIL/OpenCV
        log_progress("Saving as regular TIFF image...")

        # Ensure the prediction is in uint8 format
        if pred_colored.dtype != np.uint8:
            pred_colored = (pred_colored * 255).astype(np.uint8)

        # Convert BGR to RGB if needed (OpenCV uses BGR)
        if pred_colored.shape[2] == 3:
            pred_colored_rgb = cv2.cvtColor(pred_colored, cv2.COLOR_BGR2RGB)
        else:
            pred_colored_rgb = pred_colored

        # Save using PIL for better format support
        pil_image = Image.fromarray(pred_colored_rgb)
        pil_image.save(output_path, format='TIFF')

        log_progress(f"Successfully saved TIFF image: {output_path}")
        return True

    except Exception as e:
        log_error(f"Error saving prediction mask: {e}")
        return False

def predict_and_visualize(image_path, model, class_names, class_rgb, device="cpu", output_path=None):
    def to_tensor(x):
        return x.transpose(2, 0, 1).astype("float32")

    def one_hot_decode(onehot_mask):
        return np.argmax(onehot_mask, axis=-1)

    def colour_code_segmentation(mask, label_values):
        colour_codes = np.array(label_values)
        return colour_codes[mask.astype(int)]

    def crop_image(image, target_size=1500):
        h, w = image.shape[:2]
        crop_h = max((h - target_size) // 2, 0)
        crop_w = max((w - target_size) // 2, 0)
        return image[crop_h : crop_h + target_size, crop_w : crop_w + target_size]

    log_progress("Starting building segmentation inference...")

    # 1. Load image
    log_progress(f"Loading input image: {image_path}")
    image_raw = np.array(Image.open(image_path).convert("RGB"))
    log_progress(f"Image loaded successfully - Shape: {image_raw.shape}")

    image_input = to_tensor(image_raw)
    image_input = torch.tensor(image_input).unsqueeze(0).to(device)  # [1, 3, H, W]

    # 2. Predict
    log_progress("Running model inference...")
    start_time = time.time()
    with torch.no_grad():
        pred = model(image_input)  # [1, C, H, W]
    _STATS["seconds"] = round(time.time() - start_time, 2)
    log_progress("Model inference completed successfully")

    # 3. Process prediction
    pred_np = pred.squeeze().cpu().numpy()  # [C, H, W]
    pred_np = np.transpose(pred_np, (1, 2, 0))  # [H, W, C]

    # 4. Create color segmentation mask
    log_progress("Creating colored segmentation mask...")
    pred_decoded = one_hot_decode(pred_np)
    pred_colored = colour_code_segmentation(pred_decoded, class_rgb)

    # Ensure pred_colored is in the correct format (uint8)
    if pred_colored.dtype != np.uint8:
        pred_colored = pred_colored.astype(np.uint8)

    log_progress(f"Colored mask created - Shape: {pred_colored.shape}, Type: {pred_colored.dtype}")

    # 5. Save the prediction mask as output
    if output_path:
        log_progress(f"Saving prediction mask to output file...")
        success = save_prediction_as_geotiff(pred_colored, output_path, image_path)
        if success:
            log_progress("Building segmentation completed successfully!")
            log_progress(f"Output saved: {output_path}")

            # Log file information
            if os.path.exists(output_path):
                file_size = os.path.getsize(output_path) / (1024 * 1024)  # MB
                log_progress(f"Output file size: {file_size:.2f} MB")
        else:
            log_error("Failed to save output file")
            return False

    return True

def main():
    parser = argparse.ArgumentParser(description='Building Segmentation using UNet - Windows Console Compatible')
    parser.add_argument('--input', required=True, help='Input image path')
    parser.add_argument('--model', required=True, help='UNet model path (.pth file)')
    parser.add_argument('--output', required=True, help='Output file path (will be saved as TIFF)')
    parser.add_argument('--confidence', type=float, default=0.5, help='Confidence threshold (0.1-1.0)')
    parser.add_argument('--size', type=int, default=512, help='Input size for model (default: 512)')
    parser.add_argument('--device', type=str, default='auto', help='Device to use: auto, cpu, cuda or cuda:N')
    parser.add_argument('--no-visualize', action='store_true', help='Skip overlay visualization')

    args = parser.parse_args()

    log_progress("=== vGeoInt_v2 Building Segmentation Started ===")
    log_progress("Script version: 1.0 (Windows Console Compatible)")
    log_progress(f"Input: {args.input}")
    log_progress(f"Model: {args.model}")
    log_progress(f"Output: {args.output}")
    log_progress(f"Confidence threshold: {args.confidence}")
    log_progress(f"Model input size: {args.size}")
    log_progress(f"Device: {args.device}")

    # Determine actual device (GPU only when it really runs with this PyTorch)
    device = resolve_device(args.device, log_progress)

    # Load the model
    log_progress("Loading model...")
    model = load_model(args.model, device)

    if model is None:
        log_error("Failed to load model. Exiting.")
        sys.exit(1)

    # Check if input file exists
    if not os.path.exists(args.input):
        log_error(f"Input file not found: {args.input}")
        sys.exit(1)

    # Ensure output directory exists
    output_dir = os.path.dirname(args.output)
    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir)
        log_progress(f"Created output directory: {output_dir}")

    # Define class names and colors
    class_names = ["background", "building"]
    class_rgb = [[0, 0, 0], [255, 255, 255]]  # Black background, white buildings

    try:
        success = predict_and_visualize(args.input, model, class_names, class_rgb, device, args.output)
        if success:
            log_progress("Prediction completed successfully!")
            log_progress(f"Segmentation mask saved to: {args.output}")
            result(output=args.output, seconds=_STATS["seconds"])
        else:
            log_error("Prediction failed!")
            sys.exit(1)
    except Exception as e:
        log_error(f"Prediction failed: {str(e)}")
        sys.exit(1)

    log_progress("=== Process Finished ===")

if __name__ == "__main__":
    main()