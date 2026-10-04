"""双轮 API 与故障恢复约束；不访问 GPIO 或真实电机。"""
import asyncio
import os
import sys
import types
import unittest
from unittest.mock import patch

from server import drive, main
from test_motor import FakeDevice, FakeFactory
import test_safety as safety

request = safety.request


class ChassisTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        safety.SafetyTests.setUp(self)
        self.motor.mode = "drv8833-dual"
        self.motor.max_speed = 0.3
        self.motor.supported_directions = ("forward", "backward", "left", "right", "stop")
        self.motor.invert_left = False
        self.motor.invert_right = True
        main.reset_status(self.motor)

    async def move(self, direction="forward", speed=0.2, **extra):
        return await request("POST", "/api/move", {
            "direction": direction, "speed": speed,
            "control_epoch": main.status["control_epoch"], **extra,
        })

    async def test_status_reports_low_limit_and_installed_polarities_not_telemetry(self):
        code, data = await request("GET", "/api/status")
        self.assertEqual(code, 200)
        self.assertEqual(data["motor_mode"], "drv8833-dual")
        self.assertEqual(data["max_speed"], 0.3)
        self.assertEqual(data["supported_directions"], list(self.motor.supported_directions))
        self.assertFalse(data["left_inverted"])
        self.assertTrue(data["right_inverted"])
        self.assertIsNone(data["battery"])
        self.assertEqual(data["direction"], "stop")

    async def test_all_four_directions_use_the_same_controller_interface(self):
        for direction, method in (("forward", self.motor.forward), ("backward", self.motor.backward), ("left", self.motor.turn_left), ("right", self.motor.turn_right)):
            with self.subTest(direction=direction):
                code, data = await self.move(direction, 0.3)
                self.assertEqual(code, 200)
                self.assertEqual(data["direction"], direction)
                method.assert_called_once_with(0.3)
                await self.move("stop", 0)
                self.now += 0.5

    async def test_every_direction_change_requires_stop_and_a_fresh_pause(self):
        directions = ("forward", "backward", "left", "right")
        for old in directions:
            for new in directions:
                if old == new:
                    continue
                with self.subTest(old=old, new=new):
                    main.reset_status(self.motor)
                    self.assertEqual((await self.move(old))[0], 200)
                    code, data = await self.move(new)
                    self.assertEqual(code, 409)
                    self.assertIn("both wheels", data["detail"])
                    await self.move("stop", 0)
                    self.now += 0.49
                    self.assertEqual((await self.move(new))[0], 409)
                    self.now += 0.011
                    self.assertEqual((await self.move(new))[0], 200)

    async def test_same_direction_can_change_pwm_within_the_limit(self):
        await self.move("left", 0.2)
        code, data = await self.move("left", 0.3)
        self.assertEqual(code, 200)
        self.assertEqual(data["speed"], 0.3)
        self.motor.turn_left.assert_any_call(0.3)

    async def test_excess_pwm_and_missing_or_stale_epoch_never_move(self):
        self.assertEqual((await self.move(speed=0.31))[0], 422)
        self.assertEqual((await self.move(control_epoch="old"))[0], 409)
        self.assertEqual((await request("POST", "/api/move", {"direction": "forward", "speed": 0.2}))[0], 409)
        self.motor.forward.assert_not_called()
        # STOP 不受旧代号或台架限速限制，但 speed 仍需在 API 的有效 0..1 范围。
        self.assertEqual((await self.move("stop", 1, control_epoch="old"))[0], 200)
        self.motor.stop.assert_called_once_with()

    async def test_stop_and_timeout_reject_delayed_commands_and_heartbeats(self):
        for reason in ("manual", "timeout"):
            with self.subTest(reason=reason):
                main.reset_status(self.motor)
                old_epoch = main.status["control_epoch"]
                _, moving = await self.move()
                if reason == "manual":
                    await self.move("stop", 0)
                else:
                    self.now += 2
                    main.check_timeout()
                self.assertEqual((await self.move(control_epoch=old_epoch))[0], 409)
                _, status = await request("POST", "/api/heartbeat", {"command_id": moving["command_id"]})
                self.assertIsNone(status["command_id"])
                self.assertEqual(status["direction"], "stop")
                self.assertEqual(status["stop_reason"], reason)

    async def test_gpio_controller_starts_moves_and_stops_without_button_or_gpio23(self):
        factory = FakeFactory()
        factory.fail_create = 23  # GPIO23 无论是否可用，都不应被双轮模式申请。
        gpiozero = types.ModuleType("gpiozero")
        gpiozero.DigitalOutputDevice = FakeDevice
        gpiozero.PWMOutputDevice = FakeDevice  # 不提供 Button，防止再次引入按钮依赖。
        with patch.dict(sys.modules, {"gpiozero": gpiozero}), patch.object(drive, "sleep"):
            controller = drive.DRV8833DriveController(pin_factory=factory)
        with patch.object(main, "build_motor", return_value=controller):
            async with main.lifespan(main.app):
                code, data = await request("GET", "/api/status")
                self.assertEqual(code, 200)
                self.assertIsNone(data["fault"])
                self.assertEqual(data["direction"], "stop")
                self.assertTrue(all(device.value == 0 for device in factory.devices.values()))
                with patch.object(drive, "sleep"):
                    self.assertEqual((await self.move())[0], 200)
                self.assertEqual(factory.devices[17].value, 0.2)
                self.assertEqual(factory.devices[5].value, 0.2)
                self.assertEqual((await self.move("stop", 0))[0], 200)
                self.assertTrue(all(device.value == 0 for device in factory.devices.values()))
        self.assertEqual(set(factory.devices), {17, 27, 5, 6, 22})
        self.assertTrue(controller._closed)

    async def test_background_timeout_stops_without_browser_requests(self):
        stopped = asyncio.Event()
        self.motor.stop.side_effect = stopped.set
        async with main.lifespan(main.app):
            await self.move()
            self.now += 2
            await asyncio.wait_for(stopped.wait(), timeout=1)
            self.assertEqual(main.status["direction"], "stop")
            self.assertEqual(main.status["stop_reason"], "timeout")
            self.assertIsNone(main.status["fault"])
        self.motor.close.assert_called_once_with()

    async def test_timeout_with_failed_stop_is_not_reported_as_stopped(self):
        await self.move()
        self.now += 2
        self.motor.stop.side_effect = OSError("GPIO write failed")
        with self.assertLogs(main.logger, level="ERROR"):
            main.check_timeout()
        self.assertEqual(main.status["direction"], "unknown")
        self.assertIsNone(main.status["speed"])
        self.assertIsNone(main.command_deadline)
        self.assertIsNotNone(main.stop_retry_deadline)
        self.motor.stop.side_effect = None
        self.now += 0.5
        main.check_timeout()
        self.assertEqual(main.status["direction"], "stop")
        self.assertIsNotNone(main.status["fault"])

    async def test_partial_dual_output_failure_stops_both_and_locks_motion(self):
        self.motor.turn_left.side_effect = RuntimeError("second wheel failed")
        with self.assertLogs(main.logger, level="ERROR"):
            self.assertEqual((await self.move("left"))[0], 503)
        self.motor.stop.assert_called_once_with()
        self.assertEqual(main.status["direction"], "stop")
        self.assertEqual((await self.move("right"))[0], 503)
        self.motor.turn_right.assert_not_called()


