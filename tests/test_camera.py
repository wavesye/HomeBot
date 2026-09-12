"""不打开真实摄像头：用替身验证图片编码、失败处理与资源释放。"""

import unittest
from unittest.mock import Mock, patch

import cv2
import numpy as np

from server.camera import CameraController


class CameraTests(unittest.TestCase):
    def setUp(self):
        self.camera = CameraController()
        self.capture = Mock()
        self.capture.isOpened.return_value = True
        self.capture.read.return_value = (True, np.zeros((48, 64, 3), dtype=np.uint8))
        self.factory = patch("server.camera.cv2.VideoCapture", return_value=self.capture)
        self.factory.start()
        self.addCleanup(self.factory.stop)
        self.addCleanup(self.camera.stop)

    def test_frame_is_a_decodable_jpeg(self):
        self.camera.start()
        data = self.camera.get_frame()
        decoded = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
        self.assertEqual(decoded.shape, (48, 64, 3))

    def test_start_and_stop_are_repeatable(self):
        self.camera.start()
        self.camera.start()
        self.camera.stop()
        self.camera.stop()
        self.capture.release.assert_called_once()
        self.camera.start()
        self.assertIs(self.camera.capture, self.capture)

    def test_frame_when_off_does_not_open_camera(self):
        with self.assertRaisesRegex(RuntimeError, "Camera is off"):
            self.camera.get_frame()
        self.capture.read.assert_not_called()

    def test_open_failure_releases_camera(self):
        self.capture.isOpened.return_value = False
        with self.assertRaisesRegex(RuntimeError, "Cannot open camera"):
            self.camera.start()
        self.capture.release.assert_called_once()
        self.assertIsNone(self.camera.capture)

    def test_read_failure_releases_camera(self):
        self.camera.start()
        self.capture.read.return_value = (False, None)
        with self.assertRaisesRegex(RuntimeError, "Cannot read camera"):
            self.camera.get_frame()
        self.capture.release.assert_called_once()
        self.assertIsNone(self.camera.capture)

    def test_encode_failure_has_clear_error(self):
        self.camera.start()
        with patch("server.camera.cv2.imencode", return_value=(False, None)):
            with self.assertRaisesRegex(RuntimeError, "Cannot encode camera"):
                self.camera.get_frame()


if __name__ == "__main__":
    unittest.main()
