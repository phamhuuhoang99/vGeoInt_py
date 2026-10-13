import os
import sys
import numpy as np
from pathlib import Path

try:
    import onnxruntime as ort
except ImportError:
    print("[ERROR] onnxruntime not installed!")
    sys.exit(1)

def main():
    script_dir = Path(__file__).parent
    workspace_dir = script_dir.parent
    
    # Paths to output files
    model_path = workspace_dir / 'models' / 'onnx_output' / 'model.onnx'
    dll_path = workspace_dir / 'models' / 'onnx_output' / 'mmdeploy_onnxruntime_ops.dll'
    
    print(f"Checking model path: {model_path} (exists: {model_path.exists()})")
    print(f"Checking custom ops DLL: {dll_path} (exists: {dll_path.exists()})")
    
    if not model_path.exists() or not dll_path.exists():
        print("[ERROR] Exported files are missing!")
        return 1
        
    # Setup ONNX Runtime Session options
    session_options = ort.SessionOptions()
    print(f"Registering custom operators library: {dll_path}")
    session_options.register_custom_ops_library(str(dll_path))
    
    # Run on CPU for validation
    providers = ['CPUExecutionProvider']
    
    print("Initializing ONNX Runtime Session...")
    try:
        session = ort.InferenceSession(str(model_path), session_options, providers=providers)
        print("[SUCCESS] Session initialized successfully!")
    except Exception as e:
        print(f"[ERROR] Failed to initialize session: {e}")
        return 2
        
    # Create a dummy BGR input image frame
    print("Generating a dummy input frame (1024x1024x3)...")
    dummy_frame = np.random.randint(0, 255, (1024, 1024, 3), dtype=np.uint8)
    
    # Preprocess
    h, w = dummy_frame.shape[:2]
    # pad to 32 divisible
    pad_h = (32 - h % 32) % 32
    pad_w = (32 - w % 32) % 32
    import cv2
    padded = cv2.copyMakeBorder(dummy_frame, 0, pad_h, 0, pad_w, cv2.BORDER_CONSTANT, value=0)
    tensor = padded.transpose(2, 0, 1).astype(np.float32)
    tensor = np.expand_dims(tensor, axis=0) # [1, 3, H, W]
    
    print(f"Preprocessed input shape: {tensor.shape}")
    
    print("Running dummy inference...")
    try:
        outputs = session.run(None, {'input': tensor})
        dets = outputs[0][0]  # [num_dets, 5]
        labels = outputs[1][0]  # [num_dets]
        print("[SUCCESS] Inference completed successfully!")
        print(f"Detections shape: {dets.shape}")
        print(f"Labels shape: {labels.shape}")
        print(f"Sample detections (first 5):\n{dets[:5]}")
    except Exception as e:
        print(f"[ERROR] Inference failed: {e}")
        return 3
        
    print("\n[SUCCESS] All verification tests passed successfully!")
    return 0

if __name__ == '__main__':
    sys.exit(main())
