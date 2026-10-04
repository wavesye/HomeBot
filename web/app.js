const speedSlider = document.querySelector("#speed-slider");
const selectedSpeed = document.querySelector("#selected-speed");
const buttons = document.querySelectorAll("[data-direction]");
const connection = document.querySelector("#connection");
const errorMessage = document.querySelector("#error-message");
let controlsReady = false;
let sendingMove = false;
let pendingMoves = [];
let activeKey = null;
let activePointer = null;
const handledPointerClicks = new WeakSet();
let spaceHeld = false;
let wantsMovement = false;
let movementVersion = 0;
let heartbeatCommandId = null;
let heartbeatTimer;
let statusTimer;
let pageLeaving = false;
let motorMode = null;
let supportedDirections = [];
let maxSpeed = 0;
let motorFault = null;
let controlEpoch = null;
let lastMoveError = null;

const HEARTBEAT_INTERVAL_MS = 500;
const STATUS_INTERVAL_MS = 1000;

function timeoutSignal(milliseconds) {
  if (typeof AbortSignal !== "undefined" && typeof AbortSignal.timeout === "function") {
    return AbortSignal.timeout(milliseconds);
  }
  // 较早的手机浏览器也能超时中止；计时覆盖响应正文，不只覆盖 HTTP 头。
  const controller = new AbortController();
  setTimeout(() => controller.abort(), milliseconds);
  return controller.signal;
}

const keyDirections = {
  KeyW: "forward", ArrowUp: "forward",
  KeyS: "backward", ArrowDown: "backward",
  KeyA: "left", ArrowLeft: "left",
  KeyD: "right", ArrowRight: "right",
};

const directionLabels = {
  forward: "Forward",
  backward: "Backward",
  left: "Left",
  right: "Right",
  stop: "Stop",
  unknown: "Unknown",
};

function updateControlEpoch(status) {
  if ("control_epoch" in status) {
    controlEpoch = typeof status.control_epoch === "string" && status.control_epoch.length > 0 ? status.control_epoch : null;
  }
}

function isBenchMode(mode) {
  return mode === "tb6612" || mode === "drv8833";
}

function isRealMotorMode(mode) {
  return isBenchMode(mode) || mode === "drv8833-dual";
}

function canUseDirection(direction) {
  if (!controlsReady) return false;
  if (direction === "stop") return true; // 未知状态或故障时仍可重试停止。
  return !motorFault && motorMode !== null && supportedDirections.includes(direction)
    && maxSpeed > 0 && (!isRealMotorMode(motorMode) || controlEpoch !== null);
}

function motorFaultMessage() {
  return `Motor fault — cut motor power and restart service. ${motorFault}`;
}