class DriveSelectionTests(unittest.TestCase):
    def test_dual_constructor_receives_only_explicit_polarity_values(self):
        with patch("server.drive.DRV8833DriveController") as controller:
            for left, right in (("0", "0"), ("1", "0"), ("0", "1"), ("1", "1")):
                with self.subTest(left=left, right=right), patch.dict(os.environ, {"HOMEBOT_MOTOR": "drv8833-dual", "HOMEBOT_INVERT_LEFT": left, "HOMEBOT_INVERT_RIGHT": right}):
                    self.assertIs(main.build_motor(), controller.return_value)
                    controller.assert_called_with(invert_left=left == "1", invert_right=right == "1")

    def test_invalid_calibration_or_missing_hardware_does_not_fall_back_to_mock(self):
        with patch.dict(os.environ, {"HOMEBOT_MOTOR": "drv8833-dual", "HOMEBOT_INVERT_LEFT": "bad", "HOMEBOT_INVERT_RIGHT": "0"}), patch("server.drive.DRV8833DriveController") as controller:
            with self.assertRaises(ValueError):
                main.build_motor()
            controller.assert_not_called()
        with patch.dict(os.environ, {"HOMEBOT_MOTOR": "drv8833-dual", "HOMEBOT_INVERT_LEFT": "0", "HOMEBOT_INVERT_RIGHT": "0"}), patch("server.drive.DRV8833DriveController", side_effect=RuntimeError("no GPIO")):
            with self.assertRaisesRegex(RuntimeError, "no GPIO"):
                main.build_motor()
