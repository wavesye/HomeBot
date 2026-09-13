from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from server.motor import MotorController, MockMotorController
from server.camera import CameraController

camera = CameraController()


@asynccontextmanager
async def lifespan(app):
    try:
        yield
    finally:
        camera.stop()  # 正常退出或异常退出时都尝试释放摄像头。


app = FastAPI(title="Homebot", version="0.3.0", lifespan=lifespan)
motor: MotorController = MockMotorController()

# 状态只存在当前进程的内存里；重启服务后恢复初始值。
status = {"connected": True, "direction": "stop", "speed": 0, "battery": 100}


class MoveRequest(BaseModel):
    direction: Literal["forward", "backward", "left", "right", "stop"]
    speed: float = Field(ge=0, le=1)


@app.get("/api/status")
async def get_status():
    return status


@app.post("/api/move")
async def move(command: MoveRequest):
    # 简单的分支方便对照 HTTP 指令与 Python 方法。
    if command.direction == "forward":
        motor.forward(command.speed)
    elif command.direction == "backward":
        motor.backward(command.speed)
    elif command.direction == "left":
        motor.turn_left(command.speed)
    elif command.direction == "right":
        motor.turn_right(command.speed)
    else:
        motor.stop()

    status["direction"] = command.direction
    status["speed"] = 0 if command.direction == "stop" else command.speed
    return status


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