function updateControllerDetails(status) {
  const firstRealStatus = isRealMotorMode(status.motor_mode) && motorMode !== status.motor_mode;
  if (status.motor_mode === "mock" || isRealMotorMode(status.motor_mode)) motorMode = status.motor_mode;
  if (Array.isArray(status.supported_directions)) supportedDirections = status.supported_directions;
  if (Number.isFinite(status.max_speed)) maxSpeed = Math.max(0, Math.min(1, status.max_speed));
  if ("fault" in status) motorFault = status.fault;
  const bench = isBenchMode(motorMode);
  const dual = motorMode === "drv8833-dual";
  const real = isRealMotorMode(motorMode);
  const maximumPercent = Math.floor(maxSpeed * 100);
  speedSlider.max = String(maximumPercent);
  speedSlider.value = String(firstRealStatus ? Math.min(20, maximumPercent) : Math.min(Number(speedSlider.value), maximumPercent));
  selectedSpeed.textContent = `${speedSlider.value}%`;
  document.querySelector("#maximum-speed").textContent = `${maximumPercent}%`;
  document.querySelector("#motor-mode").textContent = dual ? "DRV8833 · Two-wheel drive"
    : bench ? `${motorMode.toUpperCase()} · Single motor bench` : motorMode === "mock" ? "Mock" : "Checking controller…";
  document.querySelector("#motor-help").textContent = dual
    ? "A Left / B Right · Before changing direction, press STOP, wait at least 0.5 s and let both wheels stop completely."
    : bench
    ? "Channel A · forward / reverse only. Press STOP and wait at least 0.5 s before reversing."
    : motorMode === "mock" ? "Mock mode only prints commands. No physical motor is driven." : "Waiting for controller capabilities.";
  const calibration = document.querySelector("#drive-calibration");
  calibration.hidden = !dual;
  const polarity = (inverted) => inverted === true ? "inverted" : inverted === false ? "normal" : "not reported";
  calibration.textContent = dual ? `Polarity · A Left: ${polarity(status.left_inverted)} · B Right: ${polarity(status.right_inverted)}` : "";
  document.querySelector("#physical-stop-help").hidden = !dual;
  document.querySelector("#backward-name").textContent = bench ? "Reverse" : "Backward";
  document.querySelector("#keyboard-keys").textContent = bench ? "W S" : "W A S D";
  document.querySelector("#keyboard-arrows").textContent = bench ? "↑ ↓" : "↑ ← ↓ →";
  document.querySelector("#speed-label").textContent = real ? "PWM output" : "Speed";
  document.querySelector("#speed-help").textContent = real
    ? "Applied on your next press. PWM is an output command, not a measured shaft speed."
    : "Applied on your next direction press.";
  document.querySelector("#direction-label").textContent = real ? "Direction command" : "Direction";
  document.querySelector("#current-speed-label").textContent = real ? "PWM command" : "Speed";
  document.querySelector("#controller-footer").textContent = dual
    ? "Two-wheel drive. No wheel-speed feedback; output off does not confirm the wheels have stopped."
    : bench
    ? "Single motor bench. No rotation feedback; output off does not confirm the shaft has stopped."
    : motorMode === "mock" ? "Same Wi-Fi. Mock motors. No physical robot required." : "Checking controller…";
  updateMovementButtons();
}

function renderStatus(status) {
  updateControllerDetails(status);
  connection.textContent = status.connected ? "● Connected" : "● Disconnected";
  connection.className = status.connected ? "connection connected" : "connection disconnected";
  document.querySelector("#direction").textContent = isRealMotorMode(motorMode) && status.direction === "stop"
    ? "Output off" : isBenchMode(motorMode) && status.direction === "backward" ? "Reverse" : directionLabels[status.direction] || "Unknown";
  document.querySelector("#current-speed").textContent = Number.isFinite(status.speed) ? `${Math.round(status.speed * 100)}%` : "Unknown";
  document.querySelector("#battery").textContent = isRealMotorMode(motorMode) || status.battery === null ? "Not measured" : `${status.battery}%`;
  const timeoutSeconds = status.watchdog_timeout_ms / 1000;
  document.querySelector("#safety-status").textContent = motorFault
    ? "Motor control is locked. STOP remains available to retry."
    : status.stop_reason === "timeout"
    ? isRealMotorMode(motorMode) ? "Output disabled: heartbeat lost. Press a direction to request output again."
      : "Auto-stopped: heartbeat lost. Use a direction control to move again."
    : `Auto-stop ready · ${timeoutSeconds}s timeout${status.command_id ? " · Movement active" : ""}`;
  errorMessage.textContent = motorFault ? motorFaultMessage() : lastMoveError || "";
  errorMessage.hidden = !motorFault && !lastMoveError;
}

