"""不打开真实摄像头：用替身验证图片编码、失败处理与资源释放。"""

import unittest
import io
from contextlib import redirect_stdout
from unittest.mock import Mock, patch

import cv2
import numpy as np

from server.camera import CameraController, check_camera


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
        self.capture.release.assert_called_once()
        self.assertIsNone(self.camera.capture)

    def test_opencv_open_exception_becomes_readable_error(self):
        self.capture.isOpened.side_effect = cv2.error("test device failure")
        with self.assertRaisesRegex(RuntimeError, "Cannot open camera"):
            self.camera.start()
        self.capture.release.assert_called_once()
        self.assertIsNone(self.camera.capture)

    def test_opencv_setup_exception_releases_camera(self):
        self.capture.set.side_effect = cv2.error("test setup failure")
        with self.assertRaisesRegex(RuntimeError, "Cannot open camera"):
            self.camera.start()
        self.capture.release.assert_called_once()
        self.assertIsNone(self.camera.capture)

    def test_opencv_read_exception_allows_restart(self):
        self.camera.start()
        self.capture.read.side_effect = cv2.error("test disconnected device")
        with self.assertRaisesRegex(RuntimeError, "Camera image failed"):
            self.camera.get_frame()
        self.capture.release.assert_called_once()
        self.assertIsNone(self.camera.capture)
        self.capture.read.side_effect = None
        self.camera.start()
        self.assertTrue(self.camera.get_frame().startswith(b"\xff\xd8"))

    def test_opencv_encode_exception_releases_camera(self):
        self.camera.start()
        with patch("server.camera.cv2.imencode", side_effect=cv2.error("test encode failure")):
            with self.assertRaisesRegex(RuntimeError, "Camera image failed"):
                self.camera.get_frame()
        self.capture.release.assert_called_once()
        self.assertIsNone(self.camera.capture)

    def test_command_line_check_releases_after_success(self):
        with redirect_stdout(io.StringIO()) as output:
            self.assertEqual(check_camera(), 0)
        self.assertIn("Camera OK", output.getvalue())
        self.capture.release.assert_called_once()

    def test_command_line_check_reports_permission_failure(self):
        self.capture.isOpened.return_value = False
        with redirect_stdout(io.StringIO()) as output:
            self.assertEqual(check_camera(), 1)
        self.assertIn("permission", output.getvalue())
        self.capture.release.assert_called_once()


if __name__ == "__main__":
    unittest.main()
