const speedSlider = document.querySelector("#speed-slider");
const selectedSpeed = document.querySelector("#selected-speed");
const buttons = document.querySelectorAll("[data-direction]");
const connection = document.querySelector("#connection");
const errorMessage = document.querySelector("#error-message");

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

async function sendMove(direction) {
  // 等本次请求结束再接受下一次点击，保持动作顺序简单明确。
  buttons.forEach((button) => { button.disabled = true; });
  try {
    const response = await fetch("/api/move", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        direction,
        speed: direction === "stop" ? 0 : Number(speedSlider.value) / 100,
      }),
      signal: AbortSignal.timeout(5000),
    });
    if (!response.ok) throw new Error("Move request failed");
    // 后端返回执行后的状态，页面据此显示，而不是猜测执行结果。
    renderStatus(await response.json());
  } catch (error) {
    showError();
  } finally {
    buttons.forEach((button) => { button.disabled = false; });
  }
}

speedSlider.addEventListener("input", () => {
  selectedSpeed.textContent = `${speedSlider.value}%`;
});

buttons.forEach((button) => {
  button.addEventListener("click", () => sendMove(button.dataset.direction));
});

// 先读取初始状态，再启用按钮，避免初始读取覆盖刚执行的动作。
buttons.forEach((button) => { button.disabled = true; });
refreshStatus().catch(showError).finally(() => {
  buttons.forEach((button) => { button.disabled = false; });
});