function showError(detail) {
  connection.textContent = "● Disconnected";
  connection.className = "connection disconnected";
  // 请求失败时无法确认当前状态，避免把旧数值当成最新状态。
  document.querySelector("#direction").textContent = "—";
  document.querySelector("#current-speed").textContent = "—";
  document.querySelector("#battery").textContent = isRealMotorMode(motorMode) ? "Not measured" : "—";
  document.querySelector("#safety-status").textContent = motorFault
    ? "Motor control is locked. STOP remains available to retry."
    : "Status unknown. Heartbeats stopped.";
  errorMessage.textContent = motorFault ? motorFaultMessage()
    : detail || lastMoveError || "Request failed. Heartbeats stopped. Check the server, then use a direction control to retry.";
  errorMessage.hidden = false;
}

function stopHeartbeat() {
  clearTimeout(heartbeatTimer);
  heartbeatCommandId = null;
}

function clearPointerControl() {
  const pointer = activePointer;
  activePointer = null; // 先放弃归属，释放捕获产生的事件不能停止下一次操作。
  if (!pointer) return;
  try {
    if (pointer.button.hasPointerCapture(pointer.id)) pointer.button.releasePointerCapture(pointer.id);
  } catch (error) {
    // 浏览器可能已经取消了这根指针或移除了捕获。
  }
}

function acceptStatus(status) {
  updateControlEpoch(status);
  // 别的页面接管或后端已超时后，不接续新动作，也不自动恢复旧动作。
  if (status.fault || (heartbeatCommandId && status.command_id !== heartbeatCommandId)) {
    stopHeartbeat();
    wantsMovement = false;
    activeKey = null;
    clearPointerControl();
    movementVersion += 1;
    if (status.fault) pendingMoves = pendingMoves.filter((command) => command.direction === "stop");
    updateMovementButtons();
  }
  renderStatus(status);
}

async function sendHeartbeat(commandId, version) {
  if (commandId !== heartbeatCommandId || version !== movementVersion || pageLeaving || document.hidden) return;
  try {
    const response = await fetch("/api/heartbeat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ command_id: commandId }),
      cache: "no-store",
      signal: timeoutSignal(1500),
    });
    if (!response.ok) throw new Error("Heartbeat failed");
    const status = await response.json();
    if (commandId !== heartbeatCommandId || version !== movementVersion) return;
    acceptStatus(status);
    if (heartbeatCommandId === commandId) {
      heartbeatTimer = setTimeout(() => sendHeartbeat(commandId, version), HEARTBEAT_INTERVAL_MS);
    }
  } catch (error) {
    if (commandId !== heartbeatCommandId || version !== movementVersion) return;
    activeKey = null;
    showError();
    sendMove("stop");
  }
}

async function refreshStatus() {
  const version = movementVersion;
  try {
    if (sendingMove) return; // 移动处理中读到的旧状态不能撤销随后确认的动作。
    const response = await fetch("/api/status", { cache: "no-store", signal: timeoutSignal(5000) });
    if (!response.ok) throw new Error("Could not read status");
    const status = await response.json();
    // 轮询只观察；操作开始前发出的旧状态不能覆盖操作结果。
    if (version === movementVersion && !sendingMove && !pageLeaving) acceptStatus(status);
  } catch (error) {
    if (version !== movementVersion || sendingMove || pageLeaving) return;
    showError();
    if (wantsMovement) {
      activeKey = null;
      sendMove("stop");
    }
  } finally {
    clearTimeout(statusTimer);
    if (!document.hidden && !pageLeaving) statusTimer = setTimeout(refreshStatus, STATUS_INTERVAL_MS);
  }
}

function updateMovementButtons() {
  buttons.forEach((button) => {
    // 按住的按钮保持可用，慢请求期间仍能收到指针释放；STOP 始终可用。
    button.disabled = !canUseDirection(button.dataset.direction)
      || (sendingMove && button.dataset.direction !== "stop" && button !== activePointer?.button);
    button.classList.toggle("keyboard-active", button.dataset.direction === keyDirections[activeKey]);
    button.classList.toggle("touch-active", button === activePointer?.button);
  });
  speedSlider.disabled = !controlsReady || motorMode === null || Boolean(motorFault);
}

