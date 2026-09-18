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
    model_path: Optional[str] = None
    model_url: Optional[str] = None
    archive_url: Optional[str] = None
    archive_glob: Optional[str] = None


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
        model_url=(
            "https://huggingface.co/nickpai/lane-detection-unet-ncnn/"
            "resolve/main/unet_depthwise_nano/"
            "unet_depthwise_nano_jit.pnnx.onnx"
        ),
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
        notes="Still-small depthwise UNet with more capacity than Nano.",
        model_path="unet_depthwise_small/unet_depthwise_small_jit.pnnx.onnx",
        model_url=(
            "https://huggingface.co/nickpai/lane-detection-unet-ncnn/"
            "resolve/main/unet_depthwise_small/"
            "unet_depthwise_small_jit.pnnx.onnx"
        ),
    ),
    "ufld_culane_resnet18": LaneModelSpec(
        name="ufld_culane_resnet18",
        title="Ultra-Fast-Lane-Detection ResNet18 CULane",
        format="onnx",
        input_width=800,
        input_height=288,
        dataset="CULane",
        license="MIT",
        params="ResNet18 backbone",
        notes="Row-wise lane detector; useful as a different architecture baseline.",
        archive_url=(
            "https://s3.ap-northeast-2.wasabisys.com/"
            "pinto-model-zoo/140_Ultra-Fast-Lane-Detection/"
            "resources_culane.tar.gz"
        ),
        archive_glob="**/*.onnx",
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
    spec = get_model_spec(name)
    if spec.model_path is not None:
        return MODEL_ROOT / spec.model_path

    candidates = sorted(MODEL_ROOT.glob(spec.archive_glob or "*.onnx"))
    if not candidates:
        return MODEL_ROOT / spec.name / f"{spec.name}.onnx"
    return candidates[0]
