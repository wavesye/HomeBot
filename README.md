# Homebot

## What is Homebot?

Homebot 是一个从零学习家庭机器人软件的项目。未来希望它能在家里移动、远程查看环境并执行简单动作；目前可以通过浏览器控制虚拟电机，并预览运行服务的电脑摄像头。

## Current Version

Homebot v0.3 adds keyboard control to virtual motors and an optional computer camera.

No physical robot is required.

保留前进、后退、左转、右转、停止、速度滑块、内存状态和电脑摄像头预览，新增 WASD / 方向键控制、松键停止与空格停止。Connected 表示虚拟控制服务可用；电量固定为 100%，不代表真实设备。没有摄像头也可以使用全部虚拟电机功能。

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

从 v0.2.1 升级到 v0.3 不需要安装新依赖。重启服务、刷新页面，看到顶部 V0.3 即可；运行项目仍只需要一个 Python 服务。

## Keyboard control (v0.3)

先把 Speed 调到需要的值，再点击页面空白处，使焦点离开滑块。

| 按键 | 动作 |
| --- | --- |
| W / ↑ | 前进 |
| S / ↓ | 后退 |
| A / ← | 左转 |
| D / → | 右转 |
| 空格 / 页面 STOP | 停止，速度归零 |

按住方向键时移动，松开当前控制方向的按键时发送停止。按住期间不会重复发送相同指令，页面会高亮当前按键对应的方向按钮。速度在按下时读取；持续按住时拖动滑块不会自动改变速度，松开再按即可使用新速度。

同时按两个方向时，后按下的方向接管。例如按住 W 后再按 D，机器人转为右转；松开 W 不影响 D，松开 D 则停止，不会自动回到前进。按空格停止后，仍按住的方向键也不会自动恢复移动，需要松开并重新按下。

鼠标点击方向仍像以前一样持续到下一条指令；鼠标接管后，松开之前的按键不会覆盖新的鼠标动作。请求过程中方向按钮暂时禁用，STOP 始终可用。

当焦点在滑块、输入框或可编辑区域内时，键盘保留原生操作，包括空格；点击空白处后再进行键盘遥控。Ctrl / Command / Alt 快捷键和输入法输入不会触发移动。按键控制过程中切换窗口或隐藏标签页，会尝试发送一次停止。

后端超时自动停止仍留待 v0.4。当前失焦或请求失败时的停止依赖浏览器继续发送 HTTP 请求，断网或浏览器崩溃时不能保证送达，当前电机仍为虚拟电机。

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

静态脚本和样式地址带有 `?v=0.3.0`，避免升级后浏览器复用旧文件。以后发布新版本时，要同步更新这些地址的版本号。

## Project structure

```text
homebot_v1/
├── README.md
├── requirements.txt
├── .gitignore
├── server/
│   ├── main.py       # 接收 HTTP 请求、更新状态、提供静态网页
│   ├── camera.py     # 打开摄像头、读取 JPEG、释放设备、命令行检查
│   └── motor.py      # 电机能力约定和打印动作的实现
├── web/
│   ├── index.html   # 按钮、滑块、状态区域
│   ├── style.css    # 页面样式
│   └── app.js       # 鼠标/键盘事件、HTTP 请求、状态与摄像头预览
└── tests/
    ├── test_camera.py    # 使用替身测试，不打开真实摄像头
    └── test_controls.cjs # 使用可控的请求替身测试键盘和慢请求
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
- **JavaScript**：读取点击和滑块的值，向服务器发送请求。
- **FastAPI**：接收 JSON，校验方向和速度，然后调用 Python 方法。
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

6. 后端更新 `status` 并返回 JSON，`app.js` 的 `renderStatus()` 将它显示在页面上。

### 跟着一次按键读数据流

```text
按下 W → keydown → keyDirections.KeyW → sendMove("forward")
       → processMoves() → POST /api/move → 虚拟电机 → 网页状态
