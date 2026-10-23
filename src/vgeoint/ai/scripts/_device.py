"""Pick the compute device for the AI scripts: the NVIDIA GPU when it really works, else the CPU.

The ai environment ships PyTorch built for CUDA 12.8, also on machines without a (usable) GPU. A plain
`torch.cuda.is_available()` is not enough there: with a GPU too old or too new for the build it is True,
then the first kernel fails with "no kernel image is available". So a small convolution is run on the
GPU first; on any failure the script uses the CPU and says why in the log.
"""

import warnings


def _first_line(text) -> str:
    lines = [line.strip() for line in str(text).splitlines() if line.strip()]
    return lines[0][:200] if lines else ""


def resolve_device(requested: str = "auto", log=print) -> str:
    """'cuda:N' when that GPU works with this PyTorch, else 'cpu'. `requested`: auto | cpu | cuda | cuda:N."""
    requested = (requested or "auto").strip().lower()
    if requested == "cpu":
        log("[INFO] Thiết bị tính toán: CPU (theo lựa chọn)")
        return "cpu"
    try:
        import torch
    except ImportError:
        log("[INFO] Không có PyTorch -> chạy bằng CPU")
        return "cpu"

    # A driver too old for the CUDA build only shows as a warning of is_available().
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        available = torch.cuda.is_available()
    if not available:
        reason = next((_first_line(w.message) for w in caught if "cuda" in str(w.message).lower()
                       or "driver" in str(w.message).lower()), "")
        log("[INFO] Không có GPU NVIDIA dùng được" + (f" ({reason})" if reason else "") + " -> chạy bằng CPU")
        return "cpu"

    device = requested if requested.startswith("cuda:") else "cuda:0"
    try:
        index = int(device.split(":")[1])
        name = torch.cuda.get_device_name(index)
        major, minor = torch.cuda.get_device_capability(index)
        x = torch.randn(1, 3, 32, 32, device=device)
        w = torch.randn(8, 3, 3, 3, device=device)
        torch.nn.functional.conv2d(x, w).sum().item()
        torch.cuda.synchronize(index)
    except Exception as e:  # no kernel image, driver error, wrong index, out of memory...
        log(f"[WARN] GPU không chạy được với bản PyTorch này ({_first_line(e)}) -> chạy bằng CPU")
        return "cpu"
    log(f"[OK] Dùng GPU: {name} (compute {major}.{minor}, CUDA {torch.version.cuda})")
    return device
