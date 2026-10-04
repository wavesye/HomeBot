"""双轮 GPIO 和常闭实体停止反馈测试；只使用替身，不访问真实硬件。"""

import importlib
import os
import sys
import types
import unittest
from unittest.mock import Mock, patch

from server import drive
from server.motor import MockMotorController
from test_motor import FakeDevice, FakeFactory


class DriveFactory(FakeFactory):
    def __init__(self):
        super().__init__()
        self.circuit_closed = True
        self.fail_read = False
        self.fail_callback = False
        self.on_write = None
        self.on_register = None
        self.feedback = None


class Output(FakeDevice):
    @FakeDevice.value.setter
    def value(self, value):
        FakeDevice.value.fset(self, value)
        if self.factory.on_write:
            self.factory.on_write(self.pin, value)


class Feedback:
    def __init__(self, pin, *, pull_up, bounce_time, pin_factory):
        self.pin = pin
        self.factory = pin_factory
        self.factory.events.append(("input", pin, pull_up, bounce_time))
        if self.factory.fail_create == pin:
            raise RuntimeError("feedback init fault")
        self.factory.feedback = self
        self._handler = None

    @property
    def is_pressed(self):
        if self.factory.fail_read:
            raise RuntimeError("feedback read fault")
        return self.factory.circuit_closed

    @property
    def when_released(self):
        return self._handler

    @when_released.setter
    def when_released(self, handler):
        self.factory.events.append(("callback", self.pin, handler is not None))
        if self.factory.fail_callback:
            raise RuntimeError("feedback callback fault")
        self._handler = handler
        if handler and self.factory.on_register:
            self.factory.on_register(self)

    def open_circuit(self):
        self.factory.circuit_closed = False
        if self._handler:
            self._handler()

    def close_circuit(self):
        self.factory.circuit_closed = True

    def close(self):
        self.factory.events.append(("close", self.pin))
        if self.pin in self.factory.fail_close:
            raise RuntimeError("feedback close fault")


