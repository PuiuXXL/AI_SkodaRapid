"""ONNX inference with automatic accelerator choice: CUDA -> OpenVINO -> CPU.

:class:`OnnxModel` does **inference only**. Pre-processing lives in :mod:`perception.preprocess` and
post-processing in :mod:`perception.postprocess`, so each can be timed and tested on its own.

Backends:
* ``CUDAExecutionProvider`` / ``CPUExecutionProvider`` (and any other ORT provider): ONNX Runtime.
* ``OpenVINOExecutionProvider``: ONNX Runtime's OpenVINO EP if that build is installed, otherwise the native
  ``openvino`` runtime reading the same ``.onnx`` (``onnxruntime-gpu`` and ``onnxruntime-openvino`` are separate
  wheels and cannot coexist, so native OpenVINO is how we get both CUDA and OpenVINO in one environment).
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt

from perception.log import get_logger
from perception.perf import LatencyWindow

__all__ = ["DEFAULT_PROVIDER_ORDER", "OnnxModel", "TensorSpec", "available_providers", "set_intra_op_threads"]

log = get_logger("perception.runtime")

DEFAULT_PROVIDER_ORDER: tuple[str, ...] = (
    "CUDAExecutionProvider",
    "OpenVINOExecutionProvider",
    "CPUExecutionProvider",
)
OPENVINO = "OpenVINOExecutionProvider"
OPENVINO_DEVICE_ENV = "DRIVEMATE_OPENVINO_DEVICE"  # default CPU; Intel iGPU would be "GPU"

_ORT_DTYPES: dict[str, npt.DTypeLike] = {
    "tensor(float)": np.float32,
    "tensor(float16)": np.float16,
    "tensor(double)": np.float64,
    "tensor(uint8)": np.uint8,
    "tensor(int8)": np.int8,
    "tensor(int32)": np.int32,
    "tensor(int64)": np.int64,
    "tensor(bool)": np.bool_,
}

_dlls_preloaded = False
_intra_op_threads = 0  # 0 = ONNX Runtime default (all physical cores)


def set_intra_op_threads(n: int) -> None:
    """Intra-op threads of every ONNX Runtime session created afterwards in this process (``models.onnx_threads``)."""
    global _intra_op_threads
    _intra_op_threads = max(0, int(n))


@dataclass(frozen=True)
class TensorSpec:
    name: str
    shape: tuple[int | str | None, ...]
    dtype: str  # numpy dtype name, e.g. "float32"


def _preload_cuda_dlls(ort: Any) -> None:
    """onnxruntime-gpu >= 1.21 can load the CUDA/cuDNN DLLs installed by pip (nvidia-* wheels)."""
    global _dlls_preloaded
    if _dlls_preloaded:
        return
    _dlls_preloaded = True
    preload = getattr(ort, "preload_dlls", None)
    if callable(preload):
        try:
            preload()
        except Exception as exc:  # pragma: no cover - depends on the machine
            log.warning("onnxruntime.preload_dlls failed", extra={"fields": {"error": str(exc)}})


def _openvino_available() -> bool:
    try:
        import openvino  # noqa: F401
    except ImportError:
        return False
    return True


def available_providers() -> list[str]:
    """Providers this environment can try, in :data:`DEFAULT_PROVIDER_ORDER` first, then the rest."""
    found: list[str] = []
    try:
        import onnxruntime as ort

        found.extend(ort.get_available_providers())
    except ImportError:
        pass
    if OPENVINO not in found and _openvino_available():
        found.append(OPENVINO)
    ordered = [p for p in DEFAULT_PROVIDER_ORDER if p in found]
    return ordered + [p for p in found if p not in ordered and p != "AzureExecutionProvider"]


class OnnxModel:
    """An ONNX model on the first provider that works.

    Args:
        path: ``.onnx`` file.
        providers: ``"auto"`` (try ``order``), one provider name, or a list tried in order.
        name: label for logs and benchmark tables (defaults to the file stem).
        perf_window: number of inference timings kept for p50/p95.
        warmup: run one inference on random inputs right away.
        order: provider order used by ``"auto"`` (pass ``cfg.models.onnx_providers``).
    """

    def __init__(
        self,
        path: str | Path,
        providers: str | Sequence[str] = "auto",
        *,
        name: str | None = None,
        perf_window: int = 120,
        warmup: bool = True,
        order: Sequence[str] = DEFAULT_PROVIDER_ORDER,
    ) -> None:
        self.path = Path(path)
        if not self.path.is_file():
            raise FileNotFoundError(f"ONNX model not found: {self.path}")
        self.name = name or self.path.stem
        self.latency = LatencyWindow(perf_window)
        self.backend = ""
        self.provider = ""
        self.inputs: list[TensorSpec] = []
        self.outputs: list[TensorSpec] = []
        self._ort_session: Any = None
        self._ov_compiled: Any = None

        if providers == "auto":
            candidates = list(order)
        elif isinstance(providers, str):
            candidates = [providers]
        else:
            candidates = list(providers)

        errors: dict[str, str] = {}
        for provider in candidates:
            try:
                self._init_backend(provider)
            except Exception as exc:
                errors[provider] = str(exc).splitlines()[0] if str(exc) else type(exc).__name__
                log.warning(
                    "provider unavailable",
                    extra={"fields": {"model": self.name, "provider": provider, "error": errors[provider]}},
                )
                continue
            break
        else:
            raise RuntimeError(f"{self.name}: no provider could load the model: {errors}")

        log.info(
            "model loaded",
            extra={"fields": {"model": self.name, "backend": self.backend, "provider": self.provider}},
        )
        if warmup:
            self.warmup()

    # backends -----------------------------------------------------------------------------------------

    def _init_backend(self, provider: str) -> None:
        import onnxruntime as ort

        ort_available = ort.get_available_providers()
        if provider == OPENVINO and OPENVINO not in ort_available:
            self._init_openvino()
            return
        if provider not in ort_available:
            raise RuntimeError(f"{provider} not in onnxruntime build ({ort_available})")
        if provider == "CUDAExecutionProvider":
            _preload_cuda_dlls(ort)
        options = ort.SessionOptions()
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        options.log_severity_level = 3
        if _intra_op_threads:
            options.intra_op_num_threads = _intra_op_threads
        session = ort.InferenceSession(str(self.path), sess_options=options, providers=[provider])
        active = session.get_providers()[0]
        if active != provider:  # ORT silently falls back to CPU when a provider fails to initialize
            raise RuntimeError(f"requested {provider}, onnxruntime activated {active}")
        self._ort_session = session
        self.backend = "onnxruntime"
        self.provider = provider
        self.inputs = [
            TensorSpec(i.name, tuple(i.shape), np.dtype(_ORT_DTYPES.get(i.type, np.float32)).name)
            for i in session.get_inputs()
        ]
        self.outputs = [
            TensorSpec(o.name, tuple(o.shape), np.dtype(_ORT_DTYPES.get(o.type, np.float32)).name)
            for o in session.get_outputs()
        ]

    def _init_openvino(self) -> None:
        import openvino as ov

        device = os.environ.get(OPENVINO_DEVICE_ENV, "CPU")
        core = ov.Core()
        compiled = core.compile_model(str(self.path), device)
        self._ov_compiled = compiled
        self.backend = "openvino"
        self.provider = f"{OPENVINO}:{device}"
        self.inputs = [self._ov_spec(port) for port in compiled.inputs]
        self.outputs = [self._ov_spec(port) for port in compiled.outputs]

    @staticmethod
    def _ov_spec(port: Any) -> TensorSpec:
        shape = tuple(int(d.get_length()) if d.is_static else None for d in port.get_partial_shape())
        dtype = np.dtype(port.get_element_type().to_dtype()).name
        return TensorSpec(port.get_any_name(), shape, dtype)

    # inference ----------------------------------------------------------------------------------------

    def run(self, feeds: Mapping[str, npt.NDArray[Any]] | npt.NDArray[Any]) -> list[npt.NDArray[Any]]:
        """Inference only (timed). ``feeds`` is ``{input_name: array}`` or a single array for one-input models."""
        if not isinstance(feeds, Mapping):
            if len(self.inputs) != 1:
                raise ValueError(f"{self.name} has {len(self.inputs)} inputs; pass a dict")
            feeds = {self.inputs[0].name: feeds}
        with self.latency.time():
            if self._ort_session is not None:
                outputs: list[npt.NDArray[Any]] = self._ort_session.run(None, dict(feeds))
            else:
                result = self._ov_compiled(dict(feeds))
                outputs = [np.asarray(result[port]) for port in self._ov_compiled.outputs]
        return outputs

    def dummy_inputs(self, seed: int = 0) -> dict[str, npt.NDArray[Any]]:
        """Random inputs with the model's shapes (dynamic dims become 1)."""
        rng = np.random.default_rng(seed)
        feeds: dict[str, npt.NDArray[Any]] = {}
        for spec in self.inputs:
            shape = tuple(d if isinstance(d, int) and d > 0 else 1 for d in spec.shape)
            dtype = np.dtype(spec.dtype)
            if np.issubdtype(dtype, np.floating):
                feeds[spec.name] = rng.random(shape, dtype=np.float32).astype(dtype)
            else:
                feeds[spec.name] = np.zeros(shape, dtype=dtype)
        return feeds

    def warmup(self, n: int = 1) -> None:
        """Run ``n`` inferences on random inputs (first-call allocations, kernel selection)."""
        feeds = self.dummy_inputs()
        for _ in range(n):
            self.run(feeds)

    def __repr__(self) -> str:
        return f"OnnxModel(name={self.name!r}, backend={self.backend!r}, provider={self.provider!r})"
