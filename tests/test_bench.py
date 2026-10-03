"""单电机台架 API 的保护行为；不加载 GPIO、不启动真实硬件。"""
import asyncio
import os
import unittest
from unittest.mock import Mock, patch

from server import main
import test_safety as safety

request = safety.request


class BenchTests(unittest.IsolatedAsyncioTestCase):
    motor_mode = "tb6612"

    def setUp(self):
        safety.SafetyTests.setUp(self)
        self.motor.mode = self.motor_mode
        self.motor.max_speed = 0.4
        self.motor.supported_directions = ("forward", "backward", "stop")
        main.reset_status(self.motor)

    async def move(self, direction="forward", speed=0.2, **extra):
        return await request("POST", "/api/move", {
            "direction": direction, "speed": speed,
            "control_epoch": main.status["control_epoch"], **extra,
        })

    async def test_bench_metadata_has_no_fake_battery_or_feedback(self):
        code, data = await request("GET", "/api/status")
        self.assertEqual(code, 200)
        self.assertEqual(data["motor_mode"], self.motor_mode)
        self.assertIsNone(data["battery"])
        self.assertEqual(data["max_speed"], 0.4)
        self.assertEqual(data["supported_directions"], ["forward", "backward", "stop"])

    async def test_missing_or_old_epoch_cannot_move_a_real_motor(self):
        for extra in ({}, {"control_epoch": "old-page"}):
            code, _ = await request("POST", "/api/move", {"direction": "forward", "speed": 0.2, **extra})
            self.assertEqual(code, 409)
        self.motor.forward.assert_not_called()

    async def test_delayed_move_cannot_cross_stop_or_timeout(self):
        old_epoch = main.status["control_epoch"]
        code, moving = await self.move()
        self.assertEqual(code, 200)
        code, stopped = await self.move("stop", 0, control_epoch="stale-but-stop-is-always-allowed")
        self.assertEqual(code, 200)
        self.assertNotEqual(stopped["control_epoch"], old_epoch)
        self.assertEqual((await self.move(control_epoch=old_epoch))[0], 409)
        self.motor.forward.assert_called_once_with(0.2)
        self.assertEqual(main.status["direction"], "stop")
        self.assertEqual((await self.move())[0], 200)
        old_epoch = main.status["control_epoch"]
        self.now += 2
        self.assertEqual((await self.move(control_epoch=old_epoch))[0], 409)
        self.assertEqual(main.status["stop_reason"], "timeout")
        self.assertEqual(self.motor.forward.call_count, 2)
        # 旧心跳也不能恢复曾经的动作。
        _, data = await request("POST", "/api/heartbeat", {"command_id": moving["command_id"]})
        self.assertEqual(data["direction"], "stop")

    async def test_turns_and_excess_speed_do_not_touch_hardware(self):
        for direction, speed in (("left", 0.2), ("right", 0.2), ("forward", 0.41), ("backward", 1)):
            self.assertEqual((await self.move(direction, speed))[0], 422)
        self.assertEqual(self.motor.mock_calls, [])

    async def test_zero_output_is_a_stop_and_invalidates_old_commands(self):
        await self.move()
        epoch = main.status["control_epoch"]
        code, data = await self.move(speed=0)
        self.assertEqual(code, 200)
        self.assertEqual(data["direction"], "stop")
        self.assertEqual(data["speed"], 0)
        self.assertNotEqual(data["control_epoch"], epoch)
        self.motor.forward.assert_called_once_with(0.2)
        self.motor.stop.assert_called_once_with()

    async def test_reversal_requires_stop_and_at_least_half_a_second(self):
        await self.move()
        self.assertEqual((await self.move("backward"))[0], 409)
        self.motor.backward.assert_not_called()
        await self.move("stop", 0)
        self.now += 0.49
        self.assertEqual((await self.move("backward"))[0], 409)
        self.now += 0.01
        self.assertEqual((await self.move("backward"))[0], 200)
        self.motor.backward.assert_called_once_with(0.2)

    async def test_partly_executed_move_failure_attempts_stop_and_locks_motion(self):
        def fail_after_output(speed):
            self.assertIsNotNone(main.command_deadline)
            raise RuntimeError("GPIO write failed after a partial output")
        self.motor.forward.side_effect = fail_after_output
        with self.assertLogs(main.logger, level="ERROR"):
            code, _ = await self.move()
        self.assertEqual(code, 503)
        self.motor.stop.assert_called_once_with()
        self.assertEqual(main.status["direction"], "stop")
        self.assertFalse(main.status["connected"])
        self.assertIsNotNone(main.status["fault"])
        self.assertEqual((await self.move())[0], 503)
        self.assertEqual(self.motor.forward.call_count, 1)
        # STOP 可以重试，但不能自行解锁。
        self.assertEqual((await self.move("stop", 0))[0], 200)
        self.assertIsNotNone(main.status["fault"])

    async def test_stop_failure_never_claims_zero_or_allows_heartbeat_renewal(self):
        _, moving = await self.move()
        self.motor.stop.side_effect = RuntimeError("GPIO off failed")
        with self.assertLogs(main.logger, level="ERROR"):
            self.assertEqual((await self.move("stop", 0))[0], 503)
        self.assertEqual(main.status["direction"], "unknown")
        self.assertIsNone(main.status["speed"])
        self.assertIsNone(main.status["command_id"])
        self.assertIsNotNone(main.stop_retry_deadline)
        await request("POST", "/api/heartbeat", {"command_id": moving["command_id"]})
        self.assertIsNone(main.command_deadline)
        self.motor.stop.side_effect = None
        self.now += 0.5
        await request("GET", "/api/status")
        self.assertEqual(main.status["direction"], "stop")
        self.assertIsNotNone(main.status["fault"])

    async def test_background_watchdog_survives_stop_failure_and_retries(self):
        failed = asyncio.Event()
        recovered = asyncio.Event()
        attempts = 0
        def stop():
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                failed.set()
                raise RuntimeError("temporary GPIO error")
            recovered.set()
        self.motor.stop.side_effect = stop
        with self.assertLogs(main.logger, level="ERROR"):
            async with main.lifespan(main.app):
                await self.move()
                self.now += 2
                await asyncio.wait_for(failed.wait(), timeout=1)
                self.assertEqual(main.status["direction"], "unknown")
                self.now += 0.5
                await asyncio.wait_for(recovered.wait(), timeout=1)
                self.assertEqual(main.status["direction"], "stop")
                self.assertIsNotNone(main.status["fault"])
                self.assertTrue(any(task.get_name() == "homebot-watchdog" for task in asyncio.all_tasks()))
        self.motor.close.assert_called_once_with()

    async def test_cleanup_failure_still_releases_camera_and_reports_fault(self):
        self.motor.close.side_effect = RuntimeError("cannot close GPIO")
        with self.assertLogs(main.logger, level="ERROR"):
            async with main.lifespan(main.app):
                await self.move()
        self.camera.stop.assert_called_once_with()
        self.assertEqual(main.status["direction"], "unknown")
        self.assertIn("cleanup failed", main.status["fault"])

    async def test_controller_is_built_only_at_startup_and_failure_aborts(self):
        with patch.object(main, "build_motor", side_effect=RuntimeError("no GPIO device")):
            with self.assertRaisesRegex(RuntimeError, "no GPIO device"):
                async with main.lifespan(main.app):
                    self.fail("Startup must fail without silently using mock")
        self.assertFalse(any(task.get_name() == "homebot-watchdog" for task in asyncio.all_tasks()))


