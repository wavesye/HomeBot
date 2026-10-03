"""Pi 4B + DRV8833 的单电机 A 通道；导入模块不会访问 GPIO。

适用于模块 STBY 已确认连接芯片 nSLEEP 的接法。PWM 直接送到 AIN1/2，
不是 TB6612 的独立 PWMA。TI 数据手册 §7.3.2、§7.3.4：
https://www.ti.com/jp/lit/ds/symlink/drv8833.pdf
"""

from math import isfinite
from time import sleep

from server.motor import MotorController


class DRV8833MotorController(MotorController):
    """反向前的 STOP 和 0.5 秒等待由服务层统一检查。"""

    mode = "drv8833"
    supported_directions = ("forward", "backward", "stop")
    max_speed = 0.4

    AIN1 = 17  # BCM 17，物理 11
    AIN2 = 27  # BCM 27，物理 13
    NSLEEP = 22  # BCM 22，物理 15；用户模块上标作 STBY，需核对板内连接。
    PWM_FREQUENCY = 1000
    WAKE_DELAY_SECONDS = 0.001  # nSLEEP 拉高后，最多需要 1 ms 才能驱动。

    def __init__(self, *, pin_factory=None):
        # 与现有驱动一致：注入的 factory 也归此实例管理。
        self._factory = pin_factory
        self._outputs = {}
        self._closed = False
        self._close_error = None
        try:
            from gpiozero import DigitalOutputDevice, PWMOutputDevice

            if self._factory is None:
                from gpiozero.pins.lgpio import LGPIOFactory

                # 明确只控制本机，忽略环境中可能遗留的远程 pin factory。
                self._factory = LGPIOFactory(chip=0)
            self._outputs["NSLEEP"] = DigitalOutputDevice(
                self.NSLEEP, active_high=True, initial_value=False, pin_factory=self._factory,
            )
            for name, pin in (("AIN1", self.AIN1), ("AIN2", self.AIN2)):
                self._outputs[name] = PWMOutputDevice(
                    pin, active_high=True, initial_value=0,
                    frequency=self.PWM_FREQUENCY, pin_factory=self._factory,
                )
        except Exception as error:
            cleanup = ""
            try:
                self.close()
            except RuntimeError as cleanup_error:
                cleanup = f" Cleanup also failed: {cleanup_error}"
            raise RuntimeError(
                "DRV8833 initialization failed. Check gpiozero/lgpio installation, "
                f"local GPIO permissions and STBY/nSLEEP wiring: {error}.{cleanup}"
            ) from error

    def _drive(self, speed, *, forward):
        if self._closed:
            raise RuntimeError("DRV8833 controller is closed; restart the service before moving.")
        if (
            isinstance(speed, bool) or not isinstance(speed, (int, float))
            or not 0 <= speed <= self.max_speed or not isfinite(speed)
        ):
            raise ValueError("DRV8833 speed must be finite and between 0 and 0.4.")
        if speed == 0:
            self.stop()
            return
        try:
            # 先休眠，再撤销两路旧 PWM。输入全低时唤醒，期间没有驱动输出。
            self._outputs["NSLEEP"].value = 0
            self._outputs["AIN1"].value = 0
            self._outputs["AIN2"].value = 0
            self._outputs["NSLEEP"].value = 1
            sleep(self.WAKE_DELAY_SECONDS)
            # fast-decay PWM：(PWM, 0) 正转，(0, PWM) 反转；绝不置为常高。
            self._outputs["AIN1" if forward else "AIN2"].value = speed
        except Exception as error:
            cleanup = ""
            try:
                self.stop()
            except RuntimeError as cleanup_error:
                cleanup = f" Stop also failed: {cleanup_error}"
            raise RuntimeError(f"DRV8833 movement failed: {error}.{cleanup}") from error

    def forward(self, speed: float):
        self._drive(speed, forward=True)

    def backward(self, speed: float):
        self._drive(speed, forward=False)

    def turn_left(self, speed: float):
        raise ValueError("DRV8833 single-motor mode does not support left turns.")

    def turn_right(self, speed: float):
        raise ValueError("DRV8833 single-motor mode does not support right turns.")

    def stop(self):
        if self._closed:
            if self._close_error:
                raise RuntimeError(self._close_error)
            return
        errors = []
        # 某次写入失败也要尝试其他引脚；不将不确定的输出报告为已停止。
        for name in ("NSLEEP", "AIN1", "AIN2"):
            device = self._outputs.get(name)
            if device is not None:
                try:
                    device.value = 0
                except Exception as error:
                    errors.append(f"{name}: {error}")
        if errors:
            raise RuntimeError("DRV8833 stop failed; motor stop is unconfirmed: " + "; ".join(errors))

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
        # 最后释放 nSLEEP；释放后的休眠依赖正确的板内连接与下拉。
        for name in ("AIN1", "AIN2", "NSLEEP"):
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
            self._close_error = "DRV8833 cleanup failed: " + "; ".join(errors)
            raise RuntimeError(self._close_error)
