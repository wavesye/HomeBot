# 树莓派 OV5647 CSI 网页预览

HomeBot 默认用 OpenCV 的 `VideoCapture(0)`，适用于原电脑摄像头；Pi 的 CSI 摄像头通过可选的 Picamera2 后端接入 libcamera。网页按钮、连续 JPEG 请求及访问码方式沿用原接口。

## 当前验证状态

用户已在 Pi 上验证 `rpicam-hello` 能识别 OV5647 并采集；系统已安装 `python3-picamera2`，项目 `.venv` 已启用 `--system-site-packages`。在该环境中，Picamera2 的 `640×480 / RGB888` 图像经 OpenCV 编码得到 46067 字节 JPEG，随后正常释放相机。此字节数仅为那次检查结果，实际画面大小会变化。

本次代码接入配有硬件替身和 API 回归测试；**修改后的 HomeBot 尚未在树莓派上完成网页预览验收**。以下步骤用于补齐这项验证，不能将底层采集成功视为网页验收通过。

## 启动

先把本次修改后的源码同步到 Pi 项目目录，停止旧 HomeBot 服务以及 `rpicam-hello`、其他 Python 相机脚本。相机同一时间只交给一个服务进程使用。已有且验证成功的 `.venv` 可直接沿用，不必重建。

新环境才需要安装系统包并创建能读取系统包的虚拟环境（在 Pi 项目目录运行，不复制 Mac 的 `.venv`）：

```bash
sudo apt update
sudo apt install python3-picamera2 python3-venv
python3 -m venv --system-site-packages .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Picamera2 不加入通用 `requirements.txt`，以免电脑环境被迫安装树莓派依赖。系统安装与虚拟环境方式见 [Picamera2 官方手册](https://datasheets.raspberrypi.com/camera/picamera2-manual.pdf)。

激活现有环境，先执行 HomeBot 自带的检查，再启动网页服务：

```bash
source .venv/bin/activate
python -m server.camera --check --camera picamera2
python -m server.run --lan --camera picamera2
```

检查应输出 `Camera OK (picamera2): received ... JPEG bytes. No image saved.` 和 `Camera released.`，退出码 0。若失败，先按提示排查；不要同时运行检查脚本和已经开启摄像头的网页。启动服务只选择后端，直到点击 **Start camera** 才申请相机。此命令默认使用虚拟电机，可独立验收摄像头。

也支持环境变量，命令行显式参数优先：

```bash
HOMEBOT_CAMERA=picamera2 python -m server.run --lan
HOMEBOT_CAMERA=picamera2 python -m server.camera --check
```

恢复原电脑/USB 摄像头时用 `--camera opencv`。没有参数和环境变量时默认 `opencv`。直接使用 Uvicorn 时也可设置 `HOMEBOT_CAMERA`，但必须保持单进程并遵循项目现有访问码配置；推荐以上启动器，不使用 reload 或多 worker。

## 网页验收

1. 手机/电脑与 Pi 连接同一 Wi-Fi，访问终端打印的 `http://<Pi局域网IP>:8000`，用用户名 `homebot` 和本次访问码登录。初始摄像头关闭，电机为 Mock。
2. 点击 **Start camera**：应看到 OV5647 的实时画面。移动镜头前物体确认持续刷新，并用红、蓝物体检查颜色；刷新目标沿用原页面约每秒最多 5 张，不要求每次 JPEG 大小一致。
3. 在浏览器开发者工具可核对：`POST /api/camera/start` 返回 `{"active":true}`；`GET /api/camera/frame` 返回 200、`Content-Type: image/jpeg` 和 `Cache-Control: no-store`。
4. 点击 **Stop camera**：画面消失，停止接口返回 `{"active":false}`。在 Pi 的另一个终端运行相同的 `--check --camera picamera2`，应能采集并释放，证明服务已让出设备。
5. 回到网页再次 **Start camera**：画面恢复；至少重复三轮开关。切换到其他标签页后再回来，应保持关闭，手动开启后恢复。
6. 检查失败后的恢复：先停止网页摄像头，再在 Pi 运行 `rpicam-hello --nopreview -t 0` 占用设备，网页点击开启应收到 503 并显示原因，服务仍可响应；结束 rpicam 进程，重试开启应恢复。不要带电拔插 CSI 排线来模拟故障。
7. 摄像头开启时在服务终端按 `Ctrl+C` 正常退出，再执行上述检查命令，确认可重新占用设备。重启 HomeBot 后，网页应初始关闭，点击开启正常。最后关闭摄像头并退出服务。

记录 Pi OS / Python / Picamera2 版本、启动命令、通过或失败的步骤、终端报错原文。不要在未完成上述步骤时记录“Pi 网页预览已通过”。

## 实现与排查

Picamera2 使用 `create_video_configuration(main={"size": (640, 480), "format": "RGB888"})`、`capture_array("main")`，然后共用 `cv2.imencode(".jpg", frame)`。Picamera2 的 `RGB888` 返回 BGR 字节顺序，正好供 OpenCV 编码，不再转换红蓝通道；见 [官方手册的像素格式说明](https://datasheets.raspberrypi.com/camera/picamera2-manual.pdf)。不启动桌面预览窗口，适用于 Pi OS Lite / SSH。

开启、读帧、编码和停止共用锁。配置/启动/读取/编码失败会清理相机；Picamera2 即使 `stop()` 失败仍尝试 `close()`。若关闭本身失败，API 返回 503，保留句柄并阻止另开设备；再次 Stop 或 Start 会先重试清理。正常重复 Stop 可成功。依赖缺失只在实际开启 Picamera2 时提示，不自动回退到 OpenCV。

- 提示 Picamera2 不可用：确认已激活 Pi 的 `.venv`，系统安装了 `python3-picamera2`，并且 `.venv/pyvenv.cfg` 中 `include-system-site-packages = true`。错误详情也可能指出 Picamera2 的系统依赖缺失。
- 提示设备忙：结束其他相机程序、旧 HomeBot 进程；确认只有一个服务进程。网页停止后再运行命令行检查。
- `--check` 成功但网页失败：核对服务终端显示 `摄像头后端：picamera2`，启动的是新源码与同一虚拟环境，浏览器访问的是正确 Pi/端口，并记录接口错误详情。
- 页面提示 Stop not confirmed 或 Cannot close camera：重试 Stop；持续失败则正常退出服务后重新检查。浏览器超时不会取消底层设备调用，若驱动卡住，后续请求也可能等待同一把锁。

本地回归命令（无需相机或安装 Picamera2）：

```bash
python -m unittest discover -s tests -v
node --test tests/test_controls.cjs
```
