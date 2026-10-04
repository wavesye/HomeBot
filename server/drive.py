"""Pi 4B + DRV8833 双轮驱动与实体停止按钮 NC 反馈锁存。

TI §7.3.2 / §7.3.4：https://www.ti.com/lit/ds/symlink/drv8833.pdf
GPIO 输入：https://gpiozero.readthedocs.io/en/stable/api_input.html#button
反馈回路由程序检测后关闭驱动输出并锁定控制；按钮不直接切断电机 VM。
程序无法运行时，须手动断开电机电源。
"""

from math import isfinite
from threading import Event
from time import sleep

from server.motor import MotorController


class DRV8833DriveController(MotorController):
    """转向变化前的 STOP 和 0.5 秒等待由单进程服务层统一检查。"""

    mode = "drv8833-dual"
    supported_directions = ("forward", "backward", "left", "right", "stop")
    max_speed = 0.3

    AIN1 = 17  # 左轮，BCM 17 / 物理 11
    AIN2 = 27  # 左轮，BCM 27 / 物理 13
    BIN1 = 5   # 右轮，BCM 5 / 物理 29
    BIN2 = 6   # 右轮，BCM 6 / 物理 31
    NSLEEP = 22  # BCM 22 / 物理 15；模块标 STBY 时须确认连到 nSLEEP。
    STOP_FEEDBACK = 23  # BCM 23 / 物理 16，经按钮 NC 触点接 GND。
    PWM_FREQUENCY = 1000
    WAKE_DELAY_SECONDS = 0.001

    def __init__(self, *, pin_factory=None, invert_left=False, invert_right=False):
        if not isinstance(invert_left, bool) or not isinstance(invert_right, bool):
            raise ValueError("Wheel inversion settings must be bool values.")
        self.invert_left = invert_left
        self.invert_right = invert_right
        self._factory = pin_factory
        self._outputs = {}
        self._stop_feedback = None
        self._safety_latched = Event()
        self._closed = False
        self._close_error = None
        try:
            from gpiozero import Button, DigitalOutputDevice, PWMOutputDevice

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
            self._stop_feedback = Button(
                self.STOP_FEEDBACK, pull_up=True, bounce_time=None, pin_factory=self._factory,
            )
            # GPIO 回调来自其他线程，只锁存事件，不在回调中操作输出。
            self._stop_feedback.when_released = self._safety_latched.set
            self._sample_safety()  # 开机已开路时也锁存，但允许服务启动并显示故障。
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

    def _sample_safety(self):
        try:
            closed = self._stop_feedback.is_pressed
        except Exception as error:
            self._safety_latched.set()
            raise RuntimeError("Physical STOP feedback could not be read; cut motor power and restart.") from error
        if not closed:
            self._safety_latched.set()

    def check_safety(self):
        if self._closed:
            raise RuntimeError("DRV8833 dual controller is closed; restart the service before moving.")
        if not self._safety_latched.is_set():
            self._sample_safety()
        if self._safety_latched.is_set():
            raise RuntimeError(
                "Physical STOP circuit opened or its wire disconnected. "
                "Motion is locked; check the button and wiring, then restart Homebot."
            )

    def _drive(self, speed, *, left, right):
        if self._closed:
            raise RuntimeError("DRV8833 dual controller is closed; restart the service before moving.")
        if (
            isinstance(speed, bool) or not isinstance(speed, (int, float))
            or not 0 <= speed <= self.max_speed or not isfinite(speed)
        ):
            raise ValueError("DRV8833 dual speed must be finite and between 0 and 0.3.")
        if speed == 0:
            self.stop()
            return
        try:
            self.check_safety()
            self._outputs["NSLEEP"].value = 0
            for name in ("AIN1", "AIN2", "BIN1", "BIN2"):
                self._outputs[name].value = 0
            self._outputs["NSLEEP"].value = 1
            sleep(self.WAKE_DELAY_SECONDS)
            self.check_safety()
            # 每轮仅一根输入送 PWM，另一根保持低，使用 fast-decay 模式。
            for prefix, positive, inverted in (
                ("A", left > 0, self.invert_left), ("B", right > 0, self.invert_right),
            ):
                name = prefix + ("IN1" if positive != inverted else "IN2")
                self._outputs[name].value = speed
                self.check_safety()
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
        # STOP 不受 NC 反馈限制，且单个写入失败不能跳过其余输出。
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
        if self._stop_feedback is not None:
            try:
                self._stop_feedback.when_released = None
            except Exception as error:
                errors.append(f"detach STOP callback: {error}")
            try:
                self._stop_feedback.close()
            except Exception as error:
                errors.append(f"close STOP feedback: {error}")
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
