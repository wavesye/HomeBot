# Homebot

## What is Homebot?

Homebot 是一个从零学习家庭机器人软件的项目。未来希望它能在家里移动、远程查看环境并执行简单动作；目前可以通过浏览器控制虚拟电机，并预览运行服务的电脑摄像头。

## Current Version

Homebot v0.4 adds heartbeat-based automatic stopping to virtual motors, with keyboard control and an optional computer camera.

No physical robot is required.

保留前进、后退、左转、右转、停止、速度滑块、WASD / 方向键控制和电脑摄像头预览，新增后端超时停止：移动中连续 2 秒未收到有效心跳，服务会停止虚拟电机。页面的 Status 区域显示自动停止原因，并每秒读取一次服务状态。Connected 表示虚拟控制服务可用；电量固定为 100%，不代表真实设备。没有摄像头也可以使用全部虚拟电机功能。

## Run locally

需要 Python 3.10 或更新版本。在终端逐行运行以下命令。

当前项目已经在本机，先进入目录：

```bash
cd /Users/waves/Documents/ChatGPT/homebot_v1
```

如果以后从 GitHub 获取，请使用项目发布后的真实仓库地址执行 `git clone <仓库地址>`，然后 `cd <下载的目录>`。目前尚未提供远程仓库地址。

macOS / Linux：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
uvicorn server.main:app --reload
```

Windows PowerShell（先进入你下载的项目目录）：

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
uvicorn server.main:app --reload
```

保持终端运行，然后在浏览器打开：

- 控制页面：http://localhost:8000
- API 交互文档：http://localhost:8000/docs
- 原始状态：http://localhost:8000/api/status

只需这一个服务。HTML、CSS、JavaScript 和 API 都由 FastAPI 提供。电机输出出现在启动 Uvicorn 的终端中，不是在浏览器控制台。按 `Ctrl+C` 停止服务。

从 v0.1 升级时，请重新执行 `python -m pip install -r requirements.txt`，安装新增的 OpenCV 依赖，再重启 Homebot。OpenCV 负责读摄像头和编码 JPEG，`headless` 表示不安装桌面图像窗口，画面由浏览器显示。

每次重新打开终端，进入项目目录、激活 `.venv`，再执行 Uvicorn 命令即可。若 8000 端口被其他项目占用，可以执行 `uvicorn server.main:app --reload --port 8001`，然后打开 http://localhost:8001。

从 v0.3 升级到 v0.4 不需要安装新依赖。重启服务、刷新页面，看到顶部 V0.4 和 Auto-stop 状态即可；运行项目仍只需要一个 Python 服务。

## Keyboard control (v0.3 起)

先把 Speed 调到需要的值，再点击页面空白处，使焦点离开滑块。

| 按键 | 动作 |
| --- | --- |
| W / ↑ | 前进 |
| S / ↓ | 后退 |
| A / ← | 左转 |
| D / → | 右转 |
| 空格 / 页面 STOP | 停止，速度归零 |

按住方向键时移动，松开当前控制方向的按键时发送停止。按住期间不会重复发送相同移动指令，但 v0.4 会为已确认的当前动作每 500 毫秒发送心跳。页面会高亮当前按键对应的方向按钮。速度在按下时读取；持续按住时拖动滑块不会自动改变速度，松开再按即可使用新速度。

同时按两个方向时，后按下的方向接管。例如按住 W 后再按 D，机器人转为右转；松开 W 不影响 D，松开 D 则停止，不会自动回到前进。按空格停止后，仍按住的方向键也不会自动恢复移动，需要松开并重新按下。

鼠标点击方向后持续移动，直到下一条指令、手动停止、页面失焦或连接失败；鼠标接管后，松开之前的按键不会覆盖新的鼠标动作。请求过程中方向按钮暂时禁用，STOP 始终可用。

当焦点在滑块、输入框或可编辑区域内时，键盘保留原生操作，包括空格；点击空白处后再进行键盘遥控。Ctrl / Command / Alt 快捷键和输入法输入不会触发移动。切换窗口、隐藏标签页或离开页面时，鼠标与键盘动作都会停止续发心跳，并尝试发送停止请求。

### 超时停止（v0.4）

每次移动后，后端返回这次动作的 `command_id`。发起动作的页面收到确认后，才每 500 毫秒携带这个编号发送心跳。心跳只延长当前动作的有效期，不会启动、改变或恢复移动；另一个页面读取状态也不会接管续期。

