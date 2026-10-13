
import subprocess
import os
import sys
import io

# Fix Windows console encoding issue with Vietnamese characters
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace', line_buffering=True)
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace', line_buffering=True)

try:
    from vgeoint.ai.scripts._events import result as emit_result
except ImportError:  # stand-alone run outside the app
    def emit_result(*a, **k):
        pass

DEFAULT_OTB_EXE = r"C:\OTB-9.1.0-Win64\bin\otbcli_Pansharpening.bat"
OTB_LAUNCHER = "otbcli_Pansharpening.bat" if sys.platform == "win32" else "otbcli_Pansharpening"


def _config_file():
    try:
        from vgeoint.common.paths import CONFIG_DIR
    except ImportError:
        from pathlib import Path
        CONFIG_DIR = Path(__file__).resolve().parents[4] / "config"
    return os.path.join(str(CONFIG_DIR), "image_blending_config.json")


def find_otb_executable():
    """OTB launcher: $VGEOINT_OTB_DIR (OTB install root), config/image_blending_config.json "otb_path",
    the historical default install, then PATH. Returns the first that exists (else the first candidate)."""
    import json
    import shutil

    candidates = []
    otb_dir = os.environ.get("VGEOINT_OTB_DIR")
    if otb_dir:
        candidates.append(os.path.join(otb_dir, "bin", OTB_LAUNCHER))
    try:
        with open(_config_file(), encoding="utf-8") as f:
            configured = json.load(f).get("otb_path")
        if configured:
            candidates.append(configured)
    except (OSError, ValueError):
        pass
    candidates.append(DEFAULT_OTB_EXE)
    found = shutil.which(OTB_LAUNCHER)
    if found:
        candidates.append(found)
    for candidate in candidates:
        if os.path.exists(candidate):
            return candidate
    return candidates[0]


def otb_environment():
    """Environment for OTB without this Python env's GDAL/PROJ settings: otbenv.bat sets GDAL_DATA and
    PROJ_LIB but not PROJ_DATA, which PROJ prefers and would point OTB at an incompatible proj.db."""
    env = dict(os.environ)
    for key in ("GDAL_DATA", "GDAL_DRIVER_PATH", "PROJ_LIB", "PROJ_DATA", "PYTHONPATH", "PYTHONHOME"):
        env.pop(key, None)
    return env


def run_otb_pansharpening(pan_path, ms_path, output_path, method, **params):
    otb_exe = find_otb_executable()

    cmd = [
        otb_exe,
        "-inp", os.path.abspath(pan_path),
        "-inxs", os.path.abspath(ms_path)
    ]

    if method == "rcs":
        cmd.extend(["-method", "rcs"])
        cmd.extend(["-method.rcs.radiusx", str(params.get("radiusx", 9))])
        cmd.extend(["-method.rcs.radiusy", str(params.get("radiusy", 9))])
    elif method == "lmvm":
        cmd.extend(["-method", "lmvm"])
        cmd.extend(["-method.lmvm.radiusx", str(params.get("radiusx", 3))])
        cmd.extend(["-method.lmvm.radiusy", str(params.get("radiusy", 3))])
    elif method == "bayes":
        cmd.extend(["-method", "bayes"])
        cmd.extend(["-method.bayes.lambda", str(params.get("lambda_weight", 0.9999))])
        cmd.extend(["-method.bayes.s", str(params.get("s", 1))])

    cmd.extend(["-out", os.path.abspath(output_path)])

    print(f"=== Starting Pansharpening ===", flush=True)
    print(f"PAN input: {os.path.abspath(pan_path)}", flush=True)
    print(f"MS input: {os.path.abspath(ms_path)}", flush=True)
    print(f"Output path: {os.path.abspath(output_path)}", flush=True)
    print(f"Method: {method}", flush=True)
    print(f"Parameters: {params}", flush=True)
    print(f"Running command: {' '.join(cmd)}", flush=True)
    
    # Check if OTB exe exists
    if not os.path.exists(otb_exe):
        print(f"✗ ERROR: OTB executable not found at: {otb_exe}", flush=True)
        return False
    
    # Check if input files exist
    if not os.path.exists(pan_path):
        print(f"✗ ERROR: PAN file not found: {pan_path}", flush=True)
        return False
    if not os.path.exists(ms_path):
        print(f"✗ ERROR: MS file not found: {ms_path}", flush=True)
        return False

    print("Starting OTB process...", flush=True)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300, encoding='utf-8', errors='replace',
                                env=otb_environment())

        print(f"OTB process finished with return code: {result.returncode}", flush=True)
        
        # Print stdout
        if result.stdout:
            print("=== OTB Output ===", flush=True)
            print(result.stdout, flush=True)
        else:
            print("(No stdout output)", flush=True)

        # Print stderr
        if result.stderr:
            print("=== OTB Messages ===", flush=True)
            print(result.stderr, flush=True)
        else:
            print("(No stderr output)", flush=True)

        # Check if output file exists
        print(f"Checking for output file: {output_path}", flush=True)
        if os.path.exists(output_path):
            file_size = os.path.getsize(output_path)
            print(f"✓ Output file created: {output_path}", flush=True)
            print(f"✓ File size: {file_size / (1024*1024):.2f} MB", flush=True)
            
            if file_size == 0:
                print("✗ WARNING: Output file is empty (0 bytes)!", flush=True)
                return False
        else:
            print(f"✗ Output file not found: {output_path}", flush=True)
            print(f"✗ Absolute path checked: {os.path.abspath(output_path)}", flush=True)
            
            # Check if file was created in current directory
            output_filename = os.path.basename(output_path)
            if os.path.exists(output_filename):
                print(f"⚠ File found in current directory: {os.path.abspath(output_filename)}", flush=True)

        if result.returncode == 0:
            if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                print("✓ Pansharpening completed successfully!", flush=True)
                return True
            else:
                print("✗ Process returned success but output file not found or empty!", flush=True)
                return False
        else:
            print(f"✗ Command failed with return code: {result.returncode}", flush=True)
            return False
    except subprocess.TimeoutExpired:
        print("✗ Error: Process timeout (>300 seconds)", flush=True)
        return False
    except Exception as e:
        print(f"✗ Error: {e}", flush=True)
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("=== Pansharpening Script Started ===", flush=True)
    print(f"Python version: {sys.version}", flush=True)
    print(f"Current directory: {os.getcwd()}", flush=True)
    print(f"Arguments received: {sys.argv}", flush=True)
    
    if len(sys.argv) < 5:
        print("Usage: script.py <pan_image> <ms_image> <output> <method> [params...]", flush=True)
        sys.exit(1)

    pan_path = sys.argv[1]
    ms_path = sys.argv[2]
    output_path = sys.argv[3]
    method = sys.argv[4]

    params = {}
    for i in range(5, len(sys.argv), 2):
        if i + 1 < len(sys.argv):
            key = sys.argv[i]
            value = sys.argv[i + 1]
            # Convert numeric strings to appropriate types
            try:
                if '.' in value:
                    params[key] = float(value)
                else:
                    params[key] = int(value)
            except ValueError:
                params[key] = value

    success = run_otb_pansharpening(pan_path, ms_path, output_path, method, **params)
    print(f"=== Script finished with success={success} ===", flush=True)
    if success:
        emit_result(output=os.path.abspath(output_path))
    sys.exit(0 if success else 1)
