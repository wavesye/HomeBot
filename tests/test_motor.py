"""用 GPIO API 替身验证引脚顺序与故障清理；不安装或访问 Pi 硬件。"""

import importlib
import io
import os
import sys
import types
import unittest
from contextlib import redirect_stdout
from unittest.mock import Mock, patch

from server.motor import MotorController, MockMotorController
from server import tb6612


class FakeFactory:
    def __init__(self):
        self.events = []
        self.devices = {}
        self.fail_create = None
        self.fail_writes = {}
        self.fail_close = set()
        self.fail_factory_close = False

    def close(self):
        self.events.append(("close_factory",))
        if self.fail_factory_close:
            raise RuntimeError("factory close fault")


class FakeDevice:
    def __init__(self, pin, *, active_high, initial_value, pin_factory, frequency=None):
        self.pin = pin
        self.factory = pin_factory
        self.frequency = frequency
        self.factory.events.append(("create", pin, initial_value, frequency, active_high))
        if self.factory.fail_create == pin:
            raise RuntimeError(f"pin {pin} init fault")
        self._value = initial_value
        self.factory.devices[pin] = self

    @property
    def value(self):
        return self._value

    @value.setter
    def value(self, value):
        self.factory.events.append(("write", self.pin, value))
        key = (self.pin, value)
        if self.factory.fail_writes.get(key, 0):
            self.factory.fail_writes[key] -= 1
            raise RuntimeError(f"pin {self.pin} write fault")
        self._value = value

    def close(self):
        self.factory.events.append(("close", self.pin))
        if self.pin in self.factory.fail_close:
            raise RuntimeError(f"pin {self.pin} close fault")


class MotorInterfaceTests(unittest.TestCase):
    def test_mock_metadata_and_default_close(self):
        self.assertEqual(MotorController.mode, "mock")
        motor = MockMotorController()
        self.assertEqual(motor.mode, "mock")
        self.assertEqual(motor.supported_directions, ("forward", "backward", "left", "right", "stop"))
        self.assertEqual(motor.max_speed, 1.0)
        with redirect_stdout(io.StringIO()) as output:
            motor.close()
        self.assertIn("Stopped", output.getvalue())

    def test_importing_driver_does_not_import_gpiozero(self):
        with patch.dict(sys.modules, {"gpiozero": None, "gpiozero.pins.lgpio": None}):
            module = importlib.reload(tb6612)
        self.assertEqual(module.TB6612MotorController.mode, "tb6612")