function sendMove(direction) {
  if (!canUseDirection(direction) || pageLeaving) return;
  if (direction !== "stop") lastMoveError = null;
  // 新操作先结束旧动作的续期；等待中的 STOP 也不会被丢弃。
  stopHeartbeat();
  wantsMovement = direction !== "stop";
  movementVersion += 1;
  if (direction === "stop") {
    clearPointerControl();
    activeKey = null;
    pendingMoves = [];
    updateMovementButtons();
  }
  pendingMoves.push({
    direction,
    speed: direction === "stop" ? 0 : Math.max(0, Math.min(maxSpeed, Number(speedSlider.value) / 100)),
    version: movementVersion,
  });
  if (!sendingMove) processMoves();
}

async function processMoves() {
  sendingMove = true;
  updateMovementButtons();
  while (pendingMoves.length > 0) {
    const command = pendingMoves.shift();
    try {
      const response = await fetch("/api/move", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ direction: command.direction, speed: command.speed,
          ...(controlEpoch !== null ? { control_epoch: controlEpoch } : {}) }),
        keepalive: command.direction === "stop",
        signal: timeoutSignal(5000),
      });
      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        const error = new Error(typeof body.detail === "string" ? body.detail : `Move request failed (HTTP ${response.status}).`);
        error.status = response.status;
        throw error;
      }
      const status = await response.json();
      // STOP 回复即使已被新按键取代，也要先更新编号，供队列下一条指令使用。
      updateControlEpoch(status);
      if (status.fault) {
        acceptStatus(status);
        continue;
      }
      if (command.version !== movementVersion || pageLeaving) continue;
      acceptStatus(status);
      // 只续期本页刚确认的动作，轮询读到的其他动作不会获得心跳。
      if (wantsMovement && status.command_id && !document.hidden) {
        heartbeatCommandId = status.command_id;
        heartbeatTimer = setTimeout(() => sendHeartbeat(status.command_id, command.version), HEARTBEAT_INTERVAL_MS);
      }
    } catch (error) {
      if (pageLeaving) break;
      activeKey = null;
      clearPointerControl();
      wantsMovement = false;
      stopHeartbeat();
      movementVersion += 1;
      if (isRealMotorMode(motorMode) && error.status === 503) motorFault = error.message;
      if (!lastMoveError || command.direction !== "stop") lastMoveError = error.message;
      updateMovementButtons();
      showError(lastMoveError);
      // 移动失败时尝试一次停止；停止也失败就留给用户重试，避免无限请求。
      pendingMoves = command.direction === "stop" ? [] : [{ direction: "stop", speed: 0, version: movementVersion }];
    }
  }
  sendingMove = false;
  updateMovementButtons();
}

speedSlider.addEventListener("input", () => {
  selectedSpeed.textContent = `${speedSlider.value}%`;
});

buttons.forEach((button) => {
  button.addEventListener("pointerdown", (event) => {
    if (event.pointerType !== "touch" && event.pointerType !== "pen") {
      handledPointerClicks.delete(button); // 真正的鼠标按下开始新一次点击。
      return;
    }
    // 即使是被忽略的第二根手指，也不能通过稍后的 click 启动移动。
    handledPointerClicks.add(button);
    event.preventDefault();
    if (!controlsReady || pageLeaving || document.hidden) return;
    if (button.dataset.direction === "stop") {
      sendMove("stop");
      return;
    }
    if (!canUseDirection(button.dataset.direction) || spaceHeld || activePointer || event.isPrimary === false || event.button !== 0 || button.disabled) return;
    try {
      button.setPointerCapture(event.pointerId);
    } catch (error) {
      return; // 无法保证收到松手事件时，不开始这次移动。
    }
    activePointer = { id: event.pointerId, button };
    activeKey = null;
    updateMovementButtons();
    sendMove(button.dataset.direction);
  });
  button.addEventListener("lostpointercapture", releasePointerControl);
  button.addEventListener("contextmenu", (event) => event.preventDefault());
  button.addEventListener("click", (event) => {
    // pointerup 后仍可能生成 click；兼容未携带 pointerType 的旧手机浏览器。
    if (event.pointerType === "touch" || event.pointerType === "pen" || (event.detail !== 0 && handledPointerClicks.has(button))) {
      event.preventDefault();
      return;
    }
    if (!controlsReady || pageLeaving || document.hidden || button.disabled) return;
    clearPointerControl();
    activeKey = null; // 鼠标接管后，松开先前的按键不会覆盖鼠标动作。
    updateMovementButtons();
    sendMove(button.dataset.direction);
  });
});

