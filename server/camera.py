"""通过可选的 OpenCV / Picamera2 后端读取摄像头，每次返回一张 JPEG。"""

import logging
import os
from threading import Lock

import cv2


BACKENDS = ("opencv", "picamera2")
logger = logging.getLogger(__name__)


class CameraController:
    def __init__(self, backend=None):
        self.backend = backend if backend is not None else os.environ.get("HOMEBOT_CAMERA", "opencv")
        if self.backend not in BACKENDS:
            raise ValueError("HOMEBOT_CAMERA must be opencv or picamera2.")
        self.capture = None
        self._ready = False
        # FastAPI 的普通 def 路由可能同时运行；避免读图时关闭摄像头。
        self.lock = Lock()

    def start(self):
        with self.lock:
            if self._ready:
                return
            # 上次 close/release 失败时先重试清理，不创建另一个设备实例。
            self._release()
            try:
                if self.backend == "picamera2":
                    try:
                        from picamera2 import Picamera2
                    except ImportError as error:
                        raise RuntimeError(
                            "Picamera2 is unavailable. Install python3-picamera2 with apt "
                            "and use a venv with --system-site-packages."
                        ) from error
                    self.capture = Picamera2()
                    config = self.capture.create_video_configuration(
                        main={"size": (640, 480), "format": "RGB888"}
                    )
                    self.capture.configure(config)
                    # 无桌面预览窗口，适用于 Pi OS Lite / SSH。
                    self.capture.start()
                else:
                    self.capture = cv2.VideoCapture(0)
                    if not self.capture.isOpened():
                        raise RuntimeError("Cannot open camera. Check connection and system permission. On macOS, run python -m server.camera --check in the server terminal first.")
                    self.capture.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                    self.capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                self._ready = True
            except Exception as error:
                self._fail("Cannot open camera", error)

    def get_frame(self):
        with self.lock:
            if not self._ready:
                raise RuntimeError("Camera is off. Click Start camera first.")
            try:
                if self.backend == "picamera2":
                    # Picamera2 的 RGB888 数组按 B,G,R 排列，可直接交给 OpenCV。
                    frame = self.capture.capture_array("main")
                    success = frame is not None and frame.size > 0
                else:
                    success, frame = self.capture.read()
                if not success:
                    raise RuntimeError("Cannot read camera image. Check the camera and try again.")
                frame = cv2.rotate(frame, cv2.ROTATE_180)  # Pi CSI 摄像头默认倒置。
                success, jpeg = cv2.imencode(".jpg", frame)
                if not success:
                    raise RuntimeError("Cannot encode camera image. Try starting the camera again.")
                return jpeg.tobytes()
            except Exception as error:
                self._fail("Camera image failed", error)

    def _fail(self, message, error):
        # 驱动可抛出 OSError / ValueError 等；统一为 API 已支持的 RuntimeError。
        detail = f"{message} ({self.backend}): {error}"
        try:
            self._release()
        except RuntimeError as cleanup_error:
            detail += f" Cleanup also failed: {cleanup_error}"
        raise RuntimeError(detail) from error

    def _release(self):
        # 仅在持有 lock 时调用。关闭失败时保留句柄，供 stop/start 重试。
        self._ready = False
        if self.capture is None:
            return
        try:
            if self.backend == "picamera2":
                try:
                    self.capture.stop()
                except Exception:
                    # 未启动、启动一半或设备异常时，仍必须调用 close。
                    logger.warning("Picamera2 stop failed; attempting close.", exc_info=True)
                self.capture.close()
            else:
                self.capture.release()
        except Exception as error:
            raise RuntimeError(
                f"Cannot close camera ({self.backend}): {error}. "
                "Retry Stop camera; if it still fails, restart the service."
            ) from error
        self.capture = None

    def stop(self):
        with self.lock:
            self._release()


def check_camera(backend=None):
    """在主线程首次申请权限、读取一帧，然后关闭；不保存图片。"""
    camera = CameraController(backend)
    result = 0
    try:
        camera.start()
        jpeg = camera.get_frame()
        print(f"Camera OK ({camera.backend}): received {len(jpeg)} JPEG bytes. No image saved.")
    except RuntimeError as error:
        print(f"Camera check failed: {error}")
        if camera.backend == "opencv":
            print("If macOS asks for permission, allow the terminal app, then run this check again.")
        result = 1
    finally:
        try:
            camera.stop()
        except RuntimeError as error:
            print(f"Camera cleanup failed: {error}")
            result = 1
        else:
            print("Camera released.")
    return result


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Check the local camera without saving images.")
    parser.add_argument("--check", action="store_true", required=True)
    parser.add_argument("--camera", choices=BACKENDS, default=os.environ.get("HOMEBOT_CAMERA", "opencv"))
    args = parser.parse_args()
    if args.camera not in BACKENDS:
        parser.error("HOMEBOT_CAMERA must be opencv or picamera2.")
    raise SystemExit(check_camera(args.camera))
