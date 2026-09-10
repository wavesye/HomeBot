"""电机接口和只打印动作的虚拟电机。速度范围为 0.0 ~ 1.0。"""


class MotorController:
    """约定电机能做什么，让上层代码不需要了解具体硬件。"""

    def forward(self, speed: float):
        raise NotImplementedError

    def backward(self, speed: float):
        raise NotImplementedError

    def turn_left(self, speed: float):
        raise NotImplementedError

    def turn_right(self, speed: float):
        raise NotImplementedError

    def stop(self):
        raise NotImplementedError


class MockMotorController(MotorController):
    """正数表示正转，负数表示反转；这里只打印，不驱动电机。"""

    def _print_action(self, action: str, left: float, right: float):
        print(
            f"[HOMEbot] {action}\n"
            f"Left motor: {left:.0%}\n"
            f"Right motor: {right:.0%}",
            flush=True,
        )

    def forward(self, speed: float):
        self._print_action("Moving forward", speed, speed)

    def backward(self, speed: float):
        self._print_action("Moving backward", -speed, -speed)

    def turn_left(self, speed: float):
        self._print_action("Turning left", -speed, speed)

    def turn_right(self, speed: float):
        self._print_action("Turning right", speed, -speed)

    def stop(self):
        self._print_action("Stopped", 0, 0)