function releasePointerControl(event) {
  if (event.pointerId !== activePointer?.id) return;
  clearPointerControl();
  updateMovementButtons();
  sendMove("stop");
}

// 捕获使滑出按钮后的松手仍到达页面；取消也走同一条停止路径。
document.addEventListener("pointerup", releasePointerControl);
document.addEventListener("pointercancel", releasePointerControl);

// 先读取初始状态，再启用按钮，避免初始读取覆盖刚执行的动作。
updateMovementButtons();
refreshStatus().finally(() => {
  controlsReady = true;
  updateMovementButtons();
});

function isEditingControl(target) {
  return target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName);
}

document.addEventListener("keydown", (event) => {
  // 不抢占输入框、滑块、输入法及浏览器的 Ctrl / Command 等快捷键。
  if (!controlsReady || event.isComposing || event.ctrlKey || event.metaKey || event.altKey || isEditingControl(event.target)) return;
  if (event.code === "Space") {
    event.preventDefault(); // 防止页面滚动或触发当前聚焦的摄像头按钮。
    if (event.repeat) return;
    spaceHeld = true;
    activeKey = null;
    updateMovementButtons();
    sendMove("stop");
    return;
  }
  const direction = keyDirections[event.code];
  if (!direction) return;
  event.preventDefault();
  if (event.repeat || spaceHeld || !canUseDirection(direction)) return;
  clearPointerControl();
  activeKey = event.code; // 后按下的方向接管，不组合方向。
  updateMovementButtons();
  sendMove(direction);
});

document.addEventListener("keyup", (event) => {
  if (event.code === "Space") {
    if (spaceHeld) event.preventDefault();
    spaceHeld = false;
    return;
  }
  // 即使焦点已移到滑块上，也必须处理正在控制机器人的那次松键。
  if (event.code !== activeKey) return;
  event.preventDefault();
  activeKey = null;
  updateMovementButtons();
  sendMove("stop");
});

function releaseMovementControl() {
  spaceHeld = false;
  activeKey = null;
  clearPointerControl();
  updateMovementButtons();
  if (wantsMovement) sendMove("stop");
}

// 鼠标与键盘都在失焦时停止；断网时由后端超时停止兜底。
window.addEventListener("blur", releaseMovementControl);
document.addEventListener("visibilitychange", () => {
  clearTimeout(statusTimer);
  if (document.hidden) releaseMovementControl();
  else if (!pageLeaving) refreshStatus();
});
window.addEventListener("pagehide", () => {
  pageLeaving = true;
  clearTimeout(statusTimer);
  stopHeartbeat();
  movementVersion += 1;
  activeKey = null;
  clearPointerControl();
  spaceHeld = false;
  updateMovementButtons();
  // 页面关闭时不等待正在发送的移动；迟到的回复也不能重新开启心跳。
  if (wantsMovement || sendingMove) {
    navigator.sendBeacon("/api/move", new Blob([
      JSON.stringify({ direction: "stop", speed: 0 }),
    ], { type: "application/json" }));
  }
  wantsMovement = false;
  pendingMoves = [];
});
window.addEventListener("pageshow", () => {
  if (!pageLeaving) return;
  pageLeaving = false;
  refreshStatus(); // 从浏览器往返缓存恢复时只刷新状态，不恢复移动。
});

