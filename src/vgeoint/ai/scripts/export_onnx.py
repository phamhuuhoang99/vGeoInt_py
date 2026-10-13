import os
import shutil
import cv2
import numpy as np
from pathlib import Path
from mmdeploy.apis import torch2onnx
from mmdeploy.backend.onnxruntime.init_plugins import get_ops_path

def main():
    # 1. Define paths
    script_dir = Path(__file__).parent
    workspace_dir = script_dir.parent
    
    # Model config and checkpoint paths
    model_cfg = str(script_dir / 'faster_rcnn_r50_fpn_viso_v3.py')
    model_checkpoint = r"C:\Program Files (x86)\vGeoInt_v2\models\epoch_6.pth"
    
    # Output directory
    work_dir = str(workspace_dir / 'models' / 'onnx_output')
    os.makedirs(work_dir, exist_ok=True)
    
    print(f"Model config: {model_cfg}")
    print(f"Checkpoint: {model_checkpoint}")
    print(f"Output directory: {work_dir}")
    
    # 2. Generate a dummy image for tracing
    dummy_img_path = os.path.join(work_dir, 'dummy_trace_input.jpg')
    dummy_img = np.zeros((1024, 1024, 3), dtype=np.uint8)
    cv2.imwrite(dummy_img_path, dummy_img)
    print(f"Generated dummy tracing image at: {dummy_img_path}")
    
    # 3. Create a temporary deploy_cfg.py file
    # Writing configuration to a file ensures it is parsed as a ConfigDict by MMEngine/MMDeploy,
    # resolving the AttributeError: 'dict' object has no attribute 'iou_threshold' error.
    deploy_cfg_path = os.path.join(work_dir, 'deploy_cfg.py')
    with open(deploy_cfg_path, 'w') as f:
        f.write('''
onnx_config = dict(
    type='onnx',
    export_params=True,
    keep_initializers_as_inputs=False,
    opset_version=11,
    save_file='end2end.onnx',
    input_names=['input'],
    output_names=['dets', 'labels'],
    input_shape=None,
    dynamic_axes=dict(
        input={0: 'batch', 2: 'height', 3: 'width'},
        dets={0: 'batch', 1: 'num_dets'},
        labels={0: 'batch', 1: 'num_dets'}
    )
)

codebase_config = dict(
    type='mmdet',
    task='ObjectDetection',
    model_type='end2end',
    post_processing=dict(
        score_threshold=0.05,
        iou_threshold=0.5,
        max_output_boxes_per_class=200,
        pre_top_k=5000,
        keep_top_k=100,
        background_label_id=-1,
    )
)

backend_config = dict(
    type='onnxruntime'
)
''')
    print(f"Created temporary deploy_cfg config file at: {deploy_cfg_path}")
    
    # 4. Perform conversion
    print("Starting conversion from PyTorch to ONNX... (this may take a few minutes)")
    try:
        torch2onnx(
            img=dummy_img_path,
            work_dir=work_dir,
            save_file='model.onnx',
            deploy_cfg=deploy_cfg_path,
            model_cfg=model_cfg,
            model_checkpoint=model_checkpoint,
            device='cpu' # Run on CPU to ensure independence from CUDA during export
        )
        print("[SUCCESS] Model successfully exported to ONNX format!")
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"[ERROR] Export failed: {e}")
        return
        
    # 5. Extract and copy custom operators DLL
    try:
        dll_path = get_ops_path()
        if os.path.exists(dll_path):
            dest_path = os.path.join(work_dir, os.path.basename(dll_path))
            shutil.copy2(dll_path, dest_path)
            print(f"[SUCCESS] Copied custom operators DLL to: {dest_path}")
        else:
            print(f"[WARNING] Warning: Custom operators library path not found at: {dll_path}")
    except Exception as e:
        print(f"[WARNING] Warning: Failed to extract custom operators DLL: {e}")
        
    # Clean up dummy image and config
    if os.path.exists(dummy_img_path):
        os.remove(dummy_img_path)
    if os.path.exists(deploy_cfg_path):
        os.remove(deploy_cfg_path)
        
    print("\nONNX export completed successfully.")
    print(f"Exported files are in: {work_dir}")

if __name__ == '__main__':
    main()
