# Homebot

## What is Homebot?

Homebot 是一个从零学习家庭机器人软件的项目。未来希望它能在家里移动、远程查看环境并执行简单动作；目前可以通过浏览器控制虚拟电机，并预览运行服务的电脑摄像头。

## Current Version

Homebot v0.5 adds phone control over a trusted local Wi-Fi network, with an access code and touch controls.

No physical robot is required.

本版目标：让手机在与电脑相同的 Wi-Fi 下打开 Homebot，查看电脑摄像头，并通过触屏控制虚拟电机。新增局域网启动命令、访问码验证、按住移动与松开停止，以及适合手机的布局；保留鼠标、WASD / 方向键、速度滑块和 v0.4 的 2 秒心跳超时停止。

Connected 表示虚拟控制服务可用；电量固定为 100%，不代表真实设备。没有摄像头也可以使用全部虚拟电机功能。

**v0.5 实现待用户实测确认；v0.6 未开始。** 每版完成用户验收并得到确认后，再进入下一版。各版目标、内容、完成标准和用户测试见 [ROADMAP.md](ROADMAP.md)。

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

从 v0.4 升级到 v0.5 不需要安装新依赖。重启服务、刷新页面，看到顶部 V0.5 即可；运行项目仍只需要一个 Python 服务。上面的默认命令只供这台电脑访问，手机连接请按下一节操作。

## Phone control over Wi-Fi (v0.5)

### 启动与连接

1. 手机与运行 Homebot 的电脑连接同一个可信 Wi-Fi。先在原服务终端按 `Ctrl+C` 停止旧服务，保留已激活的 `.venv`。
2. 在项目目录运行：

   ```bash
   python -m server.run --lan
   ```

3. 保持终端运行，找到它打印的手机候选地址和本次访问码。自动识别不到地址、或候选地址不可用时，在电脑的 Wi-Fi 设置中查看 IPv4 地址。若端口被占用，改用 `python -m server.run --lan --port 8001`，并使用新端口的地址。
4. 手机浏览器打开终端给出的 `http://电脑局域网IP:8000` 地址。不要在手机上使用 `localhost`，那代表手机自己；`0.0.0.0` 是服务监听地址，也不是手机应打开的地址。电脑切换 Wi-Fi 后，局域网 IP 可能变化，应重新查看地址。
5. 在浏览器原生验证框中填写用户名 **`homebot`**，密码填写终端中的访问码。成功后应看到 V0.5 控制页面。

每次局域网启动默认生成新的随机访问码。若需要自定义，在启动前设置环境变量 `HOMEBOT_ACCESS_CODE`；它的值就是密码，用户名仍是 `homebot`。不要把访问码写进网页地址、截图或代码仓库。浏览器可能记住本次验证，测试错误密码时使用新的无痕窗口。

局域网启动器监听 `0.0.0.0`，使用单个服务进程，并关闭代理请求头解析。启用访问码后，页面、静态资源、API、摄像头和 `/docs` 均需要验证。原来的本机 `uvicorn server.main:app --reload` 仍可在没有访问码时供 `localhost` 使用；若直接加 `--host 0.0.0.0` 而没有设置访问码，远程请求会收到 HTTP 503。请使用上面的局域网启动命令。

