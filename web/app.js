const speedSlider = document.querySelector("#speed-slider");
const selectedSpeed = document.querySelector("#selected-speed");
const buttons = document.querySelectorAll("[data-direction]");
const connection = document.querySelector("#connection");
const errorMessage = document.querySelector("#error-message");
let controlsReady = false;
let sendingMove = false;
let pendingMoves = [];
let activeKey = null;
let spaceHeld = false;

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
};

function renderStatus(status) {
  connection.textContent = status.connected ? "● Connected" : "● Disconnected";
  connection.className = status.connected ? "connection connected" : "connection disconnected";
  document.querySelector("#direction").textContent = directionLabels[status.direction];
  document.querySelector("#current-speed").textContent = `${Math.round(status.speed * 100)}%`;
  document.querySelector("#battery").textContent = `${status.battery}%`;
  errorMessage.hidden = true;
}

function showError() {
  connection.textContent = "● Disconnected";
  connection.className = "connection disconnected";
  // 请求失败时无法确认当前状态，避免把旧数值当成最新状态。
  document.querySelector("#direction").textContent = "—";
  document.querySelector("#current-speed").textContent = "—";
  document.querySelector("#battery").textContent = "—";
  errorMessage.textContent = "Request failed. Check the server terminal, then click again or reload.";
  errorMessage.hidden = false;
}

async function refreshStatus() {
  const response = await fetch("/api/status", { signal: AbortSignal.timeout(5000) });
  if (!response.ok) throw new Error("Could not read status");
  renderStatus(await response.json());
}

function updateMovementButtons() {
  buttons.forEach((button) => {
    // 等待请求时仍能点击 STOP，松键产生的停止指令也不会被丢弃。
    button.disabled = !controlsReady || (sendingMove && button.dataset.direction !== "stop");
    button.classList.toggle("keyboard-active", button.dataset.direction === keyDirections[activeKey]);
  });
}

function sendMove(direction) {
  if (!controlsReady) return;
  // STOP 清掉还没发出的移动指令；正在发送的一条结束后，下一条就是 STOP。
  if (direction === "stop") pendingMoves = [];
  pendingMoves.push({
    direction,
    speed: direction === "stop" ? 0 : Number(speedSlider.value) / 100,
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
        body: JSON.stringify(command),
        signal: AbortSignal.timeout(5000),
      });
      if (!response.ok) throw new Error("Move request failed");
      // 状态来自后端的执行结果，不是按键对应的猜测值。
      renderStatus(await response.json());
    } catch (error) {
      activeKey = null;
      showError();
      // 移动失败时尝试一次停止；停止也失败就留给用户重试，避免无限请求。
      pendingMoves = command.direction === "stop" ? [] : [{ direction: "stop", speed: 0 }];
    }
  }
  sendingMove = false;
  updateMovementButtons();
}

speedSlider.addEventListener("input", () => {
  selectedSpeed.textContent = `${speedSlider.value}%`;
});

buttons.forEach((button) => {
  button.addEventListener("click", () => {
    activeKey = null; // 鼠标接管后，松开先前的按键不会覆盖鼠标动作。
    updateMovementButtons();
    sendMove(button.dataset.direction);
  });
});

// 先读取初始状态，再启用按钮，避免初始读取覆盖刚执行的动作。
updateMovementButtons();
refreshStatus().catch(showError).finally(() => {
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
  if (event.repeat || spaceHeld) return;
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

function releaseKeyboardControl() {
  spaceHeld = false;
  if (activeKey === null) return;
  activeKey = null;
  updateMovementButtons();
  sendMove("stop");
}

// 切换窗口或标签页可能收不到 keyup，因此也要结束当前键盘动作。
window.addEventListener("blur", releaseKeyboardControl);
document.addEventListener("visibilitychange", () => {
  if (document.hidden) releaseKeyboardControl();
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
      signal: AbortSignal.timeout(10000),
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