后端使用独立的后台任务，每 100 毫秒检查一次：从移动指令或最近一次有效心跳开始计时，满 2 秒没有续期就调用 `motor.stop()`。因此，即使浏览器断网、关闭或崩溃，仍在运行的后端也会超时停止。检查间隔及服务调度会带来少量延迟；本项目仍使用虚拟电机，这不是硬件急停机制。

页面每秒读取 `/api/status`，使 Safety、Direction 和 Speed 跟上后端的超时停止。读取状态不会续期。移动、心跳或状态请求失败时，页面取消自动续期并尝试 STOP；恢复网络后不会自动恢复移动，需要重新点击方向或松开并重新按键。关闭页面的 STOP 请求只能尽力送达，未送达时由后端超时处理。

## Camera preview (v0.2.1)

1. 启动 Homebot 并打开页面，摄像头初始为关闭状态。
2. 点击 **Start camera**。程序读取运行 FastAPI 的电脑上的默认摄像头（编号 `0`），不是访问网页的手机或另一台电脑的摄像头。
3. macOS 首次使用时，先按下面的“首次授权检查”在终端完成权限与读图检查。在系统询问时，为启动 Python 的终端或应用授权。
4. 看到画面后仍可点击移动按钮，电机继续只在终端打印。
5. 点击 **Stop camera** 释放摄像头。切换到其他标签页或隐藏页面也会尝试关闭；重新显示页面后需手动开启。

关闭页面时会发送一次尽力而为的停止请求，断网或浏览器崩溃时不能保证送达。可以重新打开页面点击 Stop camera，或在服务终端按 `Ctrl+C` 释放摄像头。页面没有录制功能，程序不保存图片文件。

预览使用连续 JPEG 请求，最多约每秒 5 张；拍摄、传输还会消耗时间，所以实际刷新率可能更低。使用一个浏览器控制页面和一个服务进程即可；多个页面共享同一个摄像头，任意页面关闭它都会影响其他页面。

如果显示 Cannot open camera，检查摄像头连接、系统权限以及是否被其他应用占用。这个提示不会影响虚拟电机控制。这里只预览本机摄像头，不提供公网远程访问配置。

### 首次授权检查（v0.2.1）

先关闭网页摄像头。在项目目录激活 `.venv` 后，执行：

```bash
python -m server.camera --check
```

命令在 Python 主线程中尝试打开默认摄像头、读取一张 JPEG，然后释放设备，不保存或打印画面。成功时输出 `Camera OK: received ... JPEG bytes. No image saved.` 和 `Camera released.`，退出码为 0；失败时给出检查建议，退出码为 1。

macOS 首次请求权限可能先弹出授权框、随后本次命令返回失败；允许后再运行一次检查。若已拒绝授权，请到“系统设置 → 隐私与安全性 → 摄像头”检查启动 Python 的应用，再重试。尽量从同一个终端应用运行检查和 Uvicorn，因为权限与启动应用有关。看到 Camera OK 后，再在网页点击 Start camera。

