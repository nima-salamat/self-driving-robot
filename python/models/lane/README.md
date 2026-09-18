# Lane Model Candidates

These model files are downloaded locally and are intentionally not required by the normal robot runtime.

Run:

```bash
python python/tools/download_lane_models.py --model all
```

List:

```bash
python python/tools/benchmark_lane_models.py --list
```

Benchmark a model on a recorded video:

```bash
python python/tools/benchmark_lane_models.py \
  --model unet_depthwise_nano \
  --input output/videos/video_1.mp4 \
  --display
```

Benchmark directly from the Raspberry Pi camera:

```bash
python python/tools/benchmark_lane_models.py \
  --model unet_depthwise_nano \
  --camera \
  --display
```

The repository contains the loader/decoder and download manifest; third-party binary weights are fetched into this directory at setup time rather than committed to Git.
