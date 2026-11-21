from __future__ import annotations

from pathlib import Path

import numpy as np
import onnx
import pytest
from onnx import TensorProto, helper

from perception.runtime import OnnxModel, available_providers


@pytest.fixture(scope="session")
def tiny_model(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """y = (x + 1) * 2 on a [1, 3, 4, 4] float tensor; built once per session."""
    tmp_path = tmp_path_factory.mktemp("onnx")
    x = helper.make_tensor_value_info("x", TensorProto.FLOAT, [1, 3, 4, 4])
    y = helper.make_tensor_value_info("y", TensorProto.FLOAT, [1, 3, 4, 4])
    one = helper.make_tensor("one", TensorProto.FLOAT, [], [1.0])
    two = helper.make_tensor("two", TensorProto.FLOAT, [], [2.0])
    graph = helper.make_graph(
        [helper.make_node("Add", ["x", "one"], ["t"]), helper.make_node("Mul", ["t", "two"], ["y"])],
        "tiny",
        [x],
        [y],
        initializer=[one, two],
    )
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 17)])
    model.ir_version = 9
    onnx.checker.check_model(model)
    path = tmp_path / "tiny.onnx"
    onnx.save(model, path)
    return path


def test_cpu_inference_is_correct(tiny_model: Path) -> None:
    model = OnnxModel(tiny_model, providers=["CPUExecutionProvider"], warmup=False)
    assert model.backend == "onnxruntime"
    assert model.provider == "CPUExecutionProvider"
    assert [s.name for s in model.inputs] == ["x"]
    assert model.inputs[0].shape == (1, 3, 4, 4)
    assert model.inputs[0].dtype == "float32"

    x = np.arange(48, dtype=np.float32).reshape(1, 3, 4, 4)
    (y,) = model.run(x)
    np.testing.assert_allclose(y, (x + 1) * 2)
    (y2,) = model.run({"x": x})
    np.testing.assert_allclose(y2, y)


def test_timings_and_warmup(tiny_model: Path) -> None:
    model = OnnxModel(tiny_model, providers="CPUExecutionProvider", warmup=True, perf_window=10)
    assert model.latency.count == 1  # warm-up run is timed
    model.warmup(n=3)
    assert model.latency.count == 4
    assert model.latency.p50() >= 0
    assert model.latency.p95() >= model.latency.p50()


def test_auto_picks_a_working_provider(tiny_model: Path) -> None:
    model = OnnxModel(tiny_model, providers="auto")
    assert model.provider.split(":")[0] in available_providers()
    (y,) = model.run(np.zeros((1, 3, 4, 4), dtype=np.float32))
    np.testing.assert_allclose(y, 2.0)


def test_unknown_provider_falls_through_to_cpu(tiny_model: Path) -> None:
    model = OnnxModel(tiny_model, providers=["NoSuchExecutionProvider", "CPUExecutionProvider"], warmup=False)
    assert model.provider == "CPUExecutionProvider"


def test_no_working_provider_raises(tiny_model: Path) -> None:
    with pytest.raises(RuntimeError, match="no provider"):
        OnnxModel(tiny_model, providers=["NoSuchExecutionProvider"], warmup=False)


def test_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        OnnxModel(tmp_path / "missing.onnx")


def test_dummy_inputs_match_specs(tiny_model: Path) -> None:
    model = OnnxModel(tiny_model, providers="CPUExecutionProvider", warmup=False)
    feeds = model.dummy_inputs()
    assert set(feeds) == {"x"} and feeds["x"].shape == (1, 3, 4, 4)
