"""Pi 4B + TB6612FNG 的单电机 A 通道；只有实例化时才访问本机 GPIO。"""

from math import isfinite

from server.motor import MotorController


class TB6612MotorController(MotorController):
    """台架模式。反向前的 STOP 和 0.5 秒等待由服务层统一检查。"""

    mode = "tb6612"
    supported_directions = ("forward", "backward", "stop")
    max_speed = 0.4

    AIN1 = 17  # BCM 17，物理 11
    AIN2 = 27  # BCM 27，物理 13
    PWMA = 18  # BCM 18，物理 12
    STBY = 22  # BCM 22，物理 15
    PWM_FREQUENCY = 1000

    def __init__(self, *, pin_factory=None):
        # 注入的 factory 也由本实例负责关闭；测试可传 MockFactory。
        self._factory = pin_factory
        self._outputs = {}
        self._closed = False
        self._close_error = None
        try:
            # macOS / 虚拟模式无需安装 GPIO 依赖，也不会探测真实引脚。
            from gpiozero import DigitalOutputDevice, PWMOutputDevice

            if self._factory is None:
                from gpiozero.pins.lgpio import LGPIOFactory

                # 明确指定本机 GPIO，忽略 GPIOZERO_PIN_FACTORY / PIGPIO_ADDR。
                self._factory = LGPIOFactory(chip=0)
            self._outputs["STBY"] = DigitalOutputDevice(
                self.STBY, active_high=True, initial_value=False, pin_factory=self._factory,
            )
            self._outputs["AIN1"] = DigitalOutputDevice(
                self.AIN1, active_high=True, initial_value=False, pin_factory=self._factory,
            )
            self._outputs["AIN2"] = DigitalOutputDevice(
                self.AIN2, active_high=True, initial_value=False, pin_factory=self._factory,
            )
            self._outputs["PWMA"] = PWMOutputDevice(
                self.PWMA, active_high=True, initial_value=0,
                frequency=self.PWM_FREQUENCY, pin_factory=self._factory,
            )
        except Exception as error:
            cleanup = ""
            try:
                self.close()
            except RuntimeError as cleanup_error:
                cleanup = f" Cleanup also failed: {cleanup_error}"
            raise RuntimeError(
                "TB6612 initialization failed. Check gpiozero/lgpio installation, "
                f"local GPIO permissions and wiring: {error}.{cleanup}"
            ) from error

    def _drive(self, speed, *, forward):
        if self._closed:
            raise RuntimeError("TB6612 controller is closed; restart the service before moving.")
        if (
            isinstance(speed, bool) or not isinstance(speed, (int, float))
            or not 0 <= speed <= self.max_speed or not isfinite(speed)
        ):
            raise ValueError("TB6612 speed must be finite and between 0 and 0.4.")
        if speed == 0:
            self.stop()
            return
        try:
            # STBY 低使输出高阻；PWM 归零后再改方向，最后才使能。
            self._outputs["STBY"].value = 0
            self._outputs["PWMA"].value = 0
            self._outputs["AIN1"].value = int(forward)
            self._outputs["AIN2"].value = int(not forward)
            self._outputs["PWMA"].value = speed
            self._outputs["STBY"].value = 1
        except Exception as error:
            cleanup = ""
            try:
                self.stop()
            except RuntimeError as stop_error:
                cleanup = f" Stop also failed: {stop_error}"
            raise RuntimeError(f"TB6612 movement failed: {error}.{cleanup}") from error

    def forward(self, speed: float):
        self._drive(speed, forward=True)

    def backward(self, speed: float):
        self._drive(speed, forward=False)

    def turn_left(self, speed: float):
        raise ValueError("TB6612 single-motor mode does not support left turns.")

    def turn_right(self, speed: float):
        raise ValueError("TB6612 single-motor mode does not support right turns.")

    def stop(self):
        if self._closed:
            if self._close_error:
                raise RuntimeError(self._close_error)
            return
        errors = []
        # 即使某一引脚失败，也尝试关闭其余所有输出；不能把失败当作停机成功。
        for name in ("STBY", "PWMA", "AIN1", "AIN2"):
            device = self._outputs.get(name)
            if device is not None:
                try:
                    device.value = 0
                except Exception as error:
                    errors.append(f"{name}: {error}")
        if errors:
            raise RuntimeError("TB6612 stop failed; motor stop is unconfirmed: " + "; ".join(errors))

    def close(self):
        if self._closed:
            if self._close_error:
                raise RuntimeError(self._close_error)
            return
        errors = []
        try:
            self.stop()
        except RuntimeError as error:
            errors.append(str(error))
        # 保持 STBY 低到最后；释放后依靠驱动板的下拉保持待机。
        for name in ("PWMA", "AIN1", "AIN2", "STBY"):
            device = self._outputs.get(name)
            if device is not None:
                try:
                    device.close()
                except Exception as error:
                    errors.append(f"close {name}: {error}")
        if self._factory is not None:
            try:
                self._factory.close()
            except Exception as error:
                errors.append(f"close GPIO factory: {error}")
        self._closed = True
        if errors:
            self._close_error = "TB6612 cleanup failed: " + "; ".join(errors)
            raise RuntimeError(self._close_error)
