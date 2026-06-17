import os
import glob
import re
import threading
import logging
import cv2

class OutputManager:
    def __init__(self, output_dir=None, config_module=None, images_subdir='images', videos_subdir='videos',
                 default_fps=20, default_codec='mp4v'):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.config_module = config_module

        # Resolve directories
        if output_dir is None and getattr(config_module, 'OUTPUT_DIR', None):
            output_dir = getattr(config_module, 'OUTPUT_DIR')
        self.output_dir = output_dir or 'output'
        self.images_dir = os.path.join(self.output_dir, images_subdir)
        self.videos_dir = os.path.join(self.output_dir, videos_subdir)

        # Video defaults
        self.default_fps = getattr(config_module, 'VIDEO_FPS', default_fps) if config_module else default_fps
        self.default_codec = getattr(config_module, 'VIDEO_CODEC', default_codec) if config_module else default_codec

        # Recording state
        self._lock = threading.RLock()
        self.recording = False
        self.video_writer = None
        self.current_video_path = None

        # Create dirs now
        self.ensure_dirs()

    # -----------------
    # Filesystem helpers
    # -----------------
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
                    n = int(m.group(1))
                    if n > max_n:
                        max_n = n
                except ValueError:
                    continue
        return max_n + 1

    def next_image_path(self, ext='.png'):
        n = self._next_index_for(self.images_dir, 'image', ext)
        return os.path.join(self.images_dir, f'image_{n}{ext}')

    def next_video_path(self, ext='.mp4'):
        n = self._next_index_for(self.videos_dir, 'video', ext)
        return os.path.join(self.videos_dir, f'video_{n}{ext}')

    # -----------------
    # Image saving
    # -----------------
    def save_image(self, frame, ext='.png'):
        with self._lock:
            path = self.next_image_path(ext=ext)
            try:
                ok = cv2.imwrite(path, frame)
                if not ok:
                    raise RuntimeError('cv2.imwrite returned False')
                self.logger.info(f"Saved image: {path}")
            except Exception as e:
                self.logger.error(f"Failed to save image {path}: {e}")
                raise
            return path

    # -----------------
    # Video recording
    # -----------------
    def start_recording(self, frame_shape, fps=None, codec=None, ext='.mp4'):
        with self._lock:
            if self.recording:
                return self.current_video_path

            fps = fps or self.default_fps
            codec = codec or self.default_codec
            path = self.next_video_path(ext=ext)

            try:
                h, w = int(frame_shape[0]), int(frame_shape[1])
            except Exception as e:
                raise ValueError('frame_shape must be convertible to (h,w,...)') from e

            fourcc = cv2.VideoWriter_fourcc(*codec)
            writer = cv2.VideoWriter(path, fourcc, float(fps), (w, h))
            if not writer.isOpened():
                writer.release()
                raise RuntimeError(f'Failed to open VideoWriter for {path} (codec={codec})')

            self.video_writer = writer
            self.recording = True
            self.current_video_path = path
            self.logger.info(f"Started recording: {path}")
            return path

    def write_frame(self, frame):
        with self._lock:
            if not self.recording or self.video_writer is None:
                return False
            try:
                self.video_writer.write(frame)
                return True
            except Exception as e:
                self.logger.error(f"Failed to write frame: {e}")
                return False

    def stop_recording(self):
        with self._lock:
            if not self.recording:
                return None
            try:
                self.video_writer.release()
                self.logger.info(f"Stopped recording: {self.current_video_path}")
                return self.current_video_path
            finally:
                self.video_writer = None
                self.current_video_path = None
                self.recording = False

    def is_recording(self):
        with self._lock:
            return bool(self.recording)

    def close(self):
        with self._lock:
            if self.video_writer is not None:
                try:
                    self.video_writer.release()
                except Exception:
                    pass
            self.video_writer = None
            self.recording = False
            self.current_video_path = None

