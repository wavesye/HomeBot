"""读取运行 FastAPI 的电脑摄像头，每次返回一张 JPEG 图片。"""

from threading import Lock

import cv2


class CameraController:
    def __init__(self):
        self.capture = None
        # FastAPI 的普通 def 路由可能同时运行；避免读图时关闭摄像头。
        self.lock = Lock()

    def start(self):
        with self.lock:
            if self.capture is not None:
                return
            try:
                self.capture = cv2.VideoCapture(0)
                if not self.capture.isOpened():
                    raise RuntimeError("Cannot open camera. Check connection and system permission. On macOS, run python -m server.camera --check in the server terminal first.")
                self.capture.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                self.capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            except (cv2.error, RuntimeError) as error:
                self._release()
                message = str(error) if isinstance(error, RuntimeError) else "Cannot open camera. Check the device and system permission, then retry."
                raise RuntimeError(message) from error

    def get_frame(self):
        with self.lock:
            if self.capture is None:
                raise RuntimeError("Camera is off. Click Start camera first.")
            try:
                success, frame = self.capture.read()
                if not success:
                    raise RuntimeError("Cannot read camera image. Check the camera and try again.")
                success, jpeg = cv2.imencode(".jpg", frame)
                if not success:
                    raise RuntimeError("Cannot encode camera image. Try starting the camera again.")
                return jpeg.tobytes()
            except (cv2.error, RuntimeError) as error:
                # 设备断开、读图或编码失败都释放设备，方便下一次重新开启。
                self._release()
                message = str(error) if isinstance(error, RuntimeError) else "Camera image failed. Check the camera connection and try again."
                raise RuntimeError(message) from error

    def _release(self):
        # 仅在持有 lock 时调用，避免 stop() 再次获取同一把锁。
        if self.capture is not None:
            self.capture.release()
            self.capture = None

    def stop(self):
        with self.lock:
            self._release()


def check_camera():
    """在主线程首次申请权限、读取一帧，然后关闭；不保存图片。"""
    camera = CameraController()
    try:
        camera.start()
        jpeg = camera.get_frame()
        print(f"Camera OK: received {len(jpeg)} JPEG bytes. No image saved.")
        return 0
    except RuntimeError as error:
        print(f"Camera check failed: {error}")
        print("If macOS asks for permission, allow the terminal app, then run this check again.")
        return 1
    finally:
        camera.stop()
        print("Camera released.")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Check the local camera without saving images.")
    parser.add_argument("--check", action="store_true", required=True)
    parser.parse_args()
    raise SystemExit(check_camera())