松开 W → keyup → sendMove("stop") → 同一个接口 → Stop / 0%
```

`activeKey` 记录哪个按键正在控制方向，`event.repeat` 用来忽略长按产生的重复事件。`pendingMoves` 是一个普通 JavaScript 数组，保存等待发送的指令；`processMoves()` 每次发一条，等待回复后再发下一条。STOP 会清掉尚未发送的移动指令，然后排在当前请求之后，避免一次很短的按键让停止指令被丢弃。它不需要新的后端接口或消息服务。

### 摄像头数据流

```text
Start camera → POST /api/camera/start → CameraController.start()
浏览器 → GET /api/camera/frame → camera.read() → JPEG → <img>
         ↑                 200ms 后请求下一张              ↓
         └───────────────────────────────────────────────┘
Stop camera → POST /api/camera/stop → capture.release()
```

`camera.py` 中的 `get_frame()` 获取一张画面，`cv2.imencode()` 将它转换为浏览器认识的 JPEG。`main.py` 的 `Response(..., media_type="image/jpeg")` 返回图片，而不是 JSON。`app.js` 用 `response.blob()` 读取图片，通过 `URL.createObjectURL()` 给 `<img>` 设置临时地址；旧地址及时释放，避免一直占用内存。

`Lock` 只用于避免两个摄像头请求同时读或关闭同一个设备。摄像头路由使用普通 `def`，由 FastAPI 在工作线程中执行；摄像头读图时仍能处理移动指令。`lifespan()` 负责服务退出时关闭摄像头。

JavaScript 的 `await` 表示等待请求结果；Python 路由上的 `async def` 是 FastAPI 支持的异步函数写法。这里没有后台任务或复杂并发逻辑。

## API

`GET /api/status` 返回当前进程中的状态，初始值是：

```json
{ "connected": true, "direction": "stop", "speed": 0, "battery": 100 }
```

`POST /api/move` 接收 `direction` 和 `speed`，返回执行后的同样四个状态字段。

| direction | Python 方法 | 左 / 右电机 |
| --- | --- | --- |
| forward | forward(speed) | +speed / +speed |
| backward | backward(speed) | -speed / -speed |
| left | turn_left(speed) | -speed / +speed |
| right | turn_right(speed) | +speed / -speed |
| stop | stop() | 0 / 0 |

速度范围为 0.0～1.0；非法方向、越界速度或缺少字段会返回 HTTP 422，不调用电机。STOP 忽略请求中的有效速度值，状态速度始终归零。左转 30% 时打印左电机 -30%、右电机 30%。

状态只保存在内存，重启或 `--reload` 自动重载后恢复初始值。请按教程使用单个服务进程，不加多 worker 参数。页面加载时读取一次状态，每次点击后显示该请求返回的状态；本版不做多浏览器实时同步。

滑块只选择下一次动作的速度，拖动本身不发送移动指令。请求过程中暂时禁用方向按钮，STOP 保持可用。移动请求失败或超过 5 秒时会清空无法确认的状态、丢弃等待中的移动并尝试一次停止；停止也失败时显示错误，检查服务后可重新操作。浏览器超时不等于后端已取消原请求。

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

这些测试使用设备替身，验证真实 JPEG 编解码、重复开关、未开启读图、设备打开失败、读取失败及编码失败。真实设备和系统权限需要在自己的电脑上通过 Start camera 验证。

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

### v0.3 验收

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

Node.js 只用于上述测试，运行 Homebot 本身不需要 Node.js。测试执行真实的 `web/app.js`，通过可控的事件和 HTTP 替身验证按键映射、请求顺序、焦点、停止和错误恢复。

2026-09-12 验证记录：11 项键盘与请求行为测试、12 项原有摄像头测试全部通过。实际浏览器逐项按下并松开 WASD 和四个方向键，终端均打印对应动作及随后停止；鼠标前进、空格停止、聚焦摄像头按钮时空格不误触、滑块方向键调速也通过。长按重复、多键切换、失焦和慢请求顺序由自动测试覆盖。交付页面为 Stop / 0%，滑块保留 50%，摄像头关闭。

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

本版到此为止，后续功能另行开发。
