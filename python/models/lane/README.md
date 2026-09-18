# Lane Model Candidates

Two ONNX lane-segmentation models are bundled as base64 chunks and reconstructed automatically when an ML lane model is first used.

Available:

- `unet_depthwise_nano` — UNetDepthwiseNano, 256x256, BDD100K
- `unet_depthwise_small` — UNetDepthwiseSmall, 256x256, BDD100K

List:

```bash
python python/tools/benchmark_lane_models.py --list
```

Benchmark the models on a recorded drive:

```bash
python python/tools/benchmark_lane_models.py --model unet_depthwise_nano --input output/videos/video_1.mp4 --display --frames 300
python python/tools/benchmark_lane_models.py --model unet_depthwise_small --input output/videos/video_1.mp4 --display --frames 300
```

Benchmark directly from the camera:

```bash
python python/tools/benchmark_lane_models.py --model unet_depthwise_nano --camera --display --frames 300
```

The normal robot runtime keeps the existing classical lane detector unless `--ml-lane-model` is explicitly provided. The Arduino firmware and protocol are unchanged.
