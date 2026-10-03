"""Picamera2 替身经过真实 ASGI 路由，验证原网页依赖的接口契约。"""

import json
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import cv2
import numpy as np

from server import main
from server.camera import CameraController
from test_access import basic, request


class CameraAPITests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.device = Mock()
        self.device.capture_array.return_value = np.zeros((480, 640, 3), dtype=np.uint8)
        self.factory = Mock(return_value=self.device)
        self.camera = CameraController("picamera2")
        for patcher in (
            patch.dict(os.environ, {"HOMEBOT_ACCESS_CODE": "test-access-code", "HOMEBOT_MOTOR": "mock"}),
            patch.dict(sys.modules, {"picamera2": SimpleNamespace(Picamera2=self.factory)}),
            patch.object(main, "camera", self.camera),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(self.camera.stop)

    async def camera_request(self, method, action):
        return await request(method, f"/api/camera/{action}", headers={"authorization": basic()})

    async def test_start_frame_stop_restart_contract(self):
        for _ in range(2):
            code, _, data = await self.camera_request("POST", "start")
            self.assertEqual((code, json.loads(data)), (200, {"active": True}))
            code, headers, data = await self.camera_request("GET", "frame")
            self.assertEqual(code, 200)
            self.assertEqual(headers["content-type"], "image/jpeg")
            self.assertEqual(headers["cache-control"], "no-store")
            image = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
            self.assertEqual(image.shape, (480, 640, 3))
            for _ in range(2):
                code, _, data = await self.camera_request("POST", "stop")
                self.assertEqual((code, json.loads(data)), (200, {"active": False}))
            code, _, data = await self.camera_request("GET", "frame")
            self.assertEqual(code, 503)
            self.assertIn("Camera is off", json.loads(data)["detail"])
        self.assertEqual(self.factory.call_count, 2)
        self.assertEqual(self.device.close.call_count, 2)

    async def test_start_and_read_failures_are_503_and_recoverable(self):
        for method, action, failing_method in (
            ("POST", "start", "configure"), ("GET", "frame", "capture_array"),
        ):
            with self.subTest(action=action):
                if action == "frame":
                    await self.camera_request("POST", "start")
                getattr(self.device, failing_method).side_effect = OSError("device failure")
                code, _, data = await self.camera_request(method, action)
                self.assertEqual(code, 503)
                self.assertIn("device failure", json.loads(data)["detail"])
                self.assertIsNone(self.camera.capture)
                getattr(self.device, failing_method).side_effect = None
                code, _, _ = await self.camera_request("POST", "start")
                self.assertEqual(code, 200)
                code, _, _ = await self.camera_request("GET", "frame")
                self.assertEqual(code, 200)
                await self.camera_request("POST", "stop")

    async def test_stop_failure_is_503_then_retry_succeeds(self):
        await self.camera_request("POST", "start")
        self.device.close.side_effect = OSError("device busy")
        try:
            code, _, data = await self.camera_request("POST", "stop")
            self.assertEqual(code, 503)
            self.assertIn("Cannot close camera", json.loads(data)["detail"])
        finally:
            self.device.close.side_effect = None
        code, _, data = await self.camera_request("POST", "stop")
        self.assertEqual((code, json.loads(data)), (200, {"active": False}))

    async def test_shutdown_releases_active_picamera2(self):
        async with main.lifespan(main.app):
            await self.camera_request("POST", "start")
            self.assertIsNotNone(self.camera.capture)
        self.device.stop.assert_called_once_with()
        self.device.close.assert_called_once_with()
        self.assertIsNone(self.camera.capture)


if __name__ == "__main__":
    unittest.main()
