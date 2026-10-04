"""双轮 GPIO 测试；只使用替身，不访问真实硬件。"""

import importlib
import os
import sys
import types
import unittest
from unittest.mock import Mock, patch

from server import drive
from test_motor import FakeDevice, FakeFactory


class DriveTests(unittest.TestCase):
    STOP_WRITES = [("write", pin, 0) for pin in (22, 17, 27, 5, 6)]

    def setUp(self):
        self.factory = FakeFactory()
        gpiozero = types.ModuleType("gpiozero")
        gpiozero.__path__ = []
        gpiozero.DigitalOutputDevice = FakeDevice
        gpiozero.PWMOutputDevice = FakeDevice
        pins = types.ModuleType("gpiozero.pins")
        pins.__path__ = []
        lgpio = types.ModuleType("gpiozero.pins.lgpio")
        self.local_factory = Mock(return_value=self.factory)
        lgpio.LGPIOFactory = self.local_factory
        modules = patch.dict(sys.modules, {
            "gpiozero": gpiozero, "gpiozero.pins": pins, "gpiozero.pins.lgpio": lgpio,
        })
        modules.start()
        self.addCleanup(modules.stop)
        sleeper = patch.object(drive, "sleep", side_effect=self.check_wake)
        self.sleep = sleeper.start()
        self.addCleanup(sleeper.stop)

    def check_wake(self, seconds):
        self.assertGreaterEqual(seconds, 0.001)
        self.assertEqual(self.factory.devices[22].value, 1)
        for pin in (17, 27, 5, 6):
            self.assertEqual(self.factory.devices[pin].value, 0)
        self.factory.events.append(("wake", seconds))

    def create(self, *, injected=True, **kwargs):
        motor = drive.DRV8833DriveController(pin_factory=self.factory, **kwargs) if injected else drive.DRV8833DriveController(**kwargs)

        def cleanup():
            self.factory.fail_writes.clear()
            self.factory.fail_close.clear()
            self.factory.fail_factory_close = False
            if not motor._closed:
                motor.close()

        self.addCleanup(cleanup)
        return motor

    def assert_all_low(self):
        self.assertTrue(all(output.value == 0 for output in self.factory.devices.values()))

    def test_import_is_lazy_and_does_not_load_gpiozero(self):
        with patch.dict(sys.modules, {"gpiozero": None, "gpiozero.pins.lgpio": None}):
            self.assertEqual(importlib.reload(drive).DRV8833DriveController.mode, "drv8833-dual")
        self.assertEqual(self.factory.events, [])

    def test_init_only_opens_motor_outputs_and_keeps_them_off(self):
        motor = self.create()
        self.assertEqual(self.factory.events, [
            ("create", 22, False, None, True),
            *(("create", pin, 0, 1000, True) for pin in (17, 27, 5, 6)),
        ])
        self.assert_all_low()
        self.assertEqual(motor.supported_directions, ("forward", "backward", "left", "right", "stop"))
        self.assertEqual(motor.max_speed, 0.3)
        self.assertFalse(motor.invert_left)
        self.assertFalse(motor.invert_right)
        self.assertEqual(motor.left_scale, 1.0)
        self.assertEqual(motor.right_scale, 1.0)
        self.sleep.assert_not_called()
        self.local_factory.assert_not_called()

    def test_default_factory_is_explicit_local_lgpio(self):
        with patch.dict(os.environ, {"GPIOZERO_PIN_FACTORY": "pigpio", "PIGPIO_ADDR": "remote"}):
            self.create(injected=False)
        self.local_factory.assert_called_once_with(chip=0)

    def test_four_directions_and_all_inversion_combinations_have_correct_pwm(self):
        for inverted_left, inverted_right in ((False, False), (True, False), (False, True), (True, True)):
            motor = self.create(invert_left=inverted_left, invert_right=inverted_right)
            for method, left_positive, right_positive in (
                ("forward", True, True), ("backward", False, False),
                ("turn_left", False, True), ("turn_right", True, False),
            ):
                with self.subTest(left=inverted_left, right=inverted_right, method=method):
                    self.factory.events.clear()
                    getattr(motor, method)(0.3)
                    left_pin = 17 if left_positive != inverted_left else 27
                    right_pin = 5 if right_positive != inverted_right else 6
                    self.assertEqual(self.factory.events, [
                        *self.STOP_WRITES, ("write", 22, 1), ("wake", 0.001),
                        ("write", left_pin, 0.3), ("write", right_pin, 0.3),
                    ])
                    for pin in (17, 27, 5, 6):
                        self.assertEqual(self.factory.devices[pin].value, 0.3 if pin in (left_pin, right_pin) else 0)
            motor.close()

    def test_scaled_pwm_stays_with_its_wheel_in_all_directions_and_polarities(self):
        methods = ("forward", "backward", "turn_left", "turn_right")
        active_pins = {
            (False, False): ((17, 5), (27, 6), (27, 5), (17, 6)),
            (True, False): ((27, 5), (17, 6), (17, 5), (27, 6)),
            (False, True): ((17, 6), (27, 5), (27, 6), (17, 5)),
            (True, True): ((27, 6), (17, 5), (17, 6), (27, 5)),
        }
        for (inverted_left, inverted_right), pins in active_pins.items():
            motor = self.create(
                invert_left=inverted_left, invert_right=inverted_right,
                left_scale=0.9, right_scale=0.8,
            )
            for method, (left_pin, right_pin) in zip(methods, pins):
                with self.subTest(left=inverted_left, right=inverted_right, method=method):
                    self.factory.events.clear()
                    getattr(motor, method)(0.3)
                    self.assertEqual(self.factory.events, [
                        *self.STOP_WRITES, ("write", 22, 1), ("wake", 0.001),
                        ("write", left_pin, 0.27), ("write", right_pin, 0.24),
                    ])
                    for pin in (17, 27, 5, 6):
                        expected = 0.27 if pin == left_pin else 0.24 if pin == right_pin else 0
                        self.assertAlmostEqual(self.factory.devices[pin].value, expected)
                        self.assertLessEqual(self.factory.devices[pin].value, motor.max_speed)
            motor.close()

    def test_pwm_scale_validator_returns_float_without_opening_gpio(self):
        for value in (1, 1.0, 0.9, 0.01):
            with self.subTest(value=value):
                result = drive.validate_pwm_scale(value)
                self.assertIsInstance(result, float)
                self.assertEqual(result, value)
        self.assertEqual(self.factory.events, [])
        self.local_factory.assert_not_called()

    def test_invalid_scales_fail_before_any_gpio_is_opened(self):
        invalid = (
            0, -0.0, -0.1, 1.000001, float("nan"), float("inf"), -float("inf"),
            None, True, False, "0.9", complex(0.9, 0), 10**1000,
        )
        for value in invalid:
            for side in ("left", "right"):
                with self.subTest(side=side, value=value), self.assertRaisesRegex(ValueError, "PWM scale.*finite.*1"):
                    drive.DRV8833DriveController(**{f"{side}_scale": value})
        self.assertEqual(self.factory.events, [])
        self.local_factory.assert_not_called()

    def test_invalid_inversion_settings_fail_before_gpio_is_opened(self):
        for kwargs in ({"invert_left": "false"}, {"invert_right": 1}, {"invert_left": None}):
            with self.assertRaisesRegex(ValueError, "bool"):
                drive.DRV8833DriveController(pin_factory=self.factory, **kwargs)
        self.assertEqual(self.factory.events, [])

    def test_invalid_speeds_never_write_outputs(self):
        motor = self.create(left_scale=0.9, right_scale=0.8)
        self.factory.events.clear()
        for speed in (-0.1, 0.300001, 0.4, 1, float("nan"), float("inf"), -float("inf"), None, True, False, "0.2", 10**1000):
            for method in (motor.forward, motor.backward, motor.turn_left, motor.turn_right):
                with self.subTest(speed=speed, method=method.__name__), self.assertRaisesRegex(ValueError, "finite.*0.3"):
                    method(speed)
        self.assertEqual(self.factory.events, [])

    def test_zero_speed_stops_all_outputs(self):
        motor = self.create(left_scale=0.9, right_scale=0.8)
        for method in (motor.forward, motor.backward, motor.turn_left, motor.turn_right):
            self.factory.events.clear()
            method(0)
            self.assertEqual(self.factory.events, self.STOP_WRITES)
        self.sleep.assert_not_called()

    def test_zero_speed_stops_an_active_scaled_and_inverted_drive(self):
        motor = self.create(invert_left=True, invert_right=True, left_scale=0.9, right_scale=0.8)
        for method in (motor.forward, motor.backward, motor.turn_left, motor.turn_right):
            motor.forward(0.3)
            self.assertEqual(self.factory.devices[27].value, 0.27)
            self.assertEqual(self.factory.devices[6].value, 0.24)
            self.factory.events.clear()
            self.sleep.reset_mock()
            method(0)
            self.assertEqual(self.factory.events, self.STOP_WRITES)
            self.assert_all_low()
            self.sleep.assert_not_called()

    def test_stop_failure_attempts_all_outputs_and_can_be_retried(self):
        motor = self.create(left_scale=0.9, right_scale=0.8)
        motor.forward(0.2)
        self.factory.fail_writes = {(22, 0): 1, (17, 0): 1, (5, 0): 1}
        self.factory.events.clear()
        with self.assertRaisesRegex(RuntimeError, "unconfirmed.*NSLEEP.*AIN1.*BIN1"):
            motor.stop()
        self.assertEqual(self.factory.events, self.STOP_WRITES)
        motor.stop()
        self.assert_all_low()

    def test_each_movement_write_failure_stops_and_keeps_resources_for_retry(self):
        motor = self.create(left_scale=0.9, right_scale=0.8)
        for pin, value in ((22, 0), (17, 0), (27, 0), (5, 0), (6, 0), (22, 1), (17, 0.2 * 0.9), (5, 0.2 * 0.8)):
            with self.subTest(pin=pin, value=value):
                self.factory.events.clear()
                self.factory.fail_writes = {(pin, value): 1}
                with self.assertRaisesRegex(RuntimeError, "movement failed"):
                    motor.forward(0.2)
                self.assertEqual(self.factory.events[-5:], self.STOP_WRITES)
                self.assertFalse(any(event[0].startswith("close") for event in self.factory.events))
                self.assert_all_low()
                self.assertFalse(motor._closed)

    def test_movement_and_stop_failure_are_both_reported_without_releasing_pins(self):
        motor = self.create(left_scale=0.9, right_scale=0.8)
        def fail_after_wake(seconds):
            self.factory.fail_writes = {(22, 0): 1}
            raise RuntimeError("wake error")
        self.sleep.side_effect = fail_after_wake
        with self.assertRaisesRegex(RuntimeError, "movement failed.*wake error.*Stop also failed.*NSLEEP"):
            motor.forward(0.2)
        self.assertFalse(motor._closed)
        motor.stop()
        self.assert_all_low()

    def test_init_failure_releases_every_successfully_created_resource(self):
        for fail_pin in (22, 17, 27, 5, 6):
            with self.subTest(fail_pin=fail_pin):
                self.factory.events.clear()
                self.factory.devices.clear()
                self.factory.fail_create = fail_pin
                with self.assertRaisesRegex(RuntimeError, "initialization failed"):
                    drive.DRV8833DriveController(pin_factory=self.factory, left_scale=0.9, right_scale=0.8)
                created = set(self.factory.devices)
                stopped = {event[1] for event in self.factory.events if event[0] == "write"}
                closed = {event[1] for event in self.factory.events if event[0] == "close"}
                self.assertEqual(stopped, created)
                self.assertEqual(closed, created)
                self.assertEqual(self.factory.events[-1], ("close_factory",))

    def test_missing_dependency_or_factory_failure_never_falls_back(self):
        with patch.dict(sys.modules, {"gpiozero": None}):
            with self.assertRaisesRegex(RuntimeError, "initialization failed.*gpiozero/lgpio"):
                drive.DRV8833DriveController()
        self.local_factory.side_effect = RuntimeError("permission denied")
        with self.assertRaisesRegex(RuntimeError, "initialization failed.*permission denied"):
            drive.DRV8833DriveController()
        self.assertEqual(self.factory.events, [])

    def test_close_stops_and_releases_sleep_last(self):
        motor = self.create(left_scale=0.9, right_scale=0.8)
        motor.forward(0.2)
        self.factory.events.clear()
        motor.close()
        self.assertEqual(self.factory.events, [
            *self.STOP_WRITES, *(("close", pin) for pin in (17, 27, 5, 6)),
            ("close", 22), ("close_factory",),
        ])
        self.factory.events.clear()
        motor.close()
        motor.stop()
        self.assertEqual(self.factory.events, [])
        with self.assertRaisesRegex(RuntimeError, "closed"):
            motor.forward(0.2)

    def test_close_attempts_all_resources_and_keeps_cleanup_failure_visible(self):
        motor = self.create(left_scale=0.9, right_scale=0.8)
        self.factory.fail_writes = {(22, 0): 1}
        self.factory.fail_close = {17, 5}
        self.factory.fail_factory_close = True
        self.factory.events.clear()
        with self.assertRaisesRegex(RuntimeError, "cleanup failed.*NSLEEP.*close AIN1.*close BIN1.*GPIO factory") as error:
            motor.close()
        self.assertEqual(self.factory.events[-2:], [("close", 22), ("close_factory",)])
        self.factory.events.clear()
        with self.assertRaises(RuntimeError) as repeated:
            motor.close()
        self.assertEqual(str(error.exception), str(repeated.exception))
        self.assertEqual(self.factory.events, [])


if __name__ == "__main__":
    unittest.main()
