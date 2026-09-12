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
            capture = cv2.VideoCapture(0)
            if not capture.isOpened():
                capture.release()
                raise RuntimeError("Cannot open camera. Check the camera connection and system permission.")
            capture.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            self.capture = capture

    def get_frame(self):
        with self.lock:
            if self.capture is None:
                raise RuntimeError("Camera is off. Click Start camera first.")
            success, frame = self.capture.read()
            if not success:
                self.capture.release()
                self.capture = None
                raise RuntimeError("Cannot read camera image. Check the camera and try again.")
            success, jpeg = cv2.imencode(".jpg", frame)
            if not success:
                raise RuntimeError("Cannot encode camera image. Stop the camera and try again.")
            return jpeg.tobytes()

    def stop(self):
        with self.lock:
            if self.capture is not None:
                self.capture.release()
                self.capture = None
