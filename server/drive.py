"""Pi 4B + DRV8833 双轮驱动。

TI §7.3.2 / §7.3.4：https://www.ti.com/lit/ds/symlink/drv8833.pdf
程序无法运行时，须手动断开电机电源。
"""

from math import isfinite
from time import sleep

from server.motor import MotorController


def validate_pwm_scale(value):
    """校准只衰减单轮输出，不放大输出或代替 STOP。"""
    if (
        isinstance(value, bool) or not isinstance(value, (int, float))
        or not 0 < value <= 1 or not isfinite(value)
    ):
        raise ValueError("Wheel PWM scale must be finite and greater than 0 and at most 1.")
    return float(value)


class DRV8833DriveController(MotorController):
    """转向变化前的 STOP 和 0.5 秒等待由单进程服务层统一检查。"""

    mode = "drv8833-dual"
    supported_directions = ("forward", "backward", "left", "right", "stop")
    max_speed = 1.0

    AIN1 = 17  # 左轮，BCM 17 / 物理 11
    AIN2 = 27  # 左轮，BCM 27 / 物理 13
    BIN1 = 5   # 右轮，BCM 5 / 物理 29
    BIN2 = 6   # 右轮，BCM 6 / 物理 31
    NSLEEP = 22  # BCM 22 / 物理 15；模块标 STBY 时须确认连到 nSLEEP。
    PWM_FREQUENCY = 1000
    WAKE_DELAY_SECONDS = 0.001

    def __init__(
        self, *, pin_factory=None, invert_left=False, invert_right=False,
        left_scale=1.0, right_scale=1.0,
    ):
        if not isinstance(invert_left, bool) or not isinstance(invert_right, bool):
            raise ValueError("Wheel inversion settings must be bool values.")
        self.invert_left = invert_left
        self.invert_right = invert_right
        self.left_scale = validate_pwm_scale(left_scale)
        self.right_scale = validate_pwm_scale(right_scale)
        self._factory = pin_factory
        self._outputs = {}
        self._closed = False
        self._close_error = None
        try:
            from gpiozero import DigitalOutputDevice, PWMOutputDevice

            if self._factory is None:
                from gpiozero.pins.lgpio import LGPIOFactory

                self._factory = LGPIOFactory(chip=0)
            # 先休眠，再申请两轮的 PWM，所有输出默认低。
            self._outputs["NSLEEP"] = DigitalOutputDevice(
                self.NSLEEP, active_high=True, initial_value=False, pin_factory=self._factory,
            )
            for name in ("AIN1", "AIN2", "BIN1", "BIN2"):
                self._outputs[name] = PWMOutputDevice(
                    getattr(self, name), active_high=True, initial_value=0,
                    frequency=self.PWM_FREQUENCY, pin_factory=self._factory,
                )
        except Exception as error:
            cleanup = ""
            try:
                self.close()
            except RuntimeError as cleanup_error:
                cleanup = f" Cleanup also failed: {cleanup_error}"
            raise RuntimeError(
                "DRV8833 dual initialization failed. Check gpiozero/lgpio, local GPIO "
                f"permissions and wiring: {error}.{cleanup}"
            ) from error

    def _drive(self, speed, *, left, right):
        if self._closed:
            raise RuntimeError("DRV8833 dual controller is closed; restart the service before moving.")
        if (
            isinstance(speed, bool) or not isinstance(speed, (int, float))
            or not 0 <= speed <= self.max_speed or not isfinite(speed)
        ):
            raise ValueError("DRV8833 dual speed must be finite and between 0 and 1.0.")
        if speed == 0:
            self.stop()
            return
        try:
            self._outputs["NSLEEP"].value = 0
            for name in ("AIN1", "AIN2", "BIN1", "BIN2"):
                self._outputs[name].value = 0
            self._outputs["NSLEEP"].value = 1
            sleep(self.WAKE_DELAY_SECONDS)
            # 每轮仅一根输入送 PWM，另一根保持低，使用 fast-decay 模式。
            for prefix, positive, inverted, scale in (
                ("A", left > 0, self.invert_left, self.left_scale),
                ("B", right > 0, self.invert_right, self.right_scale),
            ):
                name = prefix + ("IN1" if positive != inverted else "IN2")
                self._outputs[name].value = speed * scale
        except Exception as error:
            cleanup = ""
            try:
                # 保留 GPIO，让服务层可以继续重试 STOP；退出时才释放引脚。
                self.stop()
            except RuntimeError as stop_error:
                cleanup = f" Stop also failed: {stop_error}"
            raise RuntimeError(f"DRV8833 dual movement failed: {error}.{cleanup}") from error

    def forward(self, speed: float):
        self._drive(speed, left=1, right=1)

    def backward(self, speed: float):
        self._drive(speed, left=-1, right=-1)

    def turn_left(self, speed: float):
        self._drive(speed, left=-1, right=1)

    def turn_right(self, speed: float):
        self._drive(speed, left=1, right=-1)

    def stop(self):
        if self._closed:
            if self._close_error:
                raise RuntimeError(self._close_error)
            return
        errors = []
        # 单个写入失败不能跳过其余输出。
        for name in ("NSLEEP", "AIN1", "AIN2", "BIN1", "BIN2"):
            device = self._outputs.get(name)
            if device is not None:
                try:
                    device.value = 0
                except Exception as error:
                    errors.append(f"{name}: {error}")
        if errors:
            raise RuntimeError("DRV8833 dual stop failed; motor stop is unconfirmed: " + "; ".join(errors))

    def close(self):
        if self._closed:
            if self._close_error:
                raise RuntimeError(self._close_error)
            return
        errors = []
        try:
            self.stop()
        except Exception as error:
            errors.append(str(error))
        for name in ("AIN1", "AIN2", "BIN1", "BIN2"):
            device = self._outputs.get(name)
            if device is not None:
                try:
                    device.close()
                except Exception as error:
                    errors.append(f"close {name}: {error}")
        # nSLEEP 保持低到最后；注入的 factory 也归此实例管理。
        for name, resource in (("NSLEEP", self._outputs.get("NSLEEP")), ("GPIO factory", self._factory)):
            if resource is not None:
                try:
                    resource.close()
                except Exception as error:
                    errors.append(f"close {name}: {error}")
        self._closed = True
        if errors:
            self._close_error = "DRV8833 dual cleanup failed: " + "; ".join(errors)
            raise RuntimeError(self._close_error)
