"""REL-008 E8.3: exports a trained model to ONNX (Phase_5 §2's "Artifact Generation: Export the
`.onnx` or `.pkl` model artifact.").

`export_lightgbm_to_onnx()` is flagged in the REL-008 plan as the one genuinely fragile path
(onnxmltools' LightGBM converter has a real history of breaking across LightGBM booster-format
versions) -- `export_torch_to_onnx()` (native `torch.onnx.export`, no third-party converter) is
the fallback if it proves unworkable, used directly for the TFT model either way since PyTorch's
own export is the natural path for it.
"""

from pathlib import Path

import onnxmltools
import torch
from onnxmltools.convert.common.data_types import FloatTensorType
from sklearn.base import BaseEstimator


def export_lightgbm_to_onnx(model: BaseEstimator, feature_names: list[str], path: Path) -> Path:
    initial_types = [("input", FloatTensorType([None, len(feature_names)]))]
    onnx_model = onnxmltools.convert_lightgbm(model, initial_types=initial_types)
    path.parent.mkdir(parents=True, exist_ok=True)
    onnxmltools.utils.save_model(onnx_model, str(path))
    return path


def export_torch_to_onnx(model: torch.nn.Module, dummy_input: torch.Tensor, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    model.eval()
    torch.onnx.export(
        model,
        (dummy_input,),
        str(path),
        input_names=["input"],
        output_names=["output"],
        dynamic_axes={"input": {0: "batch"}, "output": {0: "batch"}},
    )
    return path
