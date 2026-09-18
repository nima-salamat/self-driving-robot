from dataclasses import dataclass
from pathlib import Path
from typing import Optional


MODEL_ROOT = Path(__file__).resolve().parents[2] / "models" / "lane"


@dataclass(frozen=True)
class LaneModelSpec:
    name: str
    title: str
    format: str
    input_width: int
    input_height: int
    dataset: str
    license: str
    params: str
    notes: str
    model_path: str
    model_source: str = "bundled"


MODEL_SPECS = {
    "unet_depthwise_nano": LaneModelSpec(
        name="unet_depthwise_nano",
        title="UNetDepthwiseNano",
        format="onnx",
        input_width=256,
        input_height=256,
        dataset="BDD100K",
        license="MIT",
        params="52,191 params / 3.00 GFLOPs",
        notes="Very small depthwise UNet lane segmentation model.",
        model_path="unet_depthwise_nano/unet_depthwise_nano_jit.pnnx.onnx",
    ),
    "unet_depthwise_small": LaneModelSpec(
        name="unet_depthwise_small",
        title="UNetDepthwiseSmall",
        format="onnx",
        input_width=256,
        input_height=256,
        dataset="BDD100K",
        license="MIT",
        params="253,919 params / 5.88 GFLOPs",
        notes="Small depthwise UNet with more capacity than Nano.",
        model_path="unet_depthwise_small/unet_depthwise_small_jit.pnnx.onnx",
    ),
}


def list_models():
    return tuple(MODEL_SPECS.values())


def get_model_spec(name):
    try:
        return MODEL_SPECS[name]
    except KeyError as exc:
        choices = ", ".join(sorted(MODEL_SPECS))
        raise ValueError(f"Unknown lane model '{name}'. Available: {choices}") from exc


def resolve_model_path(name):
    return MODEL_ROOT / get_model_spec(name).model_path
