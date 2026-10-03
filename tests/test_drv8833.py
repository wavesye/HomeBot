"""验证 DRV8833 的实际引脚命令与故障清理；GPIO 为替身，不访问硬件。"""

import importlib
import os
import sys
import types
import unittest
from unittest.mock import Mock, patch

from server import drv8833
from test_motor import FakeDevice, FakeFactory


class DRV8833Tests(unittest.TestCase):
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
        sleeper = patch.object(drv8833, "sleep", side_effect=self.check_wake)
        self.sleep = sleeper.start()
        self.addCleanup(sleeper.stop)

    def check_wake(self, seconds):
        # 在等待整个唤醒周期时，两路 PWM 均必须为零，不能恢复旧动作。
        self.assertGreaterEqual(seconds, 0.001)
        self.assertEqual(self.factory.devices[22].value, 1)
        self.assertEqual(self.factory.devices[17].value, 0)
        self.assertEqual(self.factory.devices[27].value, 0)
        self.factory.events.append(("wake", seconds))

    def create(self, *, injected=True):
        motor = drv8833.DRV8833MotorController(pin_factory=self.factory) if injected else drv8833.DRV8833MotorController()

        def cleanup():
            self.factory.fail_writes.clear()
            self.factory.fail_close.clear()
            self.factory.fail_factory_close = False
            if not motor._closed:
                motor.close()

        self.addCleanup(cleanup)
        return motor

    def assert_all_low(self):
        self.assertTrue(all(device.value == 0 for device in self.factory.devices.values()))

    def test_import_does_not_load_gpio_or_open_outputs(self):
        with patch.dict(sys.modules, {"gpiozero": None, "gpiozero.pins.lgpio": None}):
            module = importlib.reload(drv8833)
        self.assertEqual(module.DRV8833MotorController.mode, "drv8833")
        self.assertEqual(self.factory.events, [])

    def test_init_holds_sleep_low_before_claiming_two_pwm_inputs_only(self):
        motor = self.create()
        self.assertEqual(self.factory.events, [
            ("create", 22, False, None, True),
            ("create", 17, 0, 1000, True), ("create", 27, 0, 1000, True),
        ])
        self.assert_all_low()
        self.assertEqual(motor.supported_directions, ("forward", "backward", "stop"))
        self.assertEqual(motor.max_speed, 0.4)
        # 特别防止把 TB6612 的 GPIO18/PWMA 留在新驱动中。
        self.assertEqual(set(self.factory.devices), {17, 27, 22})
        self.sleep.assert_not_called()
        self.local_factory.assert_not_called()

    def test_default_factory_is_local_lgpio_despite_remote_environment(self):
        with patch.dict(os.environ, {"GPIOZERO_PIN_FACTORY": "pigpio", "PIGPIO_ADDR": "remote-host"}):
            self.create(injected=False)
        self.local_factory.assert_called_once_with(chip=0)

    def test_both_directions_apply_requested_pwm_only_after_zero_input_wakeup(self):
        motor = self.create()
        # 覆盖重复同方向、改变占空比和反方向，确保每次先撤销旧输出。
        for direction, speed, active_pin in (
            ("forward", 0.2, 17), ("forward", 0.4, 17),
            ("backward", 0.3, 27), ("backward", 0.1, 27), ("forward", 0.2, 17),
        ):
            with self.subTest(direction=direction, speed=speed):
                self.factory.events.clear()
                getattr(motor, direction)(speed)
                self.assertEqual(self.factory.events, [
                    ("write", 22, 0), ("write", 17, 0), ("write", 27, 0),
                    ("write", 22, 1), ("wake", 0.001), ("write", active_pin, speed),
                ])
                inactive_pin = 27 if active_pin == 17 else 17
                self.assertEqual(self.factory.devices[active_pin].value, speed)
                self.assertEqual(self.factory.devices[inactive_pin].value, 0)
                self.assertEqual(self.factory.devices[22].value, 1)

    def test_zero_speed_stops_without_wakeup_in_either_direction(self):
        motor = self.create()
        for method in (motor.forward, motor.backward):
            with self.subTest(method=method.__name__):
                method(0.2)
                self.sleep.reset_mock()
                self.factory.events.clear()
                method(0)
                self.assertEqual(self.factory.events, [("write", 22, 0), ("write", 17, 0), ("write", 27, 0)])
                self.assert_all_low()
                self.sleep.assert_not_called()

    def test_invalid_speeds_and_turns_never_touch_hardware(self):
        motor = self.create()
        self.factory.events.clear()
        for speed in (-0.01, 0.400001, 1, float("nan"), float("inf"), -float("inf"), True, False, None, "0.2", 10**1000):
            for method in (motor.forward, motor.backward):
                with self.subTest(speed=speed, method=method.__name__):
                    with self.assertRaisesRegex(ValueError, "finite.*0.4"):
                        method(speed)
        for method in (motor.turn_left, motor.turn_right):
            with self.assertRaisesRegex(ValueError, "single-motor"):
                method(0.2)
        self.assertEqual(self.factory.events, [])

    def test_stop_attempts_both_inputs_even_when_sleep_and_active_pwm_fail(self):
        motor = self.create()
        motor.forward(0.3)
        self.factory.events.clear()
        self.factory.fail_writes = {(22, 0): 1, (17, 0): 1}
        with self.assertRaisesRegex(RuntimeError, "stop is unconfirmed.*NSLEEP:.*AIN1:"):
            motor.stop()
        self.assertEqual(self.factory.events, [("write", 22, 0), ("write", 17, 0), ("write", 27, 0)])
        motor.stop()
        self.assert_all_low()

    def test_failure_at_each_drive_write_attempts_complete_stop(self):
        motor = self.create()
        for direction, active_pin in (("forward", 17), ("backward", 27)):
            for pin, value in ((22, 0), (17, 0), (27, 0), (22, 1), (active_pin, 0.3)):
                with self.subTest(direction=direction, pin=pin, value=value):
                    self.factory.events.clear()
                    self.factory.fail_writes = {(pin, value): 1}
                    with self.assertRaisesRegex(RuntimeError, "movement failed"):
                        getattr(motor, direction)(0.3)
                    self.assertEqual(self.factory.events[-3:], [("write", 22, 0), ("write", 17, 0), ("write", 27, 0)])
                    self.assert_all_low()

    def test_wakeup_failure_does_not_apply_pwm_and_stops(self):
        motor = self.create()
        self.sleep.side_effect = RuntimeError("wake wait failed")
        self.factory.events.clear()
        with self.assertRaisesRegex(RuntimeError, "movement failed.*wake wait failed"):
            motor.forward(0.2)
        self.assertNotIn(("write", 17, 0.2), self.factory.events)
        self.assert_all_low()

    def test_drive_error_keeps_emergency_stop_failure_visible(self):
        motor = self.create()

        def fail_after_waking(seconds):
            self.factory.fail_writes = {(22, 0): 1}
            raise RuntimeError("wake error")

        self.sleep.side_effect = fail_after_waking
        with self.assertRaisesRegex(RuntimeError, "movement failed.*Stop also failed.*NSLEEP"):
            motor.forward(0.2)
        self.assertEqual(self.factory.devices[17].value, 0)
        self.assertEqual(self.factory.devices[27].value, 0)
        motor.stop()
        self.assert_all_low()

    def test_init_failure_releases_all_previously_created_resources(self):
        for failure_pin, previous_pins in ((22, []), (17, [22]), (27, [22, 17])):
            with self.subTest(failure_pin=failure_pin):
                self.factory.events.clear()
                self.factory.devices.clear()
                self.factory.fail_create = failure_pin
                with self.assertRaisesRegex(RuntimeError, "initialization failed.*init fault"):
                    drv8833.DRV8833MotorController(pin_factory=self.factory)
                stop_order = [pin for pin in (22, 17, 27) if pin in previous_pins]
                close_order = [pin for pin in (17, 27, 22) if pin in previous_pins]
                operations = [event for event in self.factory.events if event[0] != "create"]
                self.assertEqual(operations, [
                    *(("write", pin, 0) for pin in stop_order),
                    *(("close", pin) for pin in close_order), ("close_factory",),
                ])
                self.assert_all_low()

    def test_init_failure_reports_cleanup_failures_too(self):
        self.factory.fail_create = 27
        self.factory.fail_close = {17}
        self.factory.fail_factory_close = True
        with self.assertRaisesRegex(RuntimeError, "initialization failed.*Cleanup also failed.*close AIN1.*close GPIO factory"):
            drv8833.DRV8833MotorController(pin_factory=self.factory)
        self.assertIn(("close", 22), self.factory.events)
        self.assertEqual(self.factory.events[-1], ("close_factory",))

    def test_missing_dependency_and_factory_errors_abort_without_mock_fallback(self):
        with patch.dict(sys.modules, {"gpiozero": None}):
            with self.assertRaisesRegex(RuntimeError, "initialization failed.*gpiozero/lgpio"):
                drv8833.DRV8833MotorController()
        self.assertEqual(self.factory.events, [])
        self.local_factory.assert_not_called()
        self.local_factory.side_effect = RuntimeError("GPIO permission denied")
        with self.assertRaisesRegex(RuntimeError, "initialization failed.*GPIO permission denied"):
            drv8833.DRV8833MotorController()
        self.assertEqual(self.factory.events, [])

    def test_close_stops_then_releases_sleep_last_and_cannot_restart(self):
        motor = self.create()
        motor.forward(0.2)
        self.factory.events.clear()
        motor.close()
        self.assertEqual(self.factory.events, [
            ("write", 22, 0), ("write", 17, 0), ("write", 27, 0),
            ("close", 17), ("close", 27), ("close", 22), ("close_factory",),
        ])
        self.factory.events.clear()
        motor.close()
        motor.stop()
        self.assertEqual(self.factory.events, [])
        with self.assertRaisesRegex(RuntimeError, "closed"):
            motor.forward(0.2)
        with self.assertRaisesRegex(RuntimeError, "closed"):
            motor.backward(0.2)

    def test_close_aggregates_errors_and_does_not_later_claim_success(self):
        motor = self.create()
        self.factory.events.clear()
        self.factory.fail_writes = {(22, 0): 1}
        self.factory.fail_close = {17, 27}
        self.factory.fail_factory_close = True
        with self.assertRaisesRegex(RuntimeError, "cleanup failed.*NSLEEP.*close AIN1.*close AIN2.*close GPIO factory") as error:
            motor.close()
        self.assertEqual(self.factory.events[-4:], [
            ("close", 17), ("close", 27), ("close", 22), ("close_factory",),
        ])
        self.factory.events.clear()
        for method in (motor.close, motor.stop):
            with self.assertRaises(RuntimeError) as repeated:
                method()
            self.assertEqual(str(repeated.exception), str(error.exception))
        self.assertEqual(self.factory.events, [])


if __name__ == "__main__":
    unittest.main()