// 摄像头是独立的数据流：GET 图片 → 显示 → 200ms 后再取下一张。
const cameraImage = document.querySelector("#camera-image");
const cameraStatus = document.querySelector("#camera-status");
const startCameraButton = document.querySelector("#start-camera");
const stopCameraButton = document.querySelector("#stop-camera");
let cameraActive = false;
let frameTimer;
let imageUrl;
let cameraSession = 0;

async function cameraRequest(path, method = "POST") {
  try {
    const response = await fetch(path, {
      method,
      cache: "no-store",
      signal: timeoutSignal(10000),
    });
    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      throw new Error(error.detail || `Camera request failed (HTTP ${response.status}).`);
    }
    return response;
  } catch (error) {
    if (error.name === "TimeoutError" || error.name === "AbortError") {
      throw new Error("Camera request timed out. Check camera permission and the server terminal.");
    }
    if (error instanceof TypeError) {
      throw new Error("Cannot reach the camera server. Check that Homebot is running.");
    }
    throw error;
  }
}

function clearCameraPreview() {
  cameraActive = false;
  cameraSession += 1;
  clearTimeout(frameTimer);
  cameraImage.hidden = true;
  cameraImage.removeAttribute("src");
  if (imageUrl) URL.revokeObjectURL(imageUrl);
  imageUrl = undefined;
}

async function loadCameraFrame() {
  const session = cameraSession;
  try {
    const response = await cameraRequest("/api/camera/frame", "GET");
    const blob = await response.blob();
    if (!cameraActive || session !== cameraSession) return; // 忽略上次预览尚未返回的图片。
    if (imageUrl) URL.revokeObjectURL(imageUrl);
    imageUrl = URL.createObjectURL(blob);
    cameraImage.src = imageUrl;
    cameraImage.hidden = false;
    cameraStatus.textContent = "Live · refreshes up to 5 times per second";
    frameTimer = setTimeout(loadCameraFrame, 200);
  } catch (error) {
    if (!cameraActive || session !== cameraSession) return;
    const stopped = await stopCamera();
    cameraStatus.textContent = `${error.message} ${stopped ? "Camera stopped. You can retry Start camera." : "Stop not confirmed. Retry Stop camera or stop the server."}`;
  }
}

async function startCamera() {
  startCameraButton.disabled = true;
  stopCameraButton.disabled = true;
  cameraStatus.textContent = "Opening camera… Check system permission if prompted.";
  try {
    await cameraRequest("/api/camera/start");
    cameraActive = true;
    if (document.hidden) await stopCamera();
    else loadCameraFrame();
  } catch (error) {
    // 请求超时也可能已在后端打开设备，因此再尝试关闭。
    const stopped = await stopCamera();
    cameraStatus.textContent = `${error.message} ${stopped ? "Camera stopped." : "Stop not confirmed. Retry Stop camera or stop the server."}`;
  } finally {
    stopCameraButton.disabled = false;
  }
}

async function stopCamera() {
  clearCameraPreview();
  startCameraButton.disabled = true;
  stopCameraButton.disabled = true;
  try {
    await cameraRequest("/api/camera/stop");
    cameraStatus.textContent = "Camera is off.";
    return true;
  } catch (error) {
    cameraStatus.textContent = "Could not confirm camera stopped. Retry Stop camera or stop the server.";
    return false;
  } finally {
    startCameraButton.disabled = false;
    stopCameraButton.disabled = false;
  }
}

startCameraButton.addEventListener("click", startCamera);
stopCameraButton.addEventListener("click", stopCamera);
document.addEventListener("visibilitychange", () => {
  if (document.hidden && cameraActive) stopCamera();
});
window.addEventListener("pagehide", () => {
  if (cameraActive) {
    clearCameraPreview();
    navigator.sendBeacon("/api/camera/stop");
  }
});
