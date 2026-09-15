"""虚拟时钟和电机验证超时保护，不访问真实硬件或添加 HTTP 测试依赖。"""

import asyncio
import json
import unittest
from unittest.mock import Mock, call, patch
from uuid import UUID

from server import main


async def request(method, path, payload=None):
    """直接调用 ASGI 应用，同时覆盖 FastAPI 路由和请求校验。"""
    body = b"" if payload is None else json.dumps(payload).encode()
    responses = []

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message):
        responses.append(message)

    await main.app(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": method,
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "root_path": "",
            "headers": [(b"content-type", b"application/json")],
            "client": ("127.0.0.1", 1234),
            "server": ("test", 80),
        },
        receive,
        send,
    )
    code = next(message["status"] for message in responses if message["type"] == "http.response.start")
    data = b"".join(message.get("body", b"") for message in responses if message["type"] == "http.response.body")
    return code, json.loads(data)


class SafetyTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.now = 100.0
        self.motor = Mock()
        self.camera = Mock()
        for target, replacement in (("motor", self.motor), ("camera", self.camera)):
            patcher = patch.object(main, target, replacement)
            patcher.start()
            self.addCleanup(patcher.stop)
        clock = patch.object(main, "monotonic", side_effect=lambda: self.now)
        clock.start()
        self.addCleanup(clock.stop)
        main.status.update(
            connected=True,
            direction="stop",
            speed=0,
            battery=100,
            command_id=None,
            stop_reason=None,
            watchdog_timeout_ms=2000,
        )
        main.command_deadline = None

    async def move(self, direction="forward", speed=0.5):
        code, data = await request("POST", "/api/move", {"direction": direction, "speed": speed})
        self.assertEqual(code, 200)
        return data

    async def heartbeat(self, command_id):
        code, data = await request("POST", "/api/heartbeat", {"command_id": command_id})
        self.assertEqual(code, 200)
        return data

    def assert_stopped(self, data, reason):
        self.assertEqual(data["direction"], "stop")
        self.assertEqual(data["speed"], 0)
        self.assertIsNone(data["command_id"])
        self.assertEqual(data["stop_reason"], reason)
        self.assertIsNone(main.command_deadline)

    async def test_initial_status_and_version(self):
        code, data = await request("GET", "/api/status")
        self.assertEqual(code, 200)
        self.assertEqual(main.app.version, "0.4.0")
        self.assertEqual(data, {
            "connected": True, "direction": "stop", "speed": 0, "battery": 100,
            "command_id": None, "stop_reason": None, "watchdog_timeout_ms": 2000,
        })
        self.motor.stop.assert_not_called()

    async def test_directions_issue_distinct_tokens_and_keep_motor_mapping(self):
        tokens = set()
        for direction, motor_method in (
            ("forward", "forward"), ("backward", "backward"),
            ("left", "turn_left"), ("right", "turn_right"),
            ("forward", "forward"),
        ):
            data = await self.move(direction)
            self.assertEqual(data["direction"], direction)
            self.assertEqual(data["speed"], 0.5)
            self.assertIsNone(data["stop_reason"])
            self.assertEqual(UUID(data["command_id"]).version, 4)
            self.assertNotIn(data["command_id"], tokens)
            tokens.add(data["command_id"])
            getattr(self.motor, motor_method).assert_called_with(0.5)
            self.assertEqual(main.command_deadline, 102.0)

    async def test_status_stops_at_deadline_once(self):
        await self.move()
        self.now = 101.999
        _, data = await request("GET", "/api/status")
        self.assertEqual(data["direction"], "forward")
        self.now = 102.0
        _, data = await request("GET", "/api/status")
        self.assert_stopped(data, "timeout")
        self.now = 500.0
        await request("GET", "/api/status")
        main.check_timeout()
        self.motor.stop.assert_called_once_with()

    async def test_matching_heartbeat_renews_only_the_deadline(self):
        moving = await self.move()
        self.now = 101.5
        renewed = await self.heartbeat(moving["command_id"])
        self.assertEqual(renewed, moving)
        self.assertEqual(main.command_deadline, 103.5)
        self.now = 102.1
        _, data = await request("GET", "/api/status")
        self.assertEqual(data, moving)
        self.motor.forward.assert_called_once_with(0.5)
        self.motor.stop.assert_not_called()
        self.now = 103.5
        _, data = await request("GET", "/api/status")
        self.assert_stopped(data, "timeout")

    async def test_expired_heartbeat_cannot_revive_motion(self):
        moving = await self.move()
        self.now = 102.0
        expired = await self.heartbeat(moving["command_id"])
        self.assert_stopped(expired, "timeout")
        self.now = 102.5
        again = await self.heartbeat(moving["command_id"])
        self.assertEqual(again, expired)
        self.motor.stop.assert_called_once_with()
        self.motor.forward.assert_called_once_with(0.5)

    async def test_old_token_cannot_renew_a_new_move(self):
        old = await self.move()
        self.now = 100.5
        current = await self.move("left", 0.8)
        self.now = 102.0
        self.assertEqual(await self.heartbeat(old["command_id"]), current)
        self.assertEqual(main.command_deadline, 102.5)
        self.now = 102.5
        _, data = await request("GET", "/api/status")
        self.assert_stopped(data, "timeout")

    async def test_move_checks_previous_deadline_before_starting_new_motion(self):
        await self.move()
        self.now = 102.0
        current = await self.move("right", 0.6)
        self.assertEqual(self.motor.mock_calls, [call.forward(0.5), call.stop(), call.turn_right(0.6)])
        self.assertEqual(current["direction"], "right")
        self.assertIsNone(current["stop_reason"])
        self.assertEqual(main.command_deadline, 104.0)

    async def test_manual_stop_clears_token_and_ignores_delayed_heartbeat(self):
        moving = await self.move()
        stopped = await self.move("stop", 1)
        self.assert_stopped(stopped, "manual")
        self.now = 110.0
        self.assertEqual(await self.heartbeat(moving["command_id"]), stopped)
        self.motor.stop.assert_called_once_with()

    async def test_idle_heartbeat_does_not_start_motion(self):
        data = await self.heartbeat("unknown-token")
        self.assert_stopped(data, None)
        self.assertEqual(self.motor.mock_calls, [])

    async def test_watchdog_stops_without_status_requests_and_is_cancelled(self):
        stopped = asyncio.Event()
        self.motor.stop.side_effect = stopped.set
        async with main.lifespan(main.app):
            moving = await self.move()
            self.now = 102.0
            await asyncio.wait_for(stopped.wait(), timeout=1)
            self.assert_stopped(main.status, "timeout")
            await asyncio.sleep(0.12)
            self.motor.stop.assert_called_once_with()
            self.assertEqual(await self.heartbeat(moving["command_id"]), main.status)
            self.assertTrue(any(task.get_name() == "homebot-watchdog" for task in asyncio.all_tasks()))
        self.assertFalse(any(task.get_name() == "homebot-watchdog" for task in asyncio.all_tasks()))
        self.assert_stopped(main.status, "shutdown")
        self.camera.stop.assert_called_once_with()

    async def test_shutdown_stops_active_motor_and_camera(self):
        async with main.lifespan(main.app):
            moving = await self.move()
        self.assert_stopped(main.status, "shutdown")
        self.motor.stop.assert_called_once_with()
        self.camera.stop.assert_called_once_with()
        self.assert_stopped(await self.heartbeat(moving["command_id"]), "shutdown")

    async def test_exceptional_shutdown_still_releases_resources(self):
        with self.assertRaisesRegex(RuntimeError, "application error"):
            async with main.lifespan(main.app):
                await self.move()
                raise RuntimeError("application error")
        self.assert_stopped(main.status, "shutdown")
        self.motor.stop.assert_called_once_with()
        self.camera.stop.assert_called_once_with()

    async def test_camera_is_released_even_if_shutdown_motor_stop_fails(self):
        self.motor.stop.side_effect = RuntimeError("motor error")
        with self.assertRaisesRegex(RuntimeError, "motor error"):
            async with main.lifespan(main.app):
                await self.move()
        self.assert_stopped(main.status, "shutdown")
        self.camera.stop.assert_called_once_with()

    async def test_heartbeat_validation_does_not_extend_active_motion(self):
        await self.move()
        for payload in ({}, {"command_id": ""}, {"command_id": None}, {"command_id": 123}, {"command_id": []}):
            with self.subTest(payload=payload):
                code, _ = await request("POST", "/api/heartbeat", payload)
                self.assertEqual(code, 422)
                self.assertEqual(main.command_deadline, 102.0)
        self.motor.stop.assert_not_called()

    async def test_move_validation_preserves_state(self):
        for payload in (
            {"direction": "up", "speed": 0.5},
            {"direction": "forward", "speed": -0.1},
            {"direction": "forward", "speed": 1.1},
            {"direction": "forward"}, {},
        ):
            with self.subTest(payload=payload):
                code, _ = await request("POST", "/api/move", payload)
                self.assertEqual(code, 422)
                self.assert_stopped(main.status, None)
        self.assertEqual(self.motor.mock_calls, [])


if __name__ == "__main__":
    unittest.main()