class TB6612Tests(unittest.TestCase):
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

    def create(self, *, injected=True):
        motor = tb6612.TB6612MotorController(pin_factory=self.factory) if injected else tb6612.TB6612MotorController()

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

    def test_init_claims_standby_first_and_all_outputs_start_low(self):
        motor = self.create()
        self.assertEqual(self.factory.events, [
            ("create", 22, False, None, True), ("create", 17, False, None, True),
            ("create", 27, False, None, True), ("create", 18, 0, 1000, True),
        ])
        self.assert_all_low()
        self.assertEqual(motor.mode, "tb6612")
        self.assertEqual(motor.supported_directions, ("forward", "backward", "stop"))
        self.assertEqual(motor.max_speed, 0.4)
        self.local_factory.assert_not_called()

    def test_default_factory_is_local_lgpio_despite_remote_environment(self):
        with patch.dict(os.environ, {"GPIOZERO_PIN_FACTORY": "pigpio", "PIGPIO_ADDR": "remote-host"}):
            self.create(injected=False)
        self.local_factory.assert_called_once_with(chip=0)
        self.assertEqual(len(self.factory.devices), 4)

    def test_forward_uses_standby_and_zero_pwm_before_direction_and_enable(self):
        motor = self.create()
        self.factory.events.clear()
        motor.forward(0.4)
        self.assertEqual(self.factory.events, [
            ("write", 22, 0), ("write", 18, 0), ("write", 17, 1),
            ("write", 27, 0), ("write", 18, 0.4), ("write", 22, 1),
        ])
        self.assertEqual(self.factory.devices[18].value, 0.4)

    def test_backward_uses_opposite_inputs_and_enables_last(self):
        motor = self.create()
        self.factory.events.clear()
        motor.backward(0.2)
        self.assertEqual(self.factory.events, [
            ("write", 22, 0), ("write", 18, 0), ("write", 17, 0),
            ("write", 27, 1), ("write", 18, 0.2), ("write", 22, 1),
        ])

    def test_zero_speed_only_stops(self):
        motor = self.create()
        for method in (motor.forward, motor.backward):
            with self.subTest(method=method.__name__):
                self.factory.events.clear()
                method(0)
                self.assertEqual(self.factory.events, [
                    ("write", 22, 0), ("write", 18, 0), ("write", 17, 0), ("write", 27, 0),
                ])
                self.assert_all_low()

    def test_invalid_speeds_do_not_write_pins(self):
        motor = self.create()
        self.factory.events.clear()
        for speed in (-0.01, 0.400001, 1, float("nan"), float("inf"), -float("inf"), True, False, None, "0.2", 10**1000):
            for method in (motor.forward, motor.backward):
                with self.subTest(speed=speed, method=method.__name__):
                    with self.assertRaisesRegex(ValueError, "finite.*0.4"):
                        method(speed)
        self.assertEqual(self.factory.events, [])

    def test_unsupported_turns_never_write_pins(self):
        motor = self.create()
        self.factory.events.clear()
        for method in (motor.turn_left, motor.turn_right):
            with self.assertRaisesRegex(ValueError, "single-motor"):
                method(0.2)
        self.assertEqual(self.factory.events, [])

    def test_stop_attempts_every_pin_even_when_multiple_writes_fail(self):
        motor = self.create()
        motor.forward(0.3)
        self.factory.events.clear()
        self.factory.fail_writes = {(22, 0): 1, (18, 0): 1}
        with self.assertRaisesRegex(RuntimeError, "stop is unconfirmed.*STBY:.*PWMA:"):
            motor.stop()
        self.assertEqual(self.factory.events, [
            ("write", 22, 0), ("write", 18, 0), ("write", 17, 0), ("write", 27, 0),
        ])
        # 失败必须上报，随后可明确重试停机。
        motor.stop()
        self.assert_all_low()

    def test_drive_failure_at_each_step_attempts_complete_stop(self):
        motor = self.create()
        for pin, value in ((22, 0), (18, 0), (17, 1), (27, 0), (18, 0.3), (22, 1)):
            with self.subTest(pin=pin, value=value):
                self.factory.events.clear()
                self.factory.fail_writes = {(pin, value): 1}
                with self.assertRaisesRegex(RuntimeError, "movement failed"):
                    motor.forward(0.3)
                self.assertEqual(self.factory.events[-4:], [
                    ("write", 22, 0), ("write", 18, 0), ("write", 17, 0), ("write", 27, 0),
                ])
                self.assert_all_low()

    def test_drive_error_also_reports_failed_emergency_stop(self):
        motor = self.create()
        self.factory.fail_writes = {(17, 1): 1, (27, 0): 1}
        with self.assertRaisesRegex(RuntimeError, "movement failed.*Stop also failed.*AIN2"):
            motor.forward(0.3)
        self.assertEqual(self.factory.events[-4:], [
            ("write", 22, 0), ("write", 18, 0), ("write", 17, 0), ("write", 27, 0),
        ])

    def test_init_failure_stops_and_closes_every_existing_output_and_factory(self):
        for failure_pin, previous_pins in ((22, []), (17, [22]), (27, [22, 17]), (18, [22, 17, 27])):
            with self.subTest(failure_pin=failure_pin):
                self.factory.events.clear()
                self.factory.devices.clear()
                self.factory.fail_create = failure_pin
                with self.assertRaisesRegex(RuntimeError, "initialization failed.*init fault"):
                    tb6612.TB6612MotorController(pin_factory=self.factory)
                stop_order = [pin for pin in (22, 18, 17, 27) if pin in previous_pins]
                close_order = [pin for pin in (18, 17, 27, 22) if pin in previous_pins]
                operations = [event for event in self.factory.events if event[0] != "create"]
                self.assertEqual(operations, [*(('write', pin, 0) for pin in stop_order), *(('close', pin) for pin in close_order), ("close_factory",)])
                self.assert_all_low()

    def test_init_error_does_not_hide_cleanup_error(self):
        self.factory.fail_create = 18
        self.factory.fail_close = {17}
        self.factory.fail_factory_close = True
        with self.assertRaisesRegex(RuntimeError, "initialization failed.*Cleanup also failed.*close AIN1.*close GPIO factory"):
            tb6612.TB6612MotorController(pin_factory=self.factory)
        self.assertIn(("close", 22), self.factory.events)
        self.assertEqual(self.factory.events[-1], ("close_factory",))

    def test_missing_gpio_dependency_is_an_error_without_mock_fallback(self):
        with patch.dict(sys.modules, {"gpiozero": None}):
            with self.assertRaisesRegex(RuntimeError, "initialization failed.*gpiozero/lgpio"):
                tb6612.TB6612MotorController()
        self.assertEqual(self.factory.events, [])
        self.local_factory.assert_not_called()

    def test_factory_failure_does_not_open_any_output(self):
        self.local_factory.side_effect = RuntimeError("GPIO permission denied")
        with self.assertRaisesRegex(RuntimeError, "initialization failed.*GPIO permission denied"):
            tb6612.TB6612MotorController()
        self.assertEqual(self.factory.events, [])

    def test_close_stops_then_releases_standby_last_and_factory(self):
        motor = self.create()
        motor.forward(0.2)
        self.factory.events.clear()
        motor.close()
        self.assertEqual(self.factory.events, [
            ("write", 22, 0), ("write", 18, 0), ("write", 17, 0), ("write", 27, 0),
            ("close", 18), ("close", 17), ("close", 27), ("close", 22), ("close_factory",),
        ])
        self.factory.events.clear()
        motor.close()
        motor.stop()
        self.assertEqual(self.factory.events, [])
        with self.assertRaisesRegex(RuntimeError, "closed"):
            motor.forward(0.2)

    def test_close_reports_all_errors_after_attempting_all_resources(self):
        motor = self.create()
        self.factory.events.clear()
        self.factory.fail_writes = {(22, 0): 1}
        self.factory.fail_close = {18, 17}
        self.factory.fail_factory_close = True
        with self.assertRaisesRegex(RuntimeError, "cleanup failed.*STBY.*close PWMA.*close AIN1.*close GPIO factory") as error:
            motor.close()
        self.assertEqual(self.factory.events[-5:], [
            ("close", 18), ("close", 17), ("close", 27), ("close", 22), ("close_factory",),
        ])
        self.factory.events.clear()
        with self.assertRaises(RuntimeError) as repeated:
            motor.close()
        self.assertEqual(str(repeated.exception), str(error.exception))
        self.assertEqual(self.factory.events, [])
        with self.assertRaisesRegex(RuntimeError, "cleanup failed"):
            motor.stop()


if __name__ == "__main__":
    unittest.main()
