import asyncio
import logging
import os
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from time import monotonic
from typing import Literal
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from server.motor import MotorController, MockMotorController
from server.camera import CameraController
from server.access import AccessMiddleware

camera = CameraController()
motor: MotorController = MockMotorController()  # 导入模块不会打开真实 GPIO。
logger = logging.getLogger(__name__)

WATCHDOG_TIMEOUT_MS = 2000
WATCHDOG_CHECK_INTERVAL_SECONDS = 0.1
STOP_RETRY_SECONDS = 0.5
REVERSE_PAUSE_SECONDS = 0.5

# direction/speed 是已接受的输出命令，不是编码器测得的转向或转速。
status = {
    "connected": True, "direction": "stop", "speed": 0, "battery": 100,
    "command_id": None, "stop_reason": None,
    "watchdog_timeout_ms": WATCHDOG_TIMEOUT_MS,
    "motor_mode": "mock",
    "supported_directions": ["forward", "backward", "left", "right", "stop"],
    "max_speed": 1.0, "fault": None, "control_epoch": str(uuid4()),
}
command_deadline: float | None = None
stop_retry_deadline: float | None = None
last_motion_direction: str | None = None
last_stopped_at: float | None = None


def build_motor():
    mode = os.environ.get("HOMEBOT_MOTOR", "mock")
    if mode == "mock":
        return MockMotorController()
    if mode == "tb6612":
        from server.tb6612 import TB6612MotorController
        return TB6612MotorController()
    raise ValueError("HOMEBOT_MOTOR must be mock or tb6612; no controller was started.")


def reset_status(controller):
    global command_deadline, stop_retry_deadline, last_motion_direction, last_stopped_at
    command_deadline = stop_retry_deadline = None
    last_motion_direction = last_stopped_at = None
    status.update(
        connected=True, direction="stop", speed=0,
        battery=None if controller.mode == "tb6612" else 100,
        command_id=None, stop_reason=None, motor_mode=controller.mode,
        supported_directions=list(controller.supported_directions),
        max_speed=controller.max_speed, fault=None, control_epoch=str(uuid4()),
    )


def set_motor_fault(message):
    # 故障锁定到重启；即使随后 STOP 成功，也不自动重新允许移动。
    status.update(connected=False, fault=message)


def stop_motion(reason: Literal["manual", "timeout", "shutdown", "fault"]):
    global command_deadline, stop_retry_deadline, last_stopped_at
    # 先撤销旧命令。延迟到达的旧移动不能跨越这次 STOP。
    status.update(command_id=None, control_epoch=str(uuid4()), stop_reason=reason)
    command_deadline = None
    was_stopped = status["direction"] == "stop"
    try:
        motor.stop()
    except Exception:
        set_motor_fault("Motor stop failed. Cut motor power and restart Homebot.")
        status.update(direction="unknown", speed=None, stop_reason="fault")
        stop_retry_deadline = monotonic() + STOP_RETRY_SECONDS
        logger.exception("Motor stop failed; continuing stop attempts")
        return False
    status.update(direction="stop", speed=0)
    stop_retry_deadline = None
    if not was_stopped or last_stopped_at is None:
        last_stopped_at = monotonic()
    return True


def check_timeout():
    now = monotonic()
    if command_deadline is not None and now >= command_deadline:
        stop_motion("timeout")
    elif stop_retry_deadline is not None and now >= stop_retry_deadline:
        stop_motion("fault")


async def watch_motion():
    while True:
        await asyncio.sleep(WATCHDOG_CHECK_INTERVAL_SECONDS)
        # 无浏览器请求时照常检查；停止失败由 check_timeout 定时重试。
        check_timeout()


@asynccontextmanager
async def lifespan(app):
    global motor
    # 真实设备仅在显式选择后、服务启动时初始化；失败就中止启动。
    motor = build_motor()
    reset_status(motor)
    watchdog_task = asyncio.create_task(watch_motion(), name="homebot-watchdog")
    try:
        yield
    finally:
        watchdog_task.cancel()
        try:
            with suppress(asyncio.CancelledError):
                await watchdog_task
        finally:
            try:
                stop_motion("shutdown")
                try:
                    motor.close()
                except Exception:
                    set_motor_fault("Motor cleanup failed. Cut motor power before checking wiring.")
                    status.update(direction="unknown", speed=None, stop_reason="fault")
                    logger.exception("Motor cleanup failed")
            finally:
                camera.stop()


