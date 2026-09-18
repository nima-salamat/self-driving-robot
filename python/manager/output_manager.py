import glob
import logging
import os
import queue
import re
import shutil
import threading
import cv2


class OutputManager:
    def __init__(
        self,
        output_dir=None,
        config_module=None,
        images_subdir='images',
        videos_subdir='videos',
        default_fps=20,
        default_codec='mp4v',
    ):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.config_module = config_module

        if output_dir is None and getattr(config_module, 'OUTPUT_DIR', None):
            output_dir = getattr(config_module, 'OUTPUT_DIR')
        self.output_dir = output_dir or 'output'
        self.images_dir = os.path.join(self.output_dir, images_subdir)
        self.videos_dir = os.path.join(self.output_dir, videos_subdir)

        self.default_fps = getattr(config_module, 'VIDEO_FPS', default_fps) if config_module else default_fps
        self.default_codec = getattr(config_module, 'VIDEO_CODEC', default_codec) if config_module else default_codec

        self._lock = threading.RLock()
        self.recording = False
        self.video_writer = None
        self.current_video_path = None
        self._write_queue = queue.Queue(maxsize=3)
        self._writer_stop = threading.Event()
        self.dropped_video_frames = 0
        self._writer_thread = threading.Thread(
            target=self._writer_loop,
            name="video-writer",
            daemon=True,
        )
        self._writer_thread.start()

        self.ensure_dirs()

    def ensure_dirs(self):
        os.makedirs(self.images_dir, exist_ok=True)
        os.makedirs(self.videos_dir, exist_ok=True)

    def _next_index_for(self, directory, prefix, extension):
        pattern = re.compile(rf"^{re.escape(prefix)}_(\d+)\.{re.escape(extension.lstrip('.'))}$")
        max_n = 0
        for p in glob.glob(os.path.join(directory, f"{prefix}_*.*")):
            base = os.path.basename(p)
            m = pattern.search(base)
            if m:
                try:
                    max_n = max(max_n, int(m.group(1)))
                except ValueError:
                    continue
        return max_n + 1

    def next_image_path(self, ext='.png'):
        return os.path.join(
            self.images_dir,
            f'image_{self._next_index_for(self.images_dir, "image", ext)}{ext}',
        )

    def next_video_path(self, ext='.mp4'):
        return os.path.join(
            self.videos_dir,
            f'video_{self._next_index_for(self.videos_dir, "video", ext)}{ext}',
        )

    def save_image(self, frame, ext='.png'):
        with self._lock:
            path = self.next_image_path(ext=ext)
            try:
                if not cv2.imwrite(path, frame):
                    raise RuntimeError('cv2.imwrite returned False')
                self.logger.info("Saved image: %s", path)
                return path
            except Exception:
                self.logger.exception("Failed to save image %s", path)
                raise

    def start_recording(self, frame_shape, fps=None, codec=None, ext='.mp4'):
        with self._lock:
            if self.recording:
                return self.current_video_path

            fps = fps or self.default_fps
            codec = codec or self.default_codec

            minimum_mb = max(
                0.0,
                float(getattr(self.config_module, "MIN_FREE_DISK_MB", 256)),
            )
            free_mb = shutil.disk_usage(self.output_dir).free / (1024 * 1024)
            if free_mb < minimum_mb:
                raise RuntimeError(
                    f"Insufficient disk space for recording: "
                    f"{free_mb:.1f} MiB free, minimum {minimum_mb:.1f} MiB"
                )

            path = self.next_video_path(ext=ext)
            h, w = int(frame_shape[0]), int(frame_shape[1])

            fourcc = cv2.VideoWriter_fourcc(*codec)
            writer = cv2.VideoWriter(path, fourcc, float(fps), (w, h))
            if not writer.isOpened():
                writer.release()
                raise RuntimeError(f'Failed to open VideoWriter for {path} (codec={codec})')

            self.video_writer = writer
            self.recording = True
            self.current_video_path = path
            self.dropped_video_frames = 0
            self.logger.info("Started recording: %s", path)
            return path

    def write_frame(self, frame):
        with self._lock:
            if not self.recording or self.video_writer is None:
                return False

        try:
            self._write_queue.put_nowait(frame)
            return True
        except queue.Full:
            try:
                self._write_queue.get_nowait()
                self._write_queue.task_done()
            except queue.Empty:
                pass
            try:
                self._write_queue.put_nowait(frame)
                self.dropped_video_frames += 1
                return True
            except queue.Full:
                self.dropped_video_frames += 1
                return False

    def _writer_loop(self):
        while not self._writer_stop.is_set() or not self._write_queue.empty():
            try:
                frame = self._write_queue.get(timeout=0.1)
            except queue.Empty:
                continue

            try:
                with self._lock:
                    writer = self.video_writer if self.recording else None
                    if writer is not None:
                        writer.write(frame)
            except Exception:
                self.logger.exception("Failed to write video frame")
            finally:
                self._write_queue.task_done()

    def stop_recording(self):
        with self._lock:
            if not self.recording:
                return None

        self._write_queue.join()
        with self._lock:
            if not self.recording:
                return None
            path = self.current_video_path
            try:
                self.video_writer.release()
                self.logger.info(
                    "Stopped recording: %s (dropped=%d)",
                    path,
                    self.dropped_video_frames,
                )
                return path
            finally:
                self.video_writer = None
                self.current_video_path = None
                self.recording = False

    def stats(self):
        with self._lock:
            return {
                "recording": bool(self.recording),
                "current_video_path": self.current_video_path,
                "dropped_video_frames": int(self.dropped_video_frames),
                "queue_depth": self._write_queue.qsize(),
                "writer_alive": self._writer_thread.is_alive(),
            }

    def is_recording(self):
        with self._lock:
            return bool(self.recording)

    def close(self):
        try:
            self._write_queue.join()
        finally:
            with self._lock:
                if self.video_writer is not None:
                    try:
                        self.video_writer.release()
                    except Exception:
                        self.logger.exception("Failed to release video writer")
                self.video_writer = None
                self.recording = False
                self.current_video_path = None
            self._writer_stop.set()
            if self._writer_thread.is_alive() and self._writer_thread is not threading.current_thread():
                self._writer_thread.join(timeout=2.0)