访问码使用 [HTTP Basic 验证](https://fastapi.tiangolo.com/advanced/security/http-basic-auth/)。本版 HTTP 连接不加密，只适用于可信局域网；不要配置公网访问或路由器端口转发。验证方式的传输限制见 [MDN 说明](https://developer.mozilla.org/en-US/docs/Web/HTTP/Guides/Authentication)。

### 手机怎么操作

- 将 Speed 调到需要的值，例如 50%，再**按住**方向按钮移动；松开手指或触屏操作被取消时停止。触笔采用相同规则。再次按住才会继续移动。
- 点击 **STOP** 随时停止。移动中调整滑块仍只影响下一次动作。
- 点击 **Start camera** 查看运行服务的电脑摄像头；点击 **Stop camera** 关闭并释放设备。手机摄像头不会被开启。
- 手机布局缩小预览区域，让画面与控制按钮更容易同时查看；主要操作按钮至少为 44 像素的触控目标。
- 锁屏、切换应用、隐藏或关闭页面时停止心跳并尽力发送 STOP。请求未送达时，后端在最后一次有效心跳满 2 秒后停止。解锁或恢复网络不会自动恢复移动，需要重新操作。

电脑鼠标仍采用点击后持续移动，键盘仍采用按住移动、松开停止。建议一次只使用一个控制页面，因为所有页面共享同一组虚拟电机和电脑摄像头。

### 手机打不开时

先核对终端仍在运行、地址与端口一致，手机和电脑连接的是同一个 Wi-Fi。访客网络、AP/客户端隔离可能禁止设备互相连接；可换用允许设备互通的可信网络。暂时退出影响局域网访问的 VPN 后重试。检查电脑防火墙是否允许启动 Homebot 的 Python/终端应用接收入站连接，按应用允许即可，不需要关闭整个防火墙。

若已经弹出验证框，说明已连到服务，接下来核对 `homebot` 和当前终端中的访问码。服务重启后随机访问码会变化；浏览器仍使用旧码时，可在新无痕窗口重新输入。摄像头报错则按下面的摄像头排查步骤检查，访问页面成功不代表摄像头权限已授予。

### 本版完成标准与用户测试

完成标准是：真实手机可在同一 Wi-Fi 下通过访问码进入页面，错误访问码被拒绝；电脑摄像头可查看、关闭并释放；50% 方向操作、松开停止和 STOP 正常；锁屏或断网后停止，恢复连接不自动移动。需要用户完成下方 [v0.5 手机逐步验收](#v05-手机逐步验收待用户确认) 并确认结果，才进入 v0.6。

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

鼠标点击方向后持续移动，直到下一条指令、手动停止、页面失焦或连接失败；鼠标接管后，松开之前的按键不会覆盖新的鼠标动作。请求过程中其他方向按钮暂时禁用，当前触屏按住的按钮与 STOP 保持可用。

当焦点在滑块、输入框或可编辑区域内时，键盘保留原生操作，包括空格；点击空白处后再进行键盘遥控。Ctrl / Command / Alt 快捷键和输入法输入不会触发移动。切换窗口、隐藏标签页或离开页面时，鼠标与键盘动作都会停止续发心跳，并尝试发送停止请求。

### 超时停止（v0.4）

每次移动后，后端返回这次动作的 `command_id`。发起动作的页面收到确认后，才每 500 毫秒携带这个编号发送心跳。心跳只延长当前动作的有效期，不会启动、改变或恢复移动；另一个页面读取状态也不会接管续期。

后端使用独立的后台任务，每 100 毫秒检查一次：从移动指令或最近一次有效心跳开始计时，满 2 秒没有续期就调用 `motor.stop()`。因此，即使浏览器断网、关闭或崩溃，仍在运行的后端也会超时停止。检查间隔及服务调度会带来少量延迟；本项目仍使用虚拟电机，这不是硬件急停机制。

页面每秒读取 `/api/status`，使 Auto-stop、Direction 和 Speed 跟上后端的超时停止。读取状态不会续期。移动、心跳或状态请求失败时，页面取消自动续期并尝试 STOP；恢复网络后不会自动恢复移动，需要重新点击方向或松开并重新按键。关闭页面的 STOP 请求只能尽力送达，未送达时由后端超时处理。

## Camera preview (v0.2.1)

1. 启动 Homebot 并打开页面，摄像头初始为关闭状态。
2. 点击 **Start camera**。程序读取运行 FastAPI 的电脑上的默认摄像头（编号 `0`），不是访问网页的手机或另一台电脑的摄像头。
3. macOS 首次使用时，先按下面的“首次授权检查”在终端完成权限与读图检查。在系统询问时，为启动 Python 的终端或应用授权。
4. 看到画面后仍可点击移动按钮，电机继续只在终端打印。
5. 点击 **Stop camera** 释放摄像头。切换到其他标签页或隐藏页面也会尝试关闭；重新显示页面后需手动开启。

关闭页面时会发送一次尽力而为的停止请求，断网或浏览器崩溃时不能保证送达。可以重新打开页面点击 Stop camera，或在服务终端按 `Ctrl+C` 释放摄像头。页面没有录制功能，程序不保存图片文件。

预览使用连续 JPEG 请求，最多约每秒 5 张；拍摄、传输还会消耗时间，所以实际刷新率可能更低。使用一个浏览器控制页面和一个服务进程即可；多个页面共享同一个摄像头，任意页面关闭它都会影响其他页面。

如果显示 Cannot open camera，检查摄像头连接、系统权限以及是否被其他应用占用。这个提示不会影响虚拟电机控制。摄像头来源始终是运行服务的电脑；手机可以通过同一 Wi-Fi 查看预览，本版不提供公网远程访问配置。

### 首次授权检查（v0.2.1）

先关闭网页摄像头。在项目目录激活 `.venv` 后，执行：

```bash
python -m server.camera --check
```

命令在 Python 主线程中尝试打开默认摄像头、读取一张 JPEG，然后释放设备，不保存或打印画面。成功时输出 `Camera OK: received ... JPEG bytes. No image saved.` 和 `Camera released.`，退出码为 0；失败时给出检查建议，退出码为 1。

macOS 首次请求权限可能先弹出授权框、随后本次命令返回失败；允许后再运行一次检查。若已拒绝授权，请到“系统设置 → 隐私与安全性 → 摄像头”检查启动 Python 的应用，再重试。尽量从同一个终端应用运行检查和 Uvicorn，因为权限与启动应用有关。看到 Camera OK 后，再在网页点击 Start camera。

这样做的原因：首次从 FastAPI 工作线程打开设备时，本机出现 OpenCV 无法在该线程处理 macOS 授权的错误；主线程检查成功后，网页能够正常读取。[OpenCV 的 macOS 采集实现说明](https://github.com/opencv/opencv/issues/24624)包含对应的权限分支。

v0.2.1 还修复了读图、编码或设备设置异常后的资源释放。网页摄像头请求超过 10 秒会报错；开启失败时还会尝试关闭设备，因此整个失败处理可能持续约 20 秒。HTTP 请求超时不等于底层设备调用已经取消：如果页面提示 Stop not confirmed，可重试 Stop camera，或停止服务。页面的 Camera not working? 中也有排查步骤。

静态脚本和样式地址带有 `?v=0.5.0`，避免升级后浏览器复用旧文件。以后发布新版本时，要同步更新这些地址的版本号。

## Project structure

```text
homebot_v1/
├── README.md
├── ROADMAP.md       # 按版本记录目标、完成标准与用户验收
├── requirements.txt
├── .gitignore
├── server/
│   ├── main.py       # 接收 HTTP 请求、心跳与后台超时停止、提供静态网页
│   ├── run.py        # 局域网启动、访问码与手机访问地址
│   ├── access.py     # 网页与 API 的访问验证、请求来源检查
│   ├── camera.py     # 打开摄像头、读取 JPEG、释放设备、命令行检查
│   └── motor.py      # 电机能力约定和打印动作的实现
├── web/
│   ├── index.html   # 按钮、滑块、状态与自动停止提示
│   ├── style.css    # 页面样式
│   └── app.js       # 鼠标/键盘/触屏、心跳、状态轮询与摄像头预览
└── tests/
    ├── test_access.py    # 访问码验证与无访问码时的远程访问保护
    ├── test_camera.py    # 使用替身测试，不打开真实摄像头
    ├── test_run.py       # 局域网启动参数与地址提示
    ├── test_safety.py    # 测试后端心跳、超时与停止行为
    └── test_controls.cjs # 使用请求与事件替身测试键盘、触屏、心跳和失败处理
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

- **Browser**：显示用户操作界面；v0.5 局域网访问先通过原生验证框输入用户名和访问码。
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

### 跟着一次触屏操作读数据流（v0.5）

```text
手指按住方向 → pointerdown → sendMove(direction) → POST /api/move
手指松开或触屏取消 → pointerup / pointercancel → sendMove("stop")
```

触屏和触笔使用 Pointer Events 区分按住与松开；移动确认后沿用现有心跳。鼠标仍走点击控制，避免把手机松手后产生的点击再当作一次移动。访问验证发生在处理请求之前，因此页面、控制接口和摄像头都使用同一访问码。

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

v0.5 启用访问码时，以下接口以及摄像头接口、页面和 `/docs` 都需要 HTTP Basic 验证：用户名 `homebot`，密码为启动终端中的访问码。未验证或密码错误会返回 HTTP 401。浏览器验证后可继续使用页面和交互文档；访问码不放在 JSON 请求体或 URL 中。未设置访问码时只允许本机访问，远程请求返回 HTTP 503。服务会拒绝其他网站发来的跨来源请求，返回 HTTP 403；请直接打开 Homebot 页面操作。

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

滑块只选择下一次动作的速度，拖动本身不发送移动指令。请求过程中其他方向按钮暂时禁用，当前触屏按住的按钮与 STOP 保持可用。移动请求限时 5 秒，心跳请求限时 1.5 秒；请求失败时取消自动续期、丢弃等待中的移动并尝试一次停止。停止也失败时显示错误，恢复连接后需重新操作。浏览器超时不等于后端已取消原请求；后端独立计时，处理缺少有效心跳的动作。

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

### v0.5 开发验证记录（2026-09-16）

- 55 项 Python 测试、33 项 JavaScript 测试通过，共 88 项；JavaScript 语法与差异格式检查通过。
- 在本机浏览器检查了 320px、390px 竖屏和 844×390 横屏布局，没有横向溢出；390px 下方向按钮高度 60px，摄像头按钮与滑块操作区高度至少 44px。
- 本机浏览器的鼠标 Forward / 50% 与 STOP / 0% 回归通过，没有 JavaScript 错误。触屏捕获、松开、取消、多指与合成点击由自动测试覆盖，真实手机触屏仍待下表验收。
- 在临时回环地址服务上通过真实 HTTP 检查：未验证时页面、静态资源、API、摄像头和文档受保护；正确访问码可访问；跨源移动请求被拒；有效心跳和 2 秒超时停止正常。测试始终没有开启摄像头。

上述检查只证明代码与本机测试行为；本次未替用户完成真实手机、局域网或摄像头验收。临时测试服务已关闭，v0.5 仍待用户按下表确认，v0.6 未开始。

### v0.5 手机逐步验收（待用户确认）

以下为需要用户在真实手机和 Wi-Fi 上完成的检查，不是已通过的测试记录。本次没有在文档中认定真实手机、Wi-Fi 或真实摄像头已验证。建议每步记下“通过”或出现的具体提示。

| 步骤 | 需要用户做什么 | 完成标准 |
| --- | --- | --- |
| 1. 手机访问 | 按上面的局域网启动步骤操作，用同一 Wi-Fi 的手机打开终端地址，填写 `homebot` 和访问码 | 看到 V0.5、Local Wi-Fi、Connected、摄像头区域与控制按钮；竖屏可正常操作 |
| 2. 错误访问码 | 新开无痕窗口，用正确用户名和错误访问码访问；也检查 `/api/status` 或 `/docs` | 被拒绝或再次提示验证，无法读取状态、使用接口或查看摄像头 |
| 3. 摄像头 | 在已正确验证的页面点 Start camera，确认画面随电脑镜头前的物体变化；点 Stop camera，观察摄像头指示灯（如有），再开启一次 | 手机能看电脑实时画面；关闭后图片消失、电脑摄像头释放；重新开启可恢复 |
| 4. 50% 方向 | 设置 Speed 50%，依次按住前进、后退、左转、右转；其中一次保持超过 2 秒 | 页面与终端显示对应方向和 50%；按住时持续移动，松开后 Stop / 0% |
| 5. STOP 与触屏取消 | 再次按住方向，操作 STOP；也检查手指离开按钮后松开、系统取消触屏操作 | 动作停止；松手后不会因额外点击事件又恢复移动 |
| 6. 锁屏或断网 | 移动时锁屏，或断开手机 Wi-Fi，电脑服务继续运行；对照电脑终端 | 电机停止；若页面 STOP 未送达，最后有效心跳满 2 秒后由后端停止，检查间隔可能有少量延迟 |
| 7. 恢复与收尾 | 解锁或重新连上 Wi-Fi，回到页面；确认状态，再点 STOP 和 Stop camera | 不自动恢复旧动作；必须重新按住方向才移动；测试结束电机停止、摄像头关闭 |

如果设备没有摄像头或还未授权，先完成访问与虚拟电机检查，再按“首次授权检查”处理；手机视频部分应保留为未通过，不能据此确认本版全部完成。反馈时说明手机型号、浏览器，以及哪些步骤通过或失败即可。**用户确认 v0.5 验收完成后才开始 v0.6。**

开发时的自动检查仍可使用：

```bash
python -m unittest discover -s tests -v
node --test tests/test_controls.cjs
node --check web/app.js
```

新增的 `test_access.py` 和 `test_run.py` 检查访问保护、局域网启动和参数；JavaScript 测试增加触屏按住、松开与取消行为。替身测试和本机浏览器检查不能代替上表中的真实手机、Wi-Fi 和摄像头验证。

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

### v0.5 阅读顺序与练习

1. `server/run.py`：看 `--lan` 如何选择监听地址、生成访问码，并把手机访问地址打印到终端；区分监听地址与手机实际访问的局域网 IP。
2. `server/access.py`：理解页面和 API 为什么都必须在验证后处理，为什么未设置访问码的本机模式会拒绝远程请求。
3. `web/app.js`：找方向按钮的 Pointer Events 监听器，对照按住、松开、取消如何调用现有移动与停止逻辑。
4. `web/style.css`：查看手机布局与触控目标大小；再用手机横屏、竖屏检查是否容易操作。
5. `tests/test_access.py`、`tests/test_run.py` 和 `tests/test_controls.cjs`：把正常访问、错误访问码、触屏释放等测试对应回实际操作。

小练习：用 `--port 8001` 启动局域网模式，观察终端给出的手机地址，再尝试打开旧的 8000 端口。思考：为什么电脑上的 `localhost` 能打开，而手机的 `localhost` 不能访问这台电脑？这个练习尚未替你执行。

v0.5 实现待用户实测确认；v0.6 未开始。后续按 [ROADMAP.md](ROADMAP.md) 顺序推进，每版经用户确认后再继续。