这样做的原因：首次从 FastAPI 工作线程打开设备时，本机出现 OpenCV 无法在该线程处理 macOS 授权的错误；主线程检查成功后，网页能够正常读取。[OpenCV 的 macOS 采集实现说明](https://github.com/opencv/opencv/issues/24624)包含对应的权限分支。

v0.2.1 还修复了读图、编码或设备设置异常后的资源释放。网页摄像头请求超过 10 秒会报错；开启失败时还会尝试关闭设备，因此整个失败处理可能持续约 20 秒。HTTP 请求超时不等于底层设备调用已经取消：如果页面提示 Stop not confirmed，可重试 Stop camera，或停止服务。页面的 Camera not working? 中也有排查步骤。

静态脚本和样式地址带有 `?v=0.4.0`，避免升级后浏览器复用旧文件。以后发布新版本时，要同步更新这些地址的版本号。

## Project structure

```text
homebot_v1/
├── README.md
├── requirements.txt
├── .gitignore
├── server/
│   ├── main.py       # 接收 HTTP 请求、心跳与后台超时停止、提供静态网页
│   ├── camera.py     # 打开摄像头、读取 JPEG、释放设备、命令行检查
│   └── motor.py      # 电机能力约定和打印动作的实现
├── web/
│   ├── index.html   # 按钮、滑块、状态与自动停止提示
│   ├── style.css    # 页面样式
│   └── app.js       # 鼠标/键盘、心跳、状态轮询与摄像头预览
└── tests/
    ├── test_camera.py    # 使用替身测试，不打开真实摄像头
    ├── test_safety.py    # 测试后端心跳、超时与停止行为
    └── test_controls.cjs # 使用可控的请求替身测试键盘、心跳和失败处理
```

`.venv` 是本机安装的 Python 环境，已通过 `.gitignore` 排除，不需要提交到 Git。

## Architecture

```text
Browser
   ↓
JavaScript
   ↓ HTTP
FastAPI
   ↓
MotorController
   ↓
MockMotorController
   ↓
Terminal output
```

- **Browser**：显示用户操作界面。
- **JavaScript**：读取点击和滑块的值，发送移动与心跳请求，定时读取状态。
- **FastAPI**：校验方向和速度，调用 Python 方法；后台检查移动是否超时。
- **MotorController**：定义机器人应有的移动能力，是一个简单的类约定。
- **MockMotorController**：实现这些能力，目前只用 `print()` 模拟电机。

为什么不在 API 里直接操作 GPIO？API 只应该关心“前进”这样的指令，不需要知道电机接在哪个引脚。现在 `motor` 是 `MockMotorController` 对象，所以 `motor.forward(0.5)` 只打印。将来可用相同的方法实现真实电机控制类；网页和 HTTP 指令不必跟着硬件接线一起修改。本版不实现这个硬件类。

基类中的 `raise NotImplementedError` 表示“这个能力需要由子类实现”。它本身不驱动任何东西；`motor: MotorController` 是类型提示，运行时实际执行的是 Mock 子类的方法。

### 跟着一次点击读数据流

1. `index.html` 的前进按钮带有 `data-direction="forward"`。
2. `app.js` 的点击监听器读取 `button.dataset.direction`。
3. `sendMove()` 把滑块的 `50` 除以 `100`，用 `fetch()` 发送：

   ```json
   { "direction": "forward", "speed": 0.5 }
   ```

4. `main.py` 的 `MoveRequest` 校验 JSON；`move()` 调用 `motor.forward(command.speed)`。
5. `motor.py` 的 `forward()` 打印：

   ```text
   [HOMEbot] Moving forward
   Left motor: 50%
   Right motor: 50%
   ```

6. 后端更新 `status`，为这次移动生成 `command_id` 并开始计时；返回 JSON 后，`app.js` 的 `renderStatus()` 将状态显示在页面上。
7. 页面为自己已确认的动作定时发送心跳；如果有效心跳中断，后端后台任务会停止虚拟电机。

### 跟着一次按键读数据流

```text
按下 W → keydown → keyDirections.KeyW → sendMove("forward")
       → processMoves() → POST /api/move → 虚拟电机 → 网页状态
松开 W → keyup → sendMove("stop") → 同一个接口 → Stop / 0%
```

`activeKey` 记录哪个按键正在控制方向，`event.repeat` 用来忽略长按产生的重复事件。`pendingMoves` 是一个普通 JavaScript 数组，保存等待发送的指令；`processMoves()` 每次发一条，等待回复后再发下一条。STOP 会清掉尚未发送的移动指令，然后排在当前请求之后，避免一次很短的按键让停止指令被丢弃。鼠标和键盘仍共用 `/api/move`；v0.4 另用 `/api/heartbeat` 维持已确认的动作。

### 跟着一次心跳读数据流（v0.4）

```text
POST /api/move → 后端开始移动，返回 command_id
       ↓
页面确认自己的动作 → 每 500ms POST /api/heartbeat {command_id}
                                      ↓
                        仅当前且未过期的编号可续期

后端每 100ms 检查 → 满 2s 未收到有效心跳 → stop() → timeout
页面每 1s GET /api/status → 显示最新状态（不续期）
```

为什么心跳要带动作编号？如果先前动作的慢心跳请求在 STOP 或新动作之后才到达，后端必须知道它已经失效。`command_id` 只标识一次动作，不是密码或用户身份；请把它当作不可拆解的字符串，原样传回即可。

### 摄像头数据流

```text
Start camera → POST /api/camera/start → CameraController.start()
浏览器 → GET /api/camera/frame → camera.read() → JPEG → <img>
         ↑                 200ms 后请求下一张              ↓
         └───────────────────────────────────────────────┘
Stop camera → POST /api/camera/stop → capture.release()
```

`camera.py` 中的 `get_frame()` 获取一张画面，`cv2.imencode()` 将它转换为浏览器认识的 JPEG。`main.py` 的 `Response(..., media_type="image/jpeg")` 返回图片，而不是 JSON。`app.js` 用 `response.blob()` 读取图片，通过 `URL.createObjectURL()` 给 `<img>` 设置临时地址；旧地址及时释放，避免一直占用内存。

`Lock` 只用于避免两个摄像头请求同时读或关闭同一个设备。摄像头路由使用普通 `def`，由 FastAPI 在工作线程中执行；摄像头读图时仍能处理移动指令。`lifespan()` 启动后台超时检查，并在服务退出时停止电机、结束后台检查和关闭摄像头。

JavaScript 的 `await` 表示等待请求结果；Python 路由上的 `async def` 是 FastAPI 支持的异步函数写法。v0.4 增加了一个后台异步任务，因此即使没有新的 HTTP 请求到达，也能检查并停止超时的动作。它仍在同一个服务进程中运行，不需要消息服务。

## API

`GET /api/status` 返回当前进程中的状态，初始值是：

```json
{
  "connected": true,
  "direction": "stop",
  "speed": 0,
  "battery": 100,
  "command_id": null,
  "stop_reason": null,
  "watchdog_timeout_ms": 2000
}
```

`POST /api/move` 接收 `direction` 和 `speed`，返回执行后的状态。v0.4 保留原有四个字段，并增加：

| 字段 | 含义 |
| --- | --- |
| `command_id` | 每次非 `stop` 移动生成的新字符串；停止时为 `null` |
| `stop_reason` | 初始或移动中为 `null`；手动停止为 `"manual"`，心跳超时为 `"timeout"`，服务关闭清理时为 `"shutdown"` |
| `watchdog_timeout_ms` | 心跳超时阈值，本版固定为 `2000` 毫秒 |

服务关闭后的接口已不可访问，`shutdown` 表示后端清理阶段的状态，不保证浏览器能读取到。

| direction | Python 方法 | 左 / 右电机 |
| --- | --- | --- |
| forward | forward(speed) | +speed / +speed |
| backward | backward(speed) | -speed / -speed |
| left | turn_left(speed) | -speed / +speed |
| right | turn_right(speed) | +speed / -speed |
| stop | stop() | 0 / 0 |

速度范围为 0.0～1.0；非法方向、越界速度或缺少字段会返回 HTTP 422，不调用电机。STOP 忽略请求中的有效速度值，状态速度始终归零。左转 30% 时打印左电机 -30%、右电机 30%。

`POST /api/heartbeat` 接收移动响应中的编号：

```json
{ "command_id": "原样填写本次移动响应中的字符串" }
```

只有编号匹配当前移动、且距离上次移动或有效心跳尚未满 2 秒，心跳才续期。格式正确的心跳均返回 HTTP 200 和当前状态；缺少编号、空字符串或类型错误返回 422。旧编号、已停止或已超时动作的心跳不能恢复移动，也不能延长新动作。手动调用 API 时，每次移动后也需要定时发送对应心跳；仅重复读取 `/api/status`，移动仍会超时停止。

状态只保存在内存，重启或 `--reload` 自动重载后恢复初始值。请按教程使用单个服务进程，不加多 worker 参数。页面每秒读取状态，每次移动和心跳后也会处理返回状态。多个页面共享同一组电机状态；新移动会替换旧动作编号，STOP 会停止当前动作。读取到另一个页面的动作编号不会让本页面自动替它发送心跳。

滑块只选择下一次动作的速度，拖动本身不发送移动指令。请求过程中暂时禁用方向按钮，STOP 保持可用。移动请求限时 5 秒，心跳请求限时 1.5 秒；请求失败时取消自动续期、丢弃等待中的移动并尝试一次停止。停止也失败时显示错误，恢复连接后需重新操作。浏览器超时不等于后端已取消原请求；后端独立计时，处理缺少有效心跳的动作。

## Acceptance tests

启动服务后，在浏览器和服务终端之间对照检查：

| 测试 | 操作 | 预期结果 |
| --- | --- | --- |
| 1 | 打开 `http://localhost:8000`（或选择的 8001 端口） | 看到 HOMEbot / Remote Control、摄像头开关、按钮、滑块和 Connected |
| 2 | 选择 50%，点击 ↑ Forward | 终端打印 Moving forward，左右电机均为 50% |
| 3 | 查看网页 Status | Direction: Forward，Speed: 50% |
| 4 | 点击 ← Left | 终端打印 Turning left，左 -50%、右 50%；网页显示 Left |
| 5 | 点击 STOP | 终端打印 Stopped，左右为 0%；网页显示 Stop、0% |

2026-09-10 的 v0.1 验收已通过，当时摄像头区域为占位。验证环境：Python 3.13.15、FastAPI 0.141.1、Uvicorn 0.52.4。

v0.2 摄像头接口：

| 请求 | 返回 |
| --- | --- |
| `POST /api/camera/start` | `{"active": true}`；失败返回 503 和原因 |
| `GET /api/camera/frame` | 一张 JPEG；未开启或读图失败返回 503 |
| `POST /api/camera/stop` | `{"active": false}`；重复关闭也可成功 |

新增验收：开启后能看到刷新画面；关闭后图片消失且摄像头释放；再次开启可恢复；没有摄像头或权限不足时显示错误，移动控制仍可使用。

不连接摄像头也能运行自动测试：

```bash
python -m unittest discover -s tests -v
```

摄像头测试使用设备替身，验证真实 JPEG 编解码、重复开关、未开启读图、设备打开失败、读取失败及编码失败。v0.4 新增的 `test_safety.py` 验证虚拟电机心跳和超时停止。真实设备和系统权限需要在自己的电脑上通过 Start camera 验证。

2026-09-11 验证记录：6 项自动测试通过；浏览器中的 50% 前进、左转和 STOP 回归通过，并核对了终端输出；临时测试服务提供的带帧编号图片能持续刷新，关闭后消失、再次开启后恢复。测试服务仅用于验证，不是项目功能。尚未开启本机真实摄像头，真实画面及系统权限未验证。

### v0.2.1 验证记录（2026-09-12）

| 检查 | 本机结果 |
| --- | --- |
| 初始权限问题 | 复现工作线程不能处理 macOS 首次授权的错误；主线程检查成功后网页可用 |
| `python -m server.camera --check` | 成功读取真实 JPEG，退出码 0，检查后释放设备 |
| 真实网页预览 | 640×480 图片成功解码；两次读取的图片地址不同，确认持续刷新 |
| 关闭和重新开启 | 关闭后画面消失；再次开启后成功显示真实画面 |
| 预览期间移动 | Forward / 50% 与 STOP / 0% 正常，终端输出对应动作 |
| 预览期间停止服务 | 图片清空、按钮恢复，提示服务器不可达及 Stop not confirmed |
| 自动测试 | 12 项通过，覆盖设备打开、设置、读取、编码异常以及命令行检查的资源释放 |
| JavaScript | `node --check web/app.js` 通过；浏览器加载了带版本号的新脚本 |

真实摄像头测试未保存画面。设备断开、权限不可用等错误分支通过替身测试覆盖，未进行真实设备物理拔插或主动撤销系统权限。最终交付时摄像头为关闭状态。

### v0.3 验收与历史验证记录

| 操作 | 预期结果 |
| --- | --- |
| Speed 50%，按下 W 再松开 | 终端先打印 Moving forward / 50%，随后 Stopped / 0% |
| 分别使用 S、A、D 和四个方向键 | 对应后退、左转、右转；松开后停止 |
| 快速点按 W | 即使前进请求尚未返回，停止指令也会随后发出 |
| 长按一个方向键 | 只发送一次移动，松开后发送停止 |
| 移动时按空格，或点击 STOP | 网页最终显示 Stop / 0%，不会自动恢复先前的方向 |
| 聚焦 Start camera 后按空格 | 发送电机停止，不会开启摄像头 |
| 聚焦 Speed 滑块后按方向键 | 只改变滑块数值，不发送移动指令 |
| 按住方向键时切换窗口或标签页 | 尝试停止当前键盘动作 |

开发者可额外运行键盘自动测试（需要 Node.js 18+，不需要 npm 安装）：

```bash
node --test tests/test_controls.cjs
```

Node.js 只用于上述测试，运行 Homebot 本身不需要 Node.js。测试执行真实的 `web/app.js`，通过可控的事件和 HTTP 替身验证按键映射、请求顺序、焦点、停止和错误恢复；v0.4 还覆盖心跳与状态轮询。

2026-09-12 验证记录：11 项键盘与请求行为测试、12 项原有摄像头测试全部通过。实际浏览器逐项按下并松开 WASD 和四个方向键，终端均打印对应动作及随后停止；鼠标前进、空格停止、聚焦摄像头按钮时空格不误触、滑块方向键调速也通过。长按重复、多键切换、失焦和慢请求顺序由自动测试覆盖。交付页面为 Stop / 0%，滑块保留 50%，摄像头关闭。

### v0.4 验收清单

以下列出本版验收行为与预期结果；实际完成的检查见下方 2026-09-14 验证记录。前面的通过记录仅对应其注明的历史版本。

| 操作 | 预期结果 |
| --- | --- |
| 打开页面 | 顶部 V0.4，状态包含 Auto-stop 与 2 秒超时说明 |
| 点击 Forward，保持页面可见且聚焦超过 2 秒 | 正常持续移动；约每 500 毫秒发送当前动作心跳 |
| 按住 W 超过 2 秒后松开 | 只发送一次前进指令，持续发送心跳；松开后停止且不再续期 |
| 鼠标移动中切换窗口、隐藏标签页或离开页面 | 心跳停止，并尝试发送 STOP；切回后不自动恢复移动 |
| 移动中断开浏览器与后端的连接，后端继续运行 | 最后一次有效心跳满 2 秒后，由后台检查停止虚拟电机；恢复连接显示 Stop / 0% 和超时原因，需要重新操作 |
| 仅通过 API 发起移动，不发送心跳，不再访问接口 | 即使没有后续请求，后端也自动停止；随后读取状态得到 `stop_reason: "timeout"` |
| 只在移动后重复读取 `/api/status` | 状态请求不延长动作，仍会超时停止 |
| STOP 后或新动作开始后，再发送旧 `command_id` 的心跳 | 不会恢复旧动作，也不会为新动作续期 |
| 两个页面打开，只有其中一个发起移动 | 另一页面可以看到状态，但不自动为该动作发送心跳 |
| 移动或心跳请求失败、超时 | 页面取消自动续期并尝试 STOP，不排队自动重试移动；恢复连接需重新操作 |
| 点击 STOP | 状态为 Stop / 0%，`command_id` 为 `null`，`stop_reason` 为 `"manual"` |
| 移动中按 Ctrl+C 退出服务 | 后端清理过程调用电机停止并释放摄像头 |

自动检查命令（不打开真实摄像头）：

```bash
python -m unittest discover -s tests -v
node --test tests/test_controls.cjs
node --check web/app.js
```

后端测试关注心跳续期、编号失效、超时停止和退出清理；前端测试关注只有已确认的本页面动作才能续期、STOP 与慢响应的顺序、失焦及失败后的停止。浏览器的真实断网和窗口切换仍可按上表手动检查，自动测试使用可控的请求和事件替身覆盖这些分支。

### v0.4 验证记录（2026-09-14）

- 27 项 Python 测试通过：15 项心跳、超时、请求校验和退出清理测试，以及 12 项原有摄像头测试。
- 22 项 JavaScript 测试通过：原有键盘与慢请求行为，以及心跳续期、失败停止、旧回复隔离、轮询、离页和返回页面。`node --check web/app.js` 通过。
- 本机独立测试服务（8004 端口）与真实浏览器验证：Forward / 50% 持续超过 2 秒、心跳持续成功；STOP 和 W 短按松开后均显示 Stop / 0%，终端动作一致；页面无 JavaScript 错误。
- 从 `/docs` 单独发出 Left / 30% 后，不发送心跳、不再访问接口，终端仍打印 Stopped；返回控制页显示 Stop / 0% 和 Auto-stopped 提示，确认后台自动停止不依赖状态读取。
- 移动时离开控制页后，接口状态为 Stop / 0%、`command_id: null`、`stop_reason: "manual"`；浏览器返回后没有自动恢复移动。

本次没有开启真实摄像头，也没有实际切断电脑网络；摄像头回归、网络失败和窗口失焦由自动测试覆盖。测试结束时电机停止、摄像头关闭。

## Learning path

建议先从 **`web/index.html`** 开始，然后沿着一次点击往后读：

1. `web/index.html`：找到 `data-direction="forward"`，理解按钮怎样携带方向。
2. `web/app.js`：看 `addEventListener("click", ...)` → `sendMove()` → `fetch()` → `renderStatus()`。重点理解 `/ 100`、`JSON.stringify()` 和 `await response.json()`。
3. `server/main.py`：看 `MoveRequest`、`@app.post("/api/move")` 和 `move()` 中的分支。这里把网络指令变成方法调用。
4. `server/motor.py`：对比基类和子类的 `forward()`，理解同一个方法名如何替换具体实现。
5. 最后看 `web/style.css`，它只负责外观，不发送指令。

### 第一个小练习

只修改 `web/index.html`，把前进按钮的可见文字 `Forward` 改成 `前进`，保留 `data-direction="forward"`。刷新后点击它，观察终端仍然打印 `Moving forward`。

想一想：为什么改变按钮上显示的文字，并不会改变发给后端的指令？先自己完成，不需要新增任何功能。

阶段练习：读完电机类后预测 `turn_left(0.3)` 的输出；读完网页后把滑块默认值和初始百分比文字改为 30%。这些练习尚未替你实现。

### v0.2 阅读顺序与练习

先读 `server/camera.py` 的 `start()`、`get_frame()` 和 `stop()`；再读 `server/main.py` 的三个 camera 路由；最后从 `web/app.js` 的 `startCamera()` 跟到 `loadCameraFrame()`。

小练习：找到 `setTimeout(loadCameraFrame, 200)`，自行把 `200` 改成 `1000`，同时修改页面中的刷新频率提示。观察刷新速度的变化，思考这与电机的 Speed 滑块有什么不同。这个练习尚未替你完成。

### v0.2.1 阅读顺序与练习

先看 `server/camera.py` 的 `check_camera()`：`try` 尝试使用设备，`except` 给出失败信息，`finally` 确保尝试释放。再看 `get_frame()` 如何释放失败的设备，最后看 `web/app.js` 的 `cameraRequest()` 和 `stopCamera()` 如何显示结果。

这一版的数据流仍然是 摄像头 → JPEG → FastAPI → 网页；新增了失败分支：设备异常 → 释放设备 → HTTP 503 → 页面提示 → 用户重试。

小练习：只修改命令行检查成功时的提示，增加一句“现在可以回到网页点击 Start camera”，然后运行检查。不要改变 `finally` 中的释放逻辑。思考：即使函数在 `try` 中执行了 `return`，为什么仍会打印 Camera released？这个练习尚未替你完成。

### v0.3 阅读顺序与练习

1. `web/index.html`：查看新增的键盘操作提示。
2. `web/app.js`：先读 `keyDirections`，再读 `keydown` 与 `keyup` 两个监听器，理解按下和松开如何产生不同指令。
3. 继续看 `sendMove()` 和 `processMoves()`：为什么已经在发送前进请求时，也必须记住随后产生的停止指令？
4. `server/main.py`：沿用原来的 `/api/move`，它不需要知道指令来自鼠标还是键盘。

小练习：在 `keyDirections` 中增加 `KeyI: "forward"`，让 I 也能前进。先自己判断：松开 I 是否需要再写一个专门的停止分支？再运行验证。这个练习尚未替你完成。

### v0.4 阅读顺序与练习

1. `server/main.py`：先看新增状态字段，以及 `/api/move` 如何为每次动作生成 `command_id` 并记录超时时间。
2. 接着看 `/api/heartbeat`：找出匹配编号和判断是否过期的条件，理解为什么晚到的心跳不能恢复移动。
3. 看 `lifespan()` 启动的后台检查：没有浏览器请求时，它如何每 100 毫秒继续检查并调用停止？退出服务时如何清理？
4. `web/app.js`：跟踪移动响应中的 `command_id`，再找 500 毫秒心跳与 1 秒状态轮询。重点区分“保持自己的动作”和“读取所有页面共享的状态”。
5. 沿 STOP、请求失败、窗口失焦和页面隐藏几个分支，查看它们怎样取消心跳，以及为什么重新连接不会自动恢复移动。
6. `tests/test_safety.py` 与 `tests/test_controls.cjs`：把测试中的请求和时间变化对应到上面的流程。

小练习：通过 `/docs` 发出一次移动，记下返回的 `command_id`，先不发送心跳，稍后读取状态并观察终端。再次移动后，在 2 秒内用 `/api/heartbeat` 传入新的编号，再比较停止时间；最后尝试传入第一次的旧编号。思考：为什么读取状态、旧编号心跳都不能延长当前动作？这个练习尚未替你执行。

本版到此为止，后续功能另行开发。