class DriveTests(unittest.TestCase):
    STOP_WRITES = [("write", pin, 0) for pin in (22, 17, 27, 5, 6)]

    def setUp(self):
        self.factory = DriveFactory()
        gpiozero = types.ModuleType("gpiozero")
        gpiozero.__path__ = []
        gpiozero.DigitalOutputDevice = Output
        gpiozero.PWMOutputDevice = Output
        gpiozero.Button = Feedback
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
            self.factory.fail_factory_close = self.factory.fail_callback = False
            self.factory.on_write = None
            if not motor._closed:
                motor.close()

        self.addCleanup(cleanup)
        return motor

    def assert_all_low(self):
        self.assertTrue(all(output.value == 0 for output in self.factory.devices.values()))

    def test_mock_safety_check_needs_no_hardware(self):
        self.assertIsNone(MockMotorController().check_safety())

    def test_import_is_lazy_and_does_not_load_gpiozero(self):
        with patch.dict(sys.modules, {"gpiozero": None, "gpiozero.pins.lgpio": None}):
            self.assertEqual(importlib.reload(drive).DRV8833DriveController.mode, "drv8833-dual")
        self.assertEqual(self.factory.events, [])

    def test_init_pins_pwm_and_nc_pullup_are_fixed_and_outputs_stay_off(self):
        motor = self.create()
        self.assertEqual(self.factory.events, [
            ("create", 22, False, None, True),
            *(("create", pin, 0, 1000, True) for pin in (17, 27, 5, 6)),
            ("input", 23, True, None), ("callback", 23, True),
        ])
        self.assert_all_low()
        motor.check_safety()
        self.assertEqual(motor.supported_directions, ("forward", "backward", "left", "right", "stop"))
        self.assertEqual(motor.max_speed, 0.3)
        self.assertFalse(motor.invert_left)
        self.assertFalse(motor.invert_right)
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

    def test_invalid_inversion_settings_fail_before_gpio_is_opened(self):
        for kwargs in ({"invert_left": "false"}, {"invert_right": 1}, {"invert_left": None}):
            with self.assertRaisesRegex(ValueError, "bool"):
                drive.DRV8833DriveController(pin_factory=self.factory, **kwargs)
        self.assertEqual(self.factory.events, [])

    def test_invalid_speeds_never_write_outputs(self):
        motor = self.create()
        self.factory.events.clear()
        for speed in (-0.1, 0.300001, 0.4, 1, float("nan"), float("inf"), -float("inf"), None, True, False, "0.2", 10**1000):
            for method in (motor.forward, motor.backward, motor.turn_left, motor.turn_right):
                with self.subTest(speed=speed, method=method.__name__), self.assertRaisesRegex(ValueError, "finite.*0.3"):
                    method(speed)
        self.assertEqual(self.factory.events, [])

    def test_zero_speed_stops_even_when_physical_stop_has_latched(self):
        motor = self.create()
        self.factory.feedback.open_circuit()
        for method in (motor.forward, motor.backward, motor.turn_left, motor.turn_right):
            self.factory.events.clear()
            method(0)
            self.assertEqual(self.factory.events, self.STOP_WRITES)
        self.sleep.assert_not_called()
        with self.assertRaisesRegex(RuntimeError, "Motion is locked"):
            motor.check_safety()

    def test_initial_open_circuit_constructs_but_locks_safety_and_motion(self):
        self.factory.circuit_closed = False
        motor = self.create()
        self.assert_all_low()
        self.factory.feedback.close_circuit()
        with self.assertRaisesRegex(RuntimeError, "Physical STOP"):
            motor.check_safety()
        self.factory.events.clear()
        with self.assertRaisesRegex(RuntimeError, "movement failed.*Physical STOP"):
            motor.forward(0.2)
        self.assertEqual(self.factory.events, self.STOP_WRITES)
        self.assertFalse(motor._closed)

    def test_wire_disconnection_is_detected_even_without_a_callback(self):
        motor = self.create()
        self.factory.circuit_closed = False  # 模拟持续断线，不能只依赖事件回调。
        with self.assertRaisesRegex(RuntimeError, "wire disconnected"):
            motor.check_safety()
        self.factory.circuit_closed = True
        with self.assertRaisesRegex(RuntimeError, "Motion is locked"):
            motor.check_safety()

    def test_brief_open_close_callback_latches_without_any_gpio_output_write(self):
        motor = self.create()
        motor.forward(0.2)
        self.factory.events.clear()
        self.factory.feedback.open_circuit()
        self.factory.feedback.close_circuit()
        self.assertEqual(self.factory.events, [])
        with self.assertRaisesRegex(RuntimeError, "Motion is locked"):
            motor.check_safety()
        motor.stop()
        self.assert_all_low()
        with self.assertRaisesRegex(RuntimeError, "Motion is locked"):
            motor.check_safety()

    def test_callback_is_installed_before_the_initial_read(self):
        def brief_open(feedback):
            feedback.open_circuit()
            feedback.close_circuit()
        self.factory.on_register = brief_open
        motor = self.create()
        with self.assertRaisesRegex(RuntimeError, "Motion is locked"):
            motor.check_safety()

    def test_read_failure_latches_and_does_not_clear_when_read_recovers(self):
        motor = self.create()
        self.factory.fail_read = True
        with self.assertRaisesRegex(RuntimeError, "could not be read"):
            motor.check_safety()
        self.factory.fail_read = False
        with self.assertRaisesRegex(RuntimeError, "Motion is locked"):
            motor.check_safety()
        motor.stop()
        self.assert_all_low()

    def test_open_during_wakeup_stops_before_any_wheel_gets_pwm(self):
        motor = self.create()
        def open_during_wake(seconds):
            self.check_wake(seconds)
            self.factory.feedback.open_circuit()
        self.sleep.side_effect = open_during_wake
        self.factory.events.clear()
        with self.assertRaisesRegex(RuntimeError, "movement failed.*Physical STOP"):
            motor.forward(0.2)
        self.assertFalse(any(event[0] == "write" and event[-1] == 0.2 for event in self.factory.events))
        self.assert_all_low()
        self.assertFalse(motor._closed)

    def test_open_during_each_wheel_write_is_caught_and_stops_both_wheels(self):
        for trigger_pin in (17, 5):
            with self.subTest(trigger_pin=trigger_pin):
                motor = self.create()
                def briefly_open(pin, value):
                    if pin == trigger_pin and value == 0.2:
                        self.factory.feedback.open_circuit()
                        self.factory.feedback.close_circuit()
                self.factory.on_write = briefly_open
                self.factory.events.clear()
                with self.assertRaisesRegex(RuntimeError, "movement failed.*Motion is locked"):
                    motor.forward(0.2)
                self.assert_all_low()
                self.assertEqual(self.factory.events[-5:], self.STOP_WRITES)
                if trigger_pin == 17:
                    self.assertNotIn(("write", 5, 0.2), self.factory.events)
                self.factory.on_write = None
                motor.close()

    def test_stop_failure_attempts_all_outputs_and_can_be_retried(self):
        motor = self.create()
        motor.forward(0.2)
        self.factory.fail_writes = {(22, 0): 1, (17, 0): 1, (5, 0): 1}
        self.factory.events.clear()
        with self.assertRaisesRegex(RuntimeError, "unconfirmed.*NSLEEP.*AIN1.*BIN1"):
            motor.stop()
        self.assertEqual(self.factory.events, self.STOP_WRITES)
        motor.stop()
        self.assert_all_low()

    def test_each_movement_write_failure_stops_and_keeps_resources_for_retry(self):
        motor = self.create()
        for pin, value in ((22, 0), (17, 0), (27, 0), (5, 0), (6, 0), (22, 1), (17, 0.2), (5, 0.2)):
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
        motor = self.create()
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
        for fail_pin in (22, 17, 27, 5, 6, 23):
            with self.subTest(fail_pin=fail_pin):
                self.factory.events.clear()
                self.factory.devices.clear()
                self.factory.fail_create = fail_pin
                with self.assertRaisesRegex(RuntimeError, "initialization failed"):
                    drive.DRV8833DriveController(pin_factory=self.factory)
                created = set(self.factory.devices)
                stopped = {event[1] for event in self.factory.events if event[0] == "write"}
                closed = {event[1] for event in self.factory.events if event[0] == "close"}
                self.assertEqual(stopped, created)
                self.assertEqual(closed, created)
                self.assertEqual(self.factory.events[-1], ("close_factory",))

    def test_initial_read_failure_closes_input_outputs_and_factory(self):
        self.factory.fail_read = True
        with self.assertRaisesRegex(RuntimeError, "initialization failed.*could not be read"):
            drive.DRV8833DriveController(pin_factory=self.factory)
        self.assertIn(("close", 23), self.factory.events)
        self.assertEqual(self.factory.events[-2:], [("close", 22), ("close_factory",)])
        self.assert_all_low()

    def test_missing_dependency_or_factory_failure_never_falls_back(self):
        with patch.dict(sys.modules, {"gpiozero": None}):
            with self.assertRaisesRegex(RuntimeError, "initialization failed.*gpiozero/lgpio"):
                drive.DRV8833DriveController()
        self.local_factory.side_effect = RuntimeError("permission denied")
        with self.assertRaisesRegex(RuntimeError, "initialization failed.*permission denied"):
            drive.DRV8833DriveController()
        self.assertEqual(self.factory.events, [])

    def test_close_stops_detaches_feedback_and_releases_sleep_last(self):
        motor = self.create()
        motor.forward(0.2)
        self.factory.events.clear()
        motor.close()
        self.assertEqual(self.factory.events, [
            *self.STOP_WRITES, *(("close", pin) for pin in (17, 27, 5, 6)),
            ("callback", 23, False), ("close", 23), ("close", 22), ("close_factory",),
        ])
        self.factory.events.clear()
        motor.close()
        motor.stop()
        self.assertEqual(self.factory.events, [])
        for method in (motor.check_safety, lambda: motor.forward(0.2)):
            with self.assertRaisesRegex(RuntimeError, "closed"):
                method()

    def test_close_attempts_all_resources_and_keeps_cleanup_failure_visible(self):
        motor = self.create()
        self.factory.fail_writes = {(22, 0): 1}
        self.factory.fail_close = {17, 23}
        self.factory.fail_callback = self.factory.fail_factory_close = True
        self.factory.events.clear()
        with self.assertRaisesRegex(RuntimeError, "cleanup failed.*NSLEEP.*close AIN1.*detach STOP.*close STOP.*GPIO factory") as error:
            motor.close()
        self.assertEqual(self.factory.events[-2:], [("close", 22), ("close_factory",)])
        self.factory.events.clear()
        with self.assertRaises(RuntimeError) as repeated:
            motor.close()
        self.assertEqual(str(error.exception), str(repeated.exception))
        self.assertEqual(self.factory.events, [])


if __name__ == "__main__":
    unittest.main()
