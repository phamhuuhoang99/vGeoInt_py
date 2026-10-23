"""GPU/CPU choice of the AI scripts (vgeoint.ai.scripts._device) on machines with and without a usable GPU."""

import sys
import types
import warnings

import pytest

from vgeoint.ai.scripts._device import resolve_device


def fake_torch(available=True, warning=None, kernel_error=None, name="NVIDIA GeForce RTX 2080 Ti"):
    def is_available():
        if warning:
            warnings.warn(warning, UserWarning)
        return available

    def conv2d(x, w):
        if kernel_error:
            raise RuntimeError(kernel_error)
        return types.SimpleNamespace(sum=lambda: types.SimpleNamespace(item=lambda: 0.0))

    torch = types.SimpleNamespace(
        cuda=types.SimpleNamespace(
            is_available=is_available,
            get_device_name=lambda i: name,
            get_device_capability=lambda i: (7, 5),
            synchronize=lambda i: None,
        ),
        randn=lambda *shape, device=None: object(),
        nn=types.SimpleNamespace(functional=types.SimpleNamespace(conv2d=conv2d)),
        version=types.SimpleNamespace(cuda="12.8"),
    )
    return torch


@pytest.fixture
def logs():
    return []


def run(monkeypatch, logs, torch, requested="auto"):
    monkeypatch.setitem(sys.modules, "torch", torch)
    return resolve_device(requested, logs.append)


def test_working_gpu(monkeypatch, logs):
    assert run(monkeypatch, logs, fake_torch()) == "cuda:0"
    assert logs == ["[OK] Dùng GPU: NVIDIA GeForce RTX 2080 Ti (compute 7.5, CUDA 12.8)"]
    assert run(monkeypatch, logs, fake_torch(), "cuda:1") == "cuda:1"


def test_cpu_requested(monkeypatch, logs):
    assert run(monkeypatch, logs, fake_torch(), "cpu") == "cpu"


def test_no_gpu(monkeypatch, logs):
    assert run(monkeypatch, logs, fake_torch(available=False)) == "cpu"
    assert logs == ["[INFO] Không có GPU NVIDIA dùng được -> chạy bằng CPU"]


def test_driver_too_old(monkeypatch, logs):
    warning = "CUDA initialization: The NVIDIA driver on your system is too old (found version 11040)."
    assert run(monkeypatch, logs, fake_torch(available=False, warning=warning)) == "cpu"
    assert "driver on your system is too old" in logs[0] and logs[0].endswith("-> chạy bằng CPU")


def test_gpu_not_supported_by_the_build(monkeypatch, logs):
    """An old/new GPU reports available but its first kernel fails: CPU instead of a crash."""
    error = "CUDA error: no kernel image is available for execution on the device\nCUDA kernel errors..."
    assert run(monkeypatch, logs, fake_torch(kernel_error=error)) == "cpu"
    assert logs == ["[WARN] GPU không chạy được với bản PyTorch này "
                    "(CUDA error: no kernel image is available for execution on the device) -> chạy bằng CPU"]


def test_without_torch(monkeypatch, logs):
    monkeypatch.setitem(sys.modules, "torch", None)  # import torch -> ImportError
    assert resolve_device("auto", logs.append) == "cpu"