app = FastAPI(title="Homebot", version="0.6.0", lifespan=lifespan)
app.add_middleware(AccessMiddleware)


class MoveRequest(BaseModel):
    direction: Literal["forward", "backward", "left", "right", "stop"]
    speed: float = Field(ge=0, le=1)
    control_epoch: str | None = Field(default=None, min_length=1, max_length=128)


class HeartbeatRequest(BaseModel):
    command_id: str = Field(min_length=1)


@app.get("/api/status")
async def get_status():
    check_timeout()
    return status.copy()


@app.post("/api/move")
async def move(command: MoveRequest):
    global command_deadline, last_motion_direction
    check_timeout()
    if command.direction == "stop":
        if not stop_motion("manual"):
            raise HTTPException(status_code=503, detail=status["fault"])
        return status.copy()

    if status["fault"]:
        raise HTTPException(status_code=503, detail=status["fault"])
    real_motor = status["motor_mode"] == "tb6612"
    # 真实台架必须使用当前代号；虚拟模式仍兼容没有代号的旧调用方式。
    if (real_motor or command.control_epoch is not None) and command.control_epoch != status["control_epoch"]:
        raise HTTPException(status_code=409, detail="Movement expired after STOP. Refresh status and press again.")
    if command.direction not in status["supported_directions"]:
        raise HTTPException(status_code=422, detail="Single motor bench supports Forward, Backward and STOP only.")
    if command.speed > status["max_speed"]:
        raise HTTPException(status_code=422, detail=f"Maximum bench output is {status['max_speed']:.0%}.")
    if command.speed == 0:
        if not stop_motion("manual"):
            raise HTTPException(status_code=503, detail=status["fault"])
        return status.copy()
    if real_motor and last_motion_direction and command.direction != last_motion_direction:
        if status["direction"] != "stop" or last_stopped_at is None or monotonic() - last_stopped_at < REVERSE_PAUSE_SECONDS:
            raise HTTPException(status_code=409, detail="Press STOP, wait at least 0.5 seconds and let the shaft stop before reversing.")

    # 本地 GPIO 写入不包含网络等待或 sleep；在可能产生输出之前设置期限。
    command_deadline = monotonic() + WATCHDOG_TIMEOUT_MS / 1000
    try:
        action = {
            "forward": motor.forward, "backward": motor.backward,
            "left": motor.turn_left, "right": motor.turn_right,
        }[command.direction]
        action(command.speed)
    except Exception:
        set_motor_fault("Motor command failed. Cut motor power and restart Homebot.")
        logger.exception("Motor command failed; attempting STOP")
        stop_motion("fault")
        raise HTTPException(status_code=503, detail=status["fault"])
    status.update(direction=command.direction, speed=command.speed, command_id=str(uuid4()), stop_reason=None)
    last_motion_direction = command.direction
    check_timeout()
    return status.copy()


@app.post("/api/heartbeat")
async def heartbeat(command: HeartbeatRequest):
    global command_deadline
    check_timeout()
    if not status["fault"] and status["command_id"] == command.command_id:
        command_deadline = monotonic() + WATCHDOG_TIMEOUT_MS / 1000
    return status.copy()


# 普通 def 让读摄像头在工作线程中执行，不阻塞移动指令的处理。
@app.post("/api/camera/start")
def start_camera():
    try:
        camera.start()
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    return {"active": True}


@app.get("/api/camera/frame")
def camera_frame():
    try:
        jpeg = camera.get_frame()
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    return Response(jpeg, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@app.post("/api/camera/stop")
def stop_camera():
    camera.stop()
    return {"active": False}


# 用同一个服务提供网页，浏览器可直接请求同源的 /api/move。
web_directory = Path(__file__).resolve().parent.parent / "web"
app.mount("/static", StaticFiles(directory=web_directory), name="static")


@app.get("/")
async def index():
    return FileResponse(web_directory / "index.html")
