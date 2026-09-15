import asyncio
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

camera = CameraController()
motor: MotorController = MockMotorController()

WATCHDOG_TIMEOUT_MS = 2000
WATCHDOG_CHECK_INTERVAL_SECONDS = 0.1

# 状态只存在当前进程的内存里；重启服务后恢复初始值。
status = {
    "connected": True,
    "direction": "stop",
    "speed": 0,
    "battery": 100,
    "command_id": None,
    "stop_reason": None,
    "watchdog_timeout_ms": WATCHDOG_TIMEOUT_MS,
}
command_deadline: float | None = None


def stop_motion(reason: Literal["manual", "timeout", "shutdown"]):
    global command_deadline
    try:
        motor.stop()
    finally:
        status.update(direction="stop", speed=0, command_id=None, stop_reason=reason)
        command_deadline = None


def check_timeout():
    if command_deadline is not None and monotonic() >= command_deadline:
        stop_motion("timeout")


async def watch_motion():
    while True:
        await asyncio.sleep(WATCHDOG_CHECK_INTERVAL_SECONDS)
        # 即使没有浏览器请求，服务端也会检查并停止过期的移动。
        check_timeout()


@asynccontextmanager
async def lifespan(app):
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
            finally:
                camera.stop()  # 退出时先停电机，再释放摄像头。


app = FastAPI(title="Homebot", version="0.4.0", lifespan=lifespan)


class MoveRequest(BaseModel):
    direction: Literal["forward", "backward", "left", "right", "stop"]
    speed: float = Field(ge=0, le=1)


class HeartbeatRequest(BaseModel):
    command_id: str = Field(min_length=1)


@app.get("/api/status")
async def get_status():
    check_timeout()
    return status.copy()


@app.post("/api/move")
async def move(command: MoveRequest):
    global command_deadline
    check_timeout()
    if command.direction == "stop":
        stop_motion("manual")
        return status.copy()

    # 简单的分支方便对照 HTTP 指令与 Python 方法。
    if command.direction == "forward":
        motor.forward(command.speed)
    elif command.direction == "backward":
        motor.backward(command.speed)
    elif command.direction == "left":
        motor.turn_left(command.speed)
    elif command.direction == "right":
        motor.turn_right(command.speed)
    status.update(
        direction=command.direction,
        speed=command.speed,
        command_id=str(uuid4()),
        stop_reason=None,
    )
    command_deadline = monotonic() + WATCHDOG_TIMEOUT_MS / 1000
    return status.copy()


@app.post("/api/heartbeat")
async def heartbeat(command: HeartbeatRequest):
    global command_deadline
    check_timeout()
    # 旧标签页、延迟请求与停止后的心跳都不能重新启动或续期其他指令。
    if status["command_id"] == command.command_id:
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