class DRV8833BenchTests(BenchTests):
    motor_mode = "drv8833"


class ControllerSelectionTests(unittest.TestCase):
    def test_default_is_mock_and_unknown_mode_is_an_error(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(main.build_motor().mode, "mock")
        with patch.dict(os.environ, {"HOMEBOT_MOTOR": "mock"}):
            self.assertEqual(main.build_motor().mode, "mock")
        with patch.dict(os.environ, {"HOMEBOT_MOTOR": "invalid"}):
            with self.assertRaises(ValueError):
                main.build_motor()

    def test_explicit_real_modes_construct_only_the_matching_controller(self):
        with patch("server.tb6612.TB6612MotorController") as tb6612, patch("server.drv8833.DRV8833MotorController") as drv8833:
            for mode, controller, other in (("tb6612", tb6612, drv8833), ("drv8833", drv8833, tb6612)):
                with self.subTest(mode=mode), patch.dict(os.environ, {"HOMEBOT_MOTOR": mode}):
                    self.assertIs(main.build_motor(), controller.return_value)
                controller.assert_called_once_with()
                other.assert_not_called()
                controller.reset_mock()

    def test_real_controller_failure_does_not_fall_back_to_mock(self):
        for mode, name in (("tb6612", "TB6612MotorController"), ("drv8833", "DRV8833MotorController")):
            with self.subTest(mode=mode), patch.dict(os.environ, {"HOMEBOT_MOTOR": mode}), patch(f"server.{mode}.{name}", side_effect=RuntimeError("no local GPIO")):
                with self.assertRaisesRegex(RuntimeError, "no local GPIO"):
                    main.build_motor()


if __name__ == "__main__":
    unittest.main()
