"""不打开真实摄像头：用替身验证图片编码、失败处理与资源释放。"""

import unittest
import io
import os
import sys
from contextlib import redirect_stdout
from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import Mock, patch

import cv2
import numpy as np

from server.camera import CameraController, check_camera


class CameraTests(unittest.TestCase):
    def setUp(self):
        environment = patch.dict(os.environ, {"HOMEBOT_CAMERA": "opencv"})
        environment.start()
        self.addCleanup(environment.stop)
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

    def test_opencv_does_not_import_picamera2(self):
        with patch.dict(sys.modules, {"picamera2": None}):
            self.camera.start()
            self.assertTrue(self.camera.get_frame().startswith(b"\xff\xd8"))

    def test_environment_selection_and_explicit_override(self):
        with patch.dict(os.environ, {"HOMEBOT_CAMERA": "picamera2"}):
            self.assertEqual(CameraController().backend, "picamera2")
            self.assertEqual(CameraController("opencv").backend, "opencv")
        with patch.dict(os.environ, {"HOMEBOT_CAMERA": "typo"}):
            with self.assertRaisesRegex(ValueError, "HOMEBOT_CAMERA"):
                CameraController()


class Picamera2Tests(unittest.TestCase):
    def setUp(self):
        self.device = Mock()
        # RGB888 在 Picamera2 中是 BGR 字节顺序：使用红色帧检查没有错误换色。
        self.frame = np.zeros((480, 640, 3), dtype=np.uint8)
        self.frame[:, :, 2] = 255
        self.device.capture_array.return_value = self.frame
        self.factory = Mock(return_value=self.device)
        module = patch.dict(sys.modules, {"picamera2": SimpleNamespace(Picamera2=self.factory)})
        module.start()
        self.addCleanup(module.stop)
        opencv = patch("server.camera.cv2.VideoCapture")
        self.opencv = opencv.start()
        self.addCleanup(opencv.stop)
        self.camera = CameraController("picamera2")
        self.addCleanup(self.camera.stop)

    def test_lazy_open_configuration_jpeg_and_color_order(self):
        self.factory.assert_not_called()
        with self.assertRaisesRegex(RuntimeError, "Camera is off"):
            self.camera.get_frame()
        self.camera.start()
        self.device.create_video_configuration.assert_called_once_with(
            main={"size": (640, 480), "format": "RGB888"}
        )
        self.device.configure.assert_called_once_with(self.device.create_video_configuration.return_value)
        self.device.start.assert_called_once_with()
        data = self.camera.get_frame()
        self.device.capture_array.assert_called_once_with("main")
        decoded = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
        self.assertEqual(decoded.shape, (480, 640, 3))
        self.assertGreater(int(decoded[240, 320, 2]), 250)
        self.assertLess(int(decoded[240, 320, 0]), 5)
        self.opencv.assert_not_called()

    def test_repeat_start_stop_and_reopen_with_new_instance(self):
        self.camera.start()
        self.camera.start()
        self.factory.assert_called_once_with()
        self.camera.stop()
        self.camera.stop()
        self.assertEqual([call[0] for call in self.device.mock_calls][-2:], ["stop", "close"])
        self.device.stop.assert_called_once_with()
        self.device.close.assert_called_once_with()
        other = Mock()
        other.capture_array.return_value = self.frame
        self.factory.return_value = other
        self.camera.start()
        self.assertIs(self.camera.capture, other)
        self.assertTrue(self.camera.get_frame().startswith(b"\xff\xd8"))

    def test_missing_dependency_is_actionable_and_does_not_fall_back(self):
        with patch.dict(sys.modules, {"picamera2": None}):
            with self.assertRaisesRegex(RuntimeError, "python3-picamera2.*--system-site-packages"):
                self.camera.start()
        self.assertIsNone(self.camera.capture)
        self.opencv.assert_not_called()
        self.camera.start()
        self.assertTrue(self.camera.get_frame())

    def test_constructor_failure_allows_retry(self):
        self.factory.side_effect = IndexError("no camera available")
        with self.assertRaisesRegex(RuntimeError, "Cannot open camera.*no camera available"):
            self.camera.start()
        self.assertIsNone(self.camera.capture)
        self.factory.side_effect = None
        self.camera.start()
        self.assertTrue(self.camera.get_frame())

    def test_each_setup_failure_closes_device_and_allows_restart(self):
        for method in ("create_video_configuration", "configure", "start"):
            with self.subTest(method=method):
                self.device.reset_mock()
                getattr(self.device, method).side_effect = ValueError("setup failed")
                with self.assertRaisesRegex(RuntimeError, "Cannot open camera.*setup failed"):
                    self.camera.start()
                self.device.close.assert_called_once_with()
                self.assertIsNone(self.camera.capture)
                getattr(self.device, method).side_effect = None
                self.camera.start()
                self.assertTrue(self.camera.get_frame())
                self.camera.stop()

    def test_read_exception_closes_device_and_allows_restart(self):
        self.camera.start()
        self.device.capture_array.side_effect = OSError("capture failed")
        with self.assertRaisesRegex(RuntimeError, "Camera image failed.*capture failed"):
            self.camera.get_frame()
        self.device.close.assert_called_once_with()
        self.assertIsNone(self.camera.capture)
        self.device.capture_array.side_effect = None
        self.camera.start()
        self.assertTrue(self.camera.get_frame())

    def test_empty_frames_release_camera(self):
        for frame in (None, np.array([])):
            with self.subTest(frame=frame):
                self.camera.start()
                self.device.capture_array.return_value = frame
                with self.assertRaisesRegex(RuntimeError, "Cannot read camera"):
                    self.camera.get_frame()
                self.assertIsNone(self.camera.capture)
        self.assertEqual(self.device.close.call_count, 2)

    def test_encode_failures_release_camera_and_allow_restart(self):
        for kwargs in ({"return_value": (False, None)}, {"side_effect": cv2.error("encode failed")}):
            with self.subTest(kwargs=kwargs):
                self.camera.start()
                with patch("server.camera.cv2.imencode", **kwargs):
                    with self.assertRaises(RuntimeError):
                        self.camera.get_frame()
                self.assertIsNone(self.camera.capture)
                self.camera.start()
                self.assertTrue(self.camera.get_frame())
                self.camera.stop()

    def test_stop_exception_still_closes_camera(self):
        self.camera.start()
        self.device.stop.side_effect = OSError("stop failed")
        with self.assertLogs("server.camera", level="WARNING"):
            self.camera.stop()
        self.device.close.assert_called_once_with()
        self.assertIsNone(self.camera.capture)

    def test_stop_waits_for_in_progress_capture(self):
        reading, finish_read, stopping = Event(), Event(), Event()

        def read_frame(*args):
            reading.set()
            if not finish_read.wait(3):
                raise RuntimeError("test timed out waiting to finish read")
            return self.frame

        def stop_camera():
            stopping.set()
            self.camera.stop()

        self.camera.start()
        self.device.capture_array.side_effect = read_frame
        with ThreadPoolExecutor(max_workers=2) as pool:
            read = pool.submit(self.camera.get_frame)
            try:
                self.assertTrue(reading.wait(3))
                stop = pool.submit(stop_camera)
                self.assertTrue(stopping.wait(3))
                self.device.close.assert_not_called()
            finally:
                finish_read.set()
            self.assertTrue(read.result(timeout=3).startswith(b"\xff\xd8"))
            stop.result(timeout=3)
        self.device.close.assert_called_once_with()

    def test_close_failure_retains_handle_and_prevents_second_open(self):
        self.camera.start()
        self.device.close.side_effect = OSError("close failed")
        try:
            with self.assertRaisesRegex(RuntimeError, "Cannot close camera"):
                self.camera.stop()
            self.assertIs(self.camera.capture, self.device)
            with self.assertRaisesRegex(RuntimeError, "Camera is off"):
                self.camera.get_frame()
            with self.assertRaisesRegex(RuntimeError, "Cannot close camera"):
                self.camera.start()
            self.factory.assert_called_once_with()
        finally:
            self.device.close.side_effect = None
        self.camera.start()
        self.assertEqual(self.factory.call_count, 2)
        self.assertTrue(self.camera.get_frame())

    def test_cleanup_failure_does_not_hide_original_failure(self):
        self.device.configure.side_effect = ValueError("bad config")
        self.device.close.side_effect = OSError("close failed")
        try:
            with self.assertRaisesRegex(RuntimeError, "bad config.*Cleanup also failed.*close failed"):
                self.camera.start()
        finally:
            self.device.close.side_effect = None

    def test_check_selects_picamera2_and_releases_it(self):
        with redirect_stdout(io.StringIO()) as output:
            self.assertEqual(check_camera("picamera2"), 0)
        self.assertIn("Camera OK (picamera2)", output.getvalue())
        self.device.close.assert_called_once_with()

    def test_check_does_not_claim_release_when_close_failed(self):
        self.device.close.side_effect = OSError("close failed")
        with redirect_stdout(io.StringIO()) as output:
            self.assertEqual(check_camera("picamera2"), 1)
        self.assertIn("Camera cleanup failed", output.getvalue())
        self.assertNotIn("Camera released.", output.getvalue())


if __name__ == "__main__":
    unittest.main()
