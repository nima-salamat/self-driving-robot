# Lane Model Candidates

Two lightweight lane-segmentation models are included for Raspberry Pi testing.

| Name | Architecture | Input | Dataset | Runtime |
| --- | --- | --- | --- | --- |
| `unet_depthwise_nano` | UNetDepthwiseNano | 256x256 | BDD100K | NCNN |
| `unet_depthwise_small` | UNetDepthwiseSmall | 256x256 | BDD100K | NCNN |

The repository keeps the PNNX-generated ONNX files as model artifacts and uses the native NCNN `.param + .bin` pair at runtime. The ONNX artifacts have their source SHA256 recorded in `vision/ml_lane/registry.py`.

List the installed candidates:

```bash
python python/tools/benchmark_lane_models.py --list
```

The weights can also be re-fetched and verified:

```bash
python python/tools/download_lane_models.py --model all
```

Benchmark on the Raspberry Pi camera:

```bash
python python/tools/benchmark_lane_models.py --model unet_depthwise_nano --camera --camera-mode picam --display --frames 300
python python/tools/benchmark_lane_models.py --model unet_depthwise_small --camera --camera-mode picam --display --frames 300
```

Benchmark against a recorded video:

```bash
python python/tools/benchmark_lane_models.py --model unet_depthwise_nano --input output/videos/video_1.mp4 --display --frames 300
```

The normal robot runtime keeps the existing classical detector. ML lane detection is opt-in:

```bash
python python/main.py --mode race --ml-lane-model unet_depthwise_nano
```

Omitting `--ml-lane-model` leaves the existing lane detector unchanged. Arduino firmware and protocol are unchanged.
