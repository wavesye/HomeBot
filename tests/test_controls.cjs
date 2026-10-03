// 用可控的 HTTP 替身测试按键行为和慢请求，不启动服务器或摄像头。
const assert = require("node:assert/strict");
const { test } = require("node:test");
const { readFileSync } = require("node:fs");
const { join } = require("node:path");
const vm = require("node:vm");

const tick = () => new Promise((resolve) => setImmediate(resolve));

async function setup(statusOverrides = {}, options = {}) {
  function element(tagName = "DIV") {
    const node = {
      tagName, value: "50", disabled: false, hidden: true, textContent: "", dataset: {},
      classes: new Set(), listeners: {}, capturedPointers: new Set(),
      addEventListener(name, handler) { this.listeners[name] = handler; },
      setPointerCapture(id) {
        if (this.captureFails) throw new Error("Pointer no longer active");
        this.capturedPointers.add(id);
      },
      hasPointerCapture(id) { return this.capturedPointers.has(id); },
      releasePointerCapture(id) {
        this.capturedPointers.delete(id);
        this.listeners.lostpointercapture?.({ pointerId: id });
      },
    };
    node.classList = { toggle(name, enabled) { if (enabled) node.classes.add(name); else node.classes.delete(name); } };
    return node;
  }
  const nodes = new Map();
  const get = (id) => {
    if (!nodes.has(id)) nodes.set(id, element());
    return nodes.get(id);
  };
  get("#speed-slider").tagName = "INPUT";
  const buttons = ["forward", "backward", "left", "right", "stop"].map((direction) => {
    const button = element("BUTTON");
    button.dataset.direction = direction;
    return button;
  });
  const listeners = {};
  const windowListeners = {};
  const requests = [];
  const moveBodies = [];
  const waiting = [];
  const initialStatus = { connected: true, direction: "stop", speed: 0, battery: 100,
    command_id: null, stop_reason: null, watchdog_timeout_ms: 2000, control_epoch: "epoch-0",
    motor_mode: "mock", supported_directions: ["forward", "backward", "left", "right", "stop"],
    max_speed: 1, fault: null, ...statusOverrides };
  let serverStatus = initialStatus;
  let commandCount = 0;
  let epochCount = 0;
  const heartbeats = [];
  const waitingHeartbeats = [];
  const waitingStatus = [];
  const beacons = [];
  const requestSignals = [];
  const timers = new Map();
  let nextTimer = 0;
  let deferStatus = Boolean(options.deferInitialStatus);
  const document = {
    hidden: false,
    querySelector: get,
    querySelectorAll: () => buttons,
    addEventListener(name, handler) { (listeners[name] ||= []).push(handler); },
  };
  const context = vm.createContext({
    document,
    window: { addEventListener(name, handler) { (windowListeners[name] ||= []).push(handler); } },
    navigator: { sendBeacon(path, body) { beacons.push({ path, body }); return true; } },
    AbortSignal: options.legacyTimeout ? {} : AbortSignal, AbortController, URL, Blob,
    setTimeout(handler, delay) { timers.set(++nextTimer, { handler, delay }); return nextTimer; },
    clearTimeout(id) { timers.delete(id); },
    fetch(path, options) {
      requestSignals.push({ path, signal: options.signal });
      if (path === "/api/status") {
        if (deferStatus) return new Promise((resolve, reject) => waitingStatus.push({ resolve, reject }));
        return Promise.resolve({ ok: true, json: async () => serverStatus });
      }
      if (path === "/api/heartbeat") {
        heartbeats.push(JSON.parse(options.body));
        return new Promise((resolve, reject) => waitingHeartbeats.push({ resolve, reject }));
      }
      assert.equal(path, "/api/move");
      const command = JSON.parse(options.body);
      moveBodies.push(command);
      requests.push({ direction: command.direction, speed: command.speed });
      return new Promise((resolve, reject) => waiting.push({ resolve, reject, command, signal: options.signal }));
    },
  });
  vm.runInContext(readFileSync(join(__dirname, "../web/app.js"), "utf8"), context);
  await tick();

  return {
    get, buttons, requests, moveBodies, heartbeats, beacons, requestSignals,
    deferStatus() { deferStatus = true; },
    setServerStatus(status) { serverStatus = { ...serverStatus, ...status }; },
    timerCount(delay) { return [...timers.values()].filter((timer) => timer.delay === delay).length; },
    async runTimer(delay) {
      const timer = [...timers].find(([, value]) => value.delay === delay);
      assert.ok(timer, `Expected a ${delay}ms timer`);
      timers.delete(timer[0]);
      timer[1].handler();
      await tick();
    },
    async replyHeartbeat(status = serverStatus, fail = false) {
      const request = waitingHeartbeats.shift();
      assert.ok(request, "Expected an outstanding heartbeat");
      if (fail) request.reject(new Error("Test heartbeat failure"));
      else request.resolve({ ok: true, json: async () => status });
      await tick();
    },
    async replyStatus(status = serverStatus, fail = false) {
      const request = waitingStatus.shift();
      assert.ok(request, "Expected an outstanding status read");
      if (fail) request.reject(new Error("Test status failure"));
      else request.resolve({ ok: true, json: async () => status });
      await tick();
    },
    key(type, code, options = {}) {
      const event = { code, target: element("BODY"), repeat: false, preventDefault() { this.prevented = true; }, ...options };
      for (const handler of listeners[type]) handler(event);
      return event;
    },
    pointer(type, direction, options = {}) {
      const button = buttons.find((button) => button.dataset.direction === direction);
      const event = { pointerId: 1, pointerType: "touch", button: 0, isPrimary: true,
        target: button || element("BODY"), preventDefault() { this.prevented = true; }, ...options };
      if (type === "lostpointercapture") button?.capturedPointers.delete(event.pointerId);
      button?.listeners[type]?.(event);
      for (const handler of listeners[type] || []) handler(event);
      if (type === "pointerup" || type === "pointercancel") {
        for (const node of buttons) if (node.hasPointerCapture(event.pointerId)) node.releasePointerCapture(event.pointerId);
      }
      return event;
    },
    click(direction, options = {}) {
      const button = buttons.find((button) => button.dataset.direction === direction);
      const event = { detail: 1, pointerType: "mouse", preventDefault() { this.prevented = true; }, ...options };
      button.listeners.click(event);
      return event;
    },
    async replyHeaders() {
      const request = waiting.shift();
      assert.ok(request, "Expected a move request awaiting headers");
      request.resolve({ ok: true, json: () => new Promise((resolve, reject) => {
        request.signal.addEventListener("abort", () => reject(request.signal.reason), { once: true });
      }) });
      await tick();
    },
    async replyHttpError(status, detail) {
      const request = waiting.shift();
      assert.ok(request, "Expected an outstanding move request");
      request.resolve({ ok: false, status, json: async () => ({ detail }) });
      await tick();
    },
    async reply(fail = false, overrides = {}) {
      const request = waiting.shift();
      assert.ok(request, "Expected an outstanding move request");
      if (fail) request.reject(new Error("Test network failure"));
      else {
        serverStatus = { ...serverStatus, ...request.command,
          control_epoch: request.command.direction === "stop" ? `epoch-${++epochCount}` : serverStatus.control_epoch,
          command_id: request.command.direction === "stop" ? null : `command-${++commandCount}`,
          stop_reason: request.command.direction === "stop" ? "manual" : null, ...overrides };
        request.resolve({ ok: true, json: async () => serverStatus });
      }
      await tick();
    },
    blur() { for (const handler of windowListeners.blur) handler(); },
    pagehide() { for (const handler of windowListeners.pagehide) handler(); },
    pageshow() { for (const handler of windowListeners.pageshow) handler(); },
    show() {
      document.hidden = false;
      for (const handler of listeners.visibilitychange) handler();
    },
    hide() {
      document.hidden = true;
      for (const handler of listeners.visibilitychange) handler();
    },
  };
}

test("WASD and arrows move at the selected speed, then stop on release", async () => {
  const page = await setup();
  page.get("#speed-slider").value = "30";
  for (const [key, direction] of Object.entries({ KeyW: "forward", KeyS: "backward", KeyA: "left", KeyD: "right", ArrowUp: "forward", ArrowDown: "backward", ArrowLeft: "left", ArrowRight: "right" })) {
    assert.equal(page.key("keydown", key).prevented, true);
    assert.deepEqual(page.requests.at(-1), { direction, speed: 0.3 });
    await page.reply();
    page.key("keyup", key);
    assert.deepEqual(page.requests.at(-1), { direction: "stop", speed: 0 });
    await page.reply();
    assert.equal(page.get("#direction").textContent, "Stop");
    assert.equal(page.get("#current-speed").textContent, "0%");
  }
});

test("a quick release waits for the in-flight move and still sends STOP", async () => {
  const page = await setup();
  page.key("keydown", "KeyW");
  page.key("keyup", "KeyW");
  assert.equal(page.requests.length, 1);
  assert.equal(page.buttons.find((button) => button.dataset.direction === "stop").disabled, false);
  await page.reply();
  assert.deepEqual(page.requests[1], { direction: "stop", speed: 0 });
  await page.reply();
});

test("holding a key does not flood HTTP requests", async () => {
  const page = await setup();
  page.key("keydown", "KeyW");
  await page.reply();
  for (let i = 0; i < 20; i++) page.key("keydown", "KeyW", { repeat: true });
  assert.equal(page.requests.length, 1);
  page.key("keyup", "KeyW");
  await page.reply();
});

test("Space clears waiting directions and held keys do not resume movement", async () => {
  const page = await setup();
  page.key("keydown", "KeyW");
  page.key("keydown", "KeyD");
  assert.equal(page.key("keydown", "Space").prevented, true);
  page.key("keydown", "KeyA");
  page.key("keyup", "KeyD");
  await page.reply();
  assert.deepEqual(page.requests.map((request) => request.direction), ["forward", "stop"]);
  await page.reply();
  page.key("keyup", "Space");
  page.key("keydown", "KeyW", { repeat: true });
  assert.equal(page.requests.length, 2);
});

test("releasing an older direction does not stop the latest held direction", async () => {
  const page = await setup();
  page.key("keydown", "KeyW");
  await page.reply();
  page.key("keydown", "KeyD");
  await page.reply();
  page.key("keyup", "KeyW");
  assert.equal(page.requests.length, 2);
  page.key("keyup", "KeyD");
  assert.equal(page.requests.at(-1).direction, "stop");
  await page.reply();
});

test("slider, editable fields, IME and modified shortcuts keep their normal behavior", async () => {
  const page = await setup();
  for (const target of [{ tagName: "INPUT" }, { tagName: "TEXTAREA" }, { tagName: "SELECT" }, { isContentEditable: true }]) {
    assert.equal(page.key("keydown", "ArrowUp", { target }).prevented, undefined);
    page.key("keydown", "Space", { target });
  }
  for (const options of [{ ctrlKey: true }, { metaKey: true }, { altKey: true }, { isComposing: true }]) page.key("keydown", "KeyW", options);
  assert.equal(page.requests.length, 0);
  // Shift 不改变 W 的方向映射。
  page.key("keydown", "KeyW", { shiftKey: true });
  await page.reply();
  page.key("keyup", "KeyW", { target: page.get("#speed-slider") });
  assert.equal(page.requests.at(-1).direction, "stop");
  await page.reply();
});

test("Space on a focused button stops instead of activating that button", async () => {
  const page = await setup();
  assert.equal(page.key("keydown", "Space", { target: { tagName: "BUTTON" } }).prevented, true);
  assert.equal(page.requests[0].direction, "stop");
  await page.reply();
});

test("window blur and hidden tabs stop a held keyboard action once", async () => {
  for (const action of ["blur", "hide"]) {
    const page = await setup();
    page.key("keydown", "KeyW");
    await page.reply();
    page[action]();
    page[action]();
    assert.equal(page.requests.length, 2);
    assert.equal(page.requests[1].direction, "stop");
    await page.reply();
  }
});

test("mouse STOP works while a keyboard move is still in flight", async () => {
  const page = await setup();
  page.key("keydown", "KeyW");
  page.click("stop");
  await page.reply();
  assert.equal(page.requests.at(-1).direction, "stop");
  await page.reply();
  page.key("keyup", "KeyW");
  assert.equal(page.requests.length, 2);
});

test("mouse direction takes over from a held key", async () => {
  const page = await setup();
  page.key("keydown", "KeyW");
  await page.reply();
  page.click("left");
  await page.reply();
  page.key("keyup", "KeyW");
  assert.equal(page.requests.length, 2);
  assert.equal(page.get("#direction").textContent, "Left");
});

test("network failure drops waiting movement and attempts STOP only once", async () => {
  const page = await setup();
  page.key("keydown", "KeyW");
  page.key("keydown", "KeyD");
  await page.reply(true);
  assert.deepEqual(page.requests.map((request) => request.direction), ["forward", "stop"]);
  await page.reply(true);
  assert.equal(page.requests.length, 2);
  assert.equal(page.get("#error-message").hidden, false);
  assert.equal(page.buttons.every((button) => !button.disabled), true);
  page.key("keyup", "KeyD");
  assert.equal(page.requests.length, 2);
  page.key("keydown", "KeyA");
  await page.reply();
  assert.equal(page.get("#direction").textContent, "Left");
});

test("confirmed movement sends heartbeats without repeating moves and stops renewing on release", async () => {
  const page = await setup();
  assert.equal(page.timerCount(500), 0);
  page.key("keydown", "KeyW");
  assert.equal(page.timerCount(500), 0);
  await page.reply();
  for (let i = 0; i < 3; i++) {
    await page.runTimer(500);
    assert.deepEqual(page.heartbeats.at(-1), { command_id: "command-1" });
    assert.equal(page.timerCount(500), 0, "Do not overlap heartbeat requests");
    await page.replyHeartbeat();
  }
  assert.equal(page.requests.length, 1);
  page.key("keyup", "KeyW");
  assert.equal(page.timerCount(500), 0, "Cancel renewal before STOP is acknowledged");
  await page.reply();
});

test("reading another page's movement never adopts its heartbeat token", async () => {
  const page = await setup({ direction: "forward", speed: 0.5, command_id: "other-page" });
  assert.equal(page.get("#direction").textContent, "Forward");
  await page.runTimer(1000);
  assert.equal(page.timerCount(500), 0);
  assert.equal(page.heartbeats.length, 0);
  page.click("left");
  await page.reply();
  await page.runTimer(500);
  assert.deepEqual(page.heartbeats[0], { command_id: "command-1" });
  await page.replyHeartbeat();
});

test("an expired heartbeat response stops renewal and held keys cannot resume", async () => {
  const page = await setup();
  page.key("keydown", "KeyW");
  await page.reply();
  await page.runTimer(500);
  await page.replyHeartbeat({ connected: true, direction: "stop", speed: 0, battery: 100,
    command_id: null, stop_reason: "timeout", watchdog_timeout_ms: 2000 });
  assert.equal(page.timerCount(500), 0);
  assert.equal(page.get("#direction").textContent, "Stop");
  assert.match(page.get("#safety-status").textContent, /Auto-stopped/);
  page.key("keydown", "KeyW", { repeat: true });
  page.key("keyup", "KeyW");
  assert.equal(page.requests.length, 1);
  page.key("keydown", "KeyW");
  await page.reply();
  assert.equal(page.timerCount(500), 1);
});

test("heartbeat failure attempts STOP once and reconnecting only refreshes status", async () => {
  const page = await setup();
  page.click("forward");
  await page.reply();
  await page.runTimer(500);
  await page.replyHeartbeat(undefined, true);
  assert.equal(page.requests.at(-1).direction, "stop");
  assert.equal(page.timerCount(500), 0);
  await page.reply(true);
  page.setServerStatus({ direction: "stop", speed: 0, command_id: null, stop_reason: "timeout" });
  await page.runTimer(1000);
  assert.equal(page.requests.length, 2);
  assert.equal(page.get("#direction").textContent, "Stop");
  assert.equal(page.timerCount(500), 0);
});

test("a late heartbeat success or failure cannot overwrite STOP or a newer move", async () => {
  for (const next of ["stop", "left"]) {
    for (const fail of [false, true]) {
      const page = await setup();
      page.click("forward");
      await page.reply();
      await page.runTimer(500);
      page.click(next);
      await page.reply();
      await page.replyHeartbeat({ connected: true, direction: "forward", speed: 0.5,
        battery: 100, command_id: "command-1", stop_reason: null, watchdog_timeout_ms: 2000 }, fail);
      assert.equal(page.requests.length, 2);
      assert.equal(page.get("#direction").textContent, next === "stop" ? "Stop" : "Left");
      assert.equal(page.timerCount(500), next === "stop" ? 0 : 1);
    }
  }
});

test("a poll that began before movement cannot cancel the new movement", async () => {
  const page = await setup();
  page.deferStatus();
  await page.runTimer(1000);
  page.click("forward");
  await page.reply();
  await page.replyStatus({ connected: true, direction: "stop", speed: 0, battery: 100,
    command_id: null, stop_reason: "manual", watchdog_timeout_ms: 2000 });
  assert.equal(page.get("#direction").textContent, "Forward");
  assert.equal(page.timerCount(500), 1);
});

test("polling skips an outstanding move so an old stop cannot cancel its later success", async () => {
  const page = await setup();
  page.click("forward");
  await page.runTimer(1000);
  await page.reply();
  assert.equal(page.get("#direction").textContent, "Forward");
  assert.equal(page.timerCount(500), 1);
});

test("polling notices timeout or another controller and never renews that movement", async () => {
  for (const command_id of [null, "other-controller"]) {
    const page = await setup();
    page.click("forward");
    await page.reply();
    page.setServerStatus({ command_id, direction: command_id ? "left" : "stop", speed: command_id ? 0.3 : 0,
      stop_reason: command_id ? null : "timeout" });
    await page.runTimer(1000);
    assert.equal(page.timerCount(500), 0);
    assert.equal(page.get("#direction").textContent, command_id ? "Left" : "Stop");
    assert.equal(page.requests.length, 1);
  }
});

test("status read failure during movement also cancels heartbeats and attempts STOP", async () => {
  const page = await setup();
  page.click("forward");
  await page.reply();
  page.deferStatus();
  await page.runTimer(1000);
  await page.replyStatus(undefined, true);
  assert.equal(page.timerCount(500), 0);
  assert.equal(page.requests.at(-1).direction, "stop");
  await page.reply();
});

test("blur and hidden tabs stop mouse movement, including a late move response", async () => {
  for (const event of ["blur", "hide"]) {
    for (const slow of [false, true]) {
      const page = await setup();
      page.click("forward");
      if (!slow) await page.reply();
      page[event]();
      page[event]();
      assert.equal(page.timerCount(500), 0);
      if (slow) await page.reply();
      assert.deepEqual(page.requests.map((request) => request.direction), ["forward", "stop"]);
      await page.reply();
      assert.equal(page.timerCount(500), 0);
      assert.equal(page.get("#direction").textContent, "Stop");
      page.show();
      await tick();
      assert.equal(page.requests.length, 2);
    }
  }
});

test("page exit beacons STOP and late replies or page restoration do not restart renewal", async () => {
  for (const slow of [false, true]) {
    const page = await setup();
    page.click("forward");
    if (!slow) await page.reply();
    page.pagehide();
    assert.equal(page.beacons.length, 1);
    assert.equal(page.beacons[0].path, "/api/move");
    assert.deepEqual(JSON.parse(await page.beacons[0].body.text()), { direction: "stop", speed: 0 });
    assert.equal(page.beacons[0].body.type, "application/json");
    if (slow) await page.reply();
    assert.equal(page.timerCount(500), 0);
    assert.equal(page.timerCount(1000), 0);
    page.pageshow();
    await tick();
    assert.equal(page.timerCount(1000), 1);
    assert.equal(page.timerCount(500), 0);
    assert.equal(page.requests.length, 1);
  }
});

test("touch and pen hold each direction at selected speed, then stop even outside the button", async () => {
  for (const pointerType of ["touch", "pen"]) {
    const page = await setup();
    page.get("#speed-slider").value = "30";
    for (const direction of ["forward", "backward", "left", "right"]) {
      const button = page.buttons.find((button) => button.dataset.direction === direction);
      assert.equal(page.pointer("pointerdown", direction, { pointerType }).prevented, true);
      assert.deepEqual(page.requests.at(-1), { direction, speed: 0.3 });
      assert.equal(button.disabled, false, "The held button stays enabled during a slow move");
      assert.equal(button.hasPointerCapture(1), true);
      assert.equal(button.classes.has("touch-active"), true);
      await page.reply();
      await page.runTimer(500);
      await page.replyHeartbeat();
      page.pointer("pointerup", null, { pointerType });
      assert.equal(button.hasPointerCapture(1), false);
      assert.equal(button.classes.has("touch-active"), false);
      assert.equal(page.timerCount(500), 0);
      assert.deepEqual(page.requests.at(-1), { direction: "stop", speed: 0 });
      await page.reply();
      const count = page.requests.length;
      for (const clickType of [pointerType, undefined]) {
        assert.equal(page.click(direction, { pointerType: clickType }).prevented, true);
      }
      assert.equal(page.requests.length, count, "Touch-generated clicks never restart movement");
    }
  }
});

test("a quick touch release queues STOP and a late movement response never starts heartbeats", async () => {
  const page = await setup();
  page.pointer("pointerdown", "forward");
  page.pointer("pointerup", "forward");
  page.click("forward", { pointerType: "touch" });
  assert.equal(page.requests.length, 1);
  await page.reply();
  assert.deepEqual(page.requests.map((request) => request.direction), ["forward", "stop"]);
  assert.equal(page.timerCount(500), 0);
  await page.reply();
});

test("pointer cancellation or lost capture stops only once and a later mouse click still works", async () => {
  for (const ending of ["pointercancel", "lostpointercapture"]) {
    const page = await setup();
    page.pointer("pointerdown", "forward");
    await page.reply();
    page.pointer(ending, "forward");
    page.pointer("pointerup", "forward");
    page.pointer("lostpointercapture", "forward");
    assert.deepEqual(page.requests.map((request) => request.direction), ["forward", "stop"]);
    assert.equal(page.timerCount(500), 0);
    await page.reply();
    page.pointer("pointerdown", "forward", { pointerType: "mouse" });
    page.pointer("pointerup", "forward", { pointerType: "mouse" });
    assert.equal(page.requests.length, 2, "Mouse movement still begins on click");
    page.click("forward");
    await page.reply();
    assert.equal(page.requests.at(-1).direction, "forward");
    assert.equal(page.timerCount(500), 1);
  }
});

test("extra fingers cannot change direction or click to move, but any finger can press STOP", async () => {
  const page = await setup();
  page.pointer("pointerdown", "forward");
  await page.reply();
  page.pointer("pointerdown", "left", { pointerId: 2, isPrimary: false });
  page.pointer("pointerup", "left", { pointerId: 2, isPrimary: false });
  page.click("left", { pointerType: undefined });
  assert.equal(page.requests.length, 1);
  assert.equal(page.timerCount(500), 1);
  page.pointer("pointerdown", "stop", { pointerId: 3, isPrimary: false });
  assert.equal(page.requests.at(-1).direction, "stop");
  assert.equal(page.timerCount(500), 0);
  await page.reply();
  page.pointer("pointerup", "stop", { pointerId: 3, isPrimary: false });
  page.pointer("pointerup", "forward");
  page.click("stop", { pointerType: "touch" });
  page.click("forward", { pointerType: undefined });
  assert.equal(page.requests.length, 2);
});

test("keyboard and touch can take over without releases from the old input stopping the new one", async () => {
  const page = await setup();
  page.key("keydown", "KeyW");
  await page.reply();
  page.pointer("pointerdown", "right");
  await page.reply();
  page.key("keyup", "KeyW");
  assert.equal(page.requests.length, 2);
  page.key("keydown", "KeyA");
  await page.reply();
  page.pointer("pointerup", "right");
  page.click("right", { pointerType: undefined });
  assert.equal(page.requests.length, 3);
  assert.equal(page.get("#direction").textContent, "Left");
  page.key("keyup", "KeyA");
  await page.reply();
  assert.equal(page.requests.at(-1).direction, "stop");
});

test("Space stops touch movement and blocks fresh touch presses until released", async () => {
  const page = await setup();
  page.pointer("pointerdown", "forward");
  await page.reply();
  page.key("keydown", "Space");
  await page.reply();
  page.pointer("pointerup", "forward");
  page.pointer("pointerdown", "left");
  page.pointer("pointerup", "left");
  page.click("left", { pointerType: undefined });
  assert.equal(page.requests.length, 2);
  page.key("keyup", "Space");
  page.pointer("pointerdown", "left");
  await page.reply();
  assert.equal(page.requests.at(-1).direction, "left");
});

test("request failures, timeout and another controller discard touch ownership", async () => {
  for (const cause of ["move", "heartbeat", "status", "timeout", "takeover"]) {
    const page = await setup();
    page.pointer("pointerdown", "forward");
    await page.reply(cause === "move");
    if (cause === "heartbeat") {
      await page.runTimer(500);
      await page.replyHeartbeat(undefined, true);
    } else if (cause === "status") {
      page.deferStatus();
      await page.runTimer(1000);
      await page.replyStatus(undefined, true);
    } else if (cause === "timeout" || cause === "takeover") {
      page.setServerStatus({ command_id: cause === "timeout" ? null : "another-controller",
        direction: cause === "timeout" ? "stop" : "left", speed: cause === "timeout" ? 0 : 0.3,
        stop_reason: cause === "timeout" ? "timeout" : null });
      await page.runTimer(1000);
    }
    assert.equal(page.buttons.some((button) => button.classes.has("touch-active")), false,
      "Clear the held appearance before waiting for the fallback STOP");
    if (["move", "heartbeat", "status"].includes(cause)) await page.reply();
    const count = page.requests.length;
    page.pointer("pointerup", "forward");
    page.click("forward", { pointerType: undefined });
    assert.equal(page.requests.length, count, "An old finger cannot stop another controller or restart movement");
    assert.equal(page.timerCount(500), 0);
    assert.equal(page.buttons.some((button) => button.hasPointerCapture(1)), false);
    assert.equal(page.buttons.some((button) => button.classes.has("touch-active")), false);
  }
});

test("blur, hiding and leaving clear touch capture before late releases or responses", async () => {
  for (const event of ["blur", "hide", "pagehide"]) {
    for (const slow of [false, true]) {
      const page = await setup();
      page.pointer("pointerdown", "forward");
      if (!slow) await page.reply();
      page[event]();
      page.pointer("pointerup", "forward");
      page.click("forward", { pointerType: undefined });
      if (slow) await page.reply();
      assert.equal(page.buttons.some((button) => button.hasPointerCapture(1)), false);
      assert.equal(page.timerCount(500), 0);
      if (event === "pagehide") {
        assert.equal(page.beacons.length, 1);
        assert.equal(page.requests.length, 1);
      } else {
        assert.deepEqual(page.requests.map((request) => request.direction), ["forward", "stop"]);
        await page.reply();
      }
    }
  }
});

test("capture failure leaves an existing keyboard action owned by its key", async () => {
  const page = await setup();
  page.key("keydown", "KeyW");
  await page.reply();
  page.buttons.find((button) => button.dataset.direction === "left").captureFails = true;
  page.pointer("pointerdown", "left");
  page.click("left", { pointerType: undefined });
  assert.equal(page.requests.length, 1);
  page.key("keyup", "KeyW");
  assert.equal(page.requests.at(-1).direction, "stop");
  await page.reply();
});

test("keyboard and assistive clicks remain available after a cancelled touch", async () => {
  const page = await setup();
  page.pointer("pointerdown", "left");
  await page.reply();
  page.pointer("pointercancel", "left");
  await page.reply();
  page.click("left", { detail: 0, pointerType: undefined });
  await page.reply();
  assert.equal(page.requests.at(-1).direction, "left");
});

test("the older-browser timeout fallback also aborts a stalled response body", async () => {
  const page = await setup({}, { legacyTimeout: true });
  page.pointer("pointerdown", "forward");
  const signal = page.requestSignals.find((request) => request.path === "/api/move").signal;
  await page.replyHeaders();
  assert.equal(signal.aborted, false);
  await page.runTimer(5000); // 初始 status 的计时器。
  await page.runTimer(5000); // 已收到 headers、仍在读取正文的移动请求。
  assert.equal(signal.aborted, true);
  assert.deepEqual(page.requests.map((request) => request.direction), ["forward", "stop"]);
  assert.equal(page.timerCount(500), 0);
  await page.reply();
});

test("mock mode remains explicit and preserves its full controls and default speed", async () => {
  const page = await setup();
  assert.equal(page.get("#motor-mode").textContent, "Mock");
  assert.equal(page.get("#speed-slider").max, "100");
  assert.equal(page.get("#speed-slider").value, "50");
  assert.equal(page.get("#battery").textContent, "100%");
  assert.equal(page.buttons.every((button) => !button.disabled), true);
  page.click("left");
  assert.equal(page.moveBodies[0].control_epoch, "epoch-0");
  await page.reply();
});

test("unknown capabilities never enable movement but an initial read failure still allows STOP", async () => {
  const page = await setup({}, { deferInitialStatus: true });
  assert.equal(page.buttons.every((button) => button.disabled), true);
  page.key("keydown", "KeyW");
  assert.equal(page.requests.length, 0);
  await page.replyStatus(undefined, true);
  assert.equal(page.buttons.find((button) => button.dataset.direction === "stop").disabled, false);
  assert.equal(page.buttons.filter((button) => button.dataset.direction !== "stop").every((button) => button.disabled), true);
  page.key("keydown", "KeyW");
  page.pointer("pointerdown", "forward");
  assert.equal(page.requests.length, 0);
  page.click("stop");
  assert.deepEqual(page.moveBodies[0], { direction: "stop", speed: 0 });
  await page.reply();
});

for (const motorMode of ["tb6612", "drv8833"]) {
  const benchTest = (description, handler) => test(`${motorMode}: ${description}`, handler);
  const benchStatus = {
    motor_mode: motorMode, supported_directions: ["forward", "backward", "stop"],
    max_speed: 0.4, battery: null, control_epoch: "bench-start",
  };

  benchTest("the single motor bench starts at 20 percent PWM and polls preserve the user's selection", async () => {
    const page = await setup(benchStatus);
    assert.equal(page.get("#motor-mode").textContent, `${motorMode.toUpperCase()} · Single motor bench`);
    assert.equal(page.get("#speed-slider").max, "40");
    assert.equal(page.get("#speed-slider").value, "20");
    assert.equal(page.get("#maximum-speed").textContent, "40%");
    assert.equal(page.get("#selected-speed").textContent, "20%");
    assert.equal(page.get("#speed-label").textContent, "PWM output");
    assert.equal(page.get("#current-speed-label").textContent, "PWM command");
    assert.equal(page.get("#battery").textContent, "Not measured");
    assert.equal(page.get("#direction").textContent, "Output off");
    assert.match(page.get("#motor-help").textContent, /STOP.*0\.5 s/);
    assert.match(page.get("#controller-footer").textContent, /No rotation feedback/);
    page.get("#speed-slider").value = "30";
    await page.runTimer(1000);
    assert.equal(page.get("#speed-slider").value, "30");
    assert.equal(page.get("#selected-speed").textContent, "30%");
    page.get("#speed-slider").value = "90"; // 即使输入值被外部改写，请求也不越过能力上限。
    page.key("keydown", "KeyW");
    assert.deepEqual(page.requests[0], { direction: "forward", speed: 0.4 });
    assert.equal(page.moveBodies[0].control_epoch, "bench-start");
    await page.reply();
    page.key("keyup", "KeyW");
    await page.reply();
  });

  benchTest("unsupported bench directions are blocked for keyboard, touch, mouse and assistive clicks", async () => {
    const page = await setup(benchStatus);
    for (const direction of ["left", "right"]) {
      assert.equal(page.buttons.find((button) => button.dataset.direction === direction).disabled, true);
      page.pointer("pointerdown", direction);
      page.pointer("pointerup", direction);
      page.click(direction);
      page.click(direction, { detail: 0, pointerType: undefined });
    }
    for (const key of ["KeyA", "KeyD", "ArrowLeft", "ArrowRight"]) {
      page.key("keydown", key);
      page.key("keyup", key);
    }
    assert.equal(page.requests.length, 0);
    assert.equal(page.buttons.some((button) => button.hasPointerCapture(1)), false);
    page.key("keydown", "KeyW");
    await page.reply();
    page.key("keydown", "KeyA");
    page.key("keyup", "KeyA");
    assert.equal(page.requests.length, 1);
    page.key("keyup", "KeyW");
    assert.equal(page.requests.at(-1).direction, "stop");
    await page.reply();
  });

  benchTest("a bench without a current control epoch permits STOP but no direction request", async () => {
    const page = await setup({ ...benchStatus, control_epoch: null });
    page.key("keydown", "KeyW");
    page.pointer("pointerdown", "forward");
    assert.equal(page.requests.length, 0);
    page.click("stop");
    await page.reply();
    page.pointer("pointerdown", "forward");
    assert.equal(page.moveBodies.at(-1).control_epoch, "epoch-1");
    await page.reply();
  });

  benchTest("fault status displays unknown output and locks movement while keeping STOP retryable", async () => {
    const fault = "GPIO write failed; output state is unknown.";
    const page = await setup({ ...benchStatus, fault, connected: false, direction: "unknown", speed: null });
    assert.equal(page.get("#direction").textContent, "Unknown");
    assert.equal(page.get("#current-speed").textContent, "Unknown");
    assert.equal(page.get("#battery").textContent, "Not measured");
    assert.match(page.get("#error-message").textContent, /Motor fault.*cut motor power and restart service/);
    assert.equal(page.get("#error-message").hidden, false);
    assert.equal(page.get("#connection").textContent, "● Disconnected");
    assert.equal(page.get("#speed-slider").disabled, true);
    page.key("keydown", "KeyW");
    page.pointer("pointerdown", "forward");
    page.click("backward", { detail: 0 });
    assert.equal(page.requests.length, 0);
    for (let i = 0; i < 2; i++) {
      assert.equal(page.buttons.find((button) => button.dataset.direction === "stop").disabled, false);
      page.click("stop");
      await page.reply();
      assert.equal(page.buttons.filter((button) => button.dataset.direction !== "stop").every((button) => button.disabled), true);
      assert.match(page.get("#error-message").textContent, /Motor fault/);
    }
    assert.equal(page.timerCount(500), 0);
  });

  benchTest("heartbeat fault releases a held touch and a server restart never resumes that old gesture", async () => {
    const page = await setup(benchStatus);
    page.pointer("pointerdown", "forward");
    await page.reply();
    await page.runTimer(500);
    await page.replyHeartbeat({ ...benchStatus, connected: false, fault: "Motor I/O failed",
      direction: "unknown", speed: null, command_id: null, control_epoch: "fault-epoch", watchdog_timeout_ms: 2000 });
    assert.equal(page.timerCount(500), 0);
    assert.equal(page.buttons.some((button) => button.hasPointerCapture(1)), false);
    page.pointer("pointerup", "forward");
    page.click("forward", { pointerType: "touch" });
    assert.equal(page.requests.length, 1);
    page.setServerStatus({ connected: true, fault: null, direction: "stop", speed: 0,
      command_id: null, control_epoch: "restart-epoch" });
    await page.runTimer(1000);
    assert.equal(page.requests.length, 1);
    assert.equal(page.timerCount(500), 0);
    page.pointer("pointerdown", "forward", { pointerId: 2 });
    assert.equal(page.moveBodies.at(-1).control_epoch, "restart-epoch");
    await page.reply();
  });

  benchTest("HTTP 503 locks bench movement immediately, drops queued moves and attempts STOP once", async () => {
    const page = await setup(benchStatus);
    page.key("keydown", "KeyW");
    page.key("keydown", "KeyS");
    await page.replyHttpError(503, "Motor driver failed");
    assert.deepEqual(page.requests.map((request) => request.direction), ["forward", "stop"]);
    assert.equal(page.buttons.filter((button) => button.dataset.direction !== "stop").every((button) => button.disabled), true);
    assert.match(page.get("#error-message").textContent, /Motor fault.*Motor driver failed/);
    await page.reply(false, { fault: "Motor driver failed", connected: false });
    page.key("keyup", "KeyS");
    page.key("keydown", "KeyS");
    assert.equal(page.requests.length, 2);
    assert.equal(page.timerCount(500), 0);
    page.click("stop");
    await page.reply(false, { fault: "Motor driver failed", connected: false });
    assert.equal(page.requests.length, 3);
  });

  benchTest("a reversal rejection preserves the server detail after safe STOP and never retries movement", async () => {
    const page = await setup(benchStatus);
    page.click("forward");
    await page.reply();
    page.key("keydown", "KeyS");
    const detail = "Press STOP and wait at least 0.5 seconds before reversing.";
    await page.replyHttpError(409, detail);
    assert.deepEqual(page.requests.map((request) => request.direction), ["forward", "backward", "stop"]);
    await page.reply();
    assert.equal(page.get("#error-message").textContent, detail);
    assert.equal(page.get("#error-message").hidden, false);
    await page.runTimer(1000);
    assert.equal(page.get("#error-message").textContent, detail);
    page.key("keydown", "KeyS", { repeat: true });
    page.key("keyup", "KeyS");
    assert.equal(page.requests.length, 3);
    assert.equal(page.timerCount(500), 0);
    page.key("keydown", "KeyS");
    assert.equal(page.moveBodies.at(-1).control_epoch, "epoch-1");
    await page.reply();
    assert.equal(page.get("#error-message").hidden, true);
  });

  benchTest("a stale STOP response still supplies the epoch for a fresh direction queued behind it", async () => {
    const page = await setup(benchStatus);
    page.key("keydown", "KeyW");
    page.key("keyup", "KeyW");
    page.key("keydown", "KeyW");
    await page.reply();
    assert.equal(page.moveBodies[1].direction, "stop");
    assert.equal(page.moveBodies[1].control_epoch, "bench-start");
    await page.reply(false, { control_epoch: "after-stop" });
    assert.equal(page.moveBodies[2].direction, "forward");
    assert.equal(page.moveBodies[2].control_epoch, "after-stop");
    await page.reply();
    assert.equal(page.timerCount(500), 1);
  });

  benchTest("late poll and heartbeat replies cannot replace the epoch acknowledged by STOP", async () => {
    for (const source of ["poll", "heartbeat"]) {
      const page = await setup(benchStatus);
      if (source === "poll") {
        page.deferStatus();
        await page.runTimer(1000);
      }
      page.click("forward");
      await page.reply();
      if (source === "heartbeat") await page.runTimer(500);
      page.click("stop");
      await page.reply(false, { control_epoch: "new-stop-epoch" });
      const oldStatus = { ...benchStatus, connected: true, direction: "forward", speed: 0.2,
        command_id: "command-1", fault: null, watchdog_timeout_ms: 2000 };
      if (source === "poll") await page.replyStatus(oldStatus);
      else await page.replyHeartbeat(oldStatus);
      page.click("forward");
      assert.equal(page.moveBodies.at(-1).control_epoch, "new-stop-epoch");
      await page.reply();
    }
  });

  benchTest("a fault in a superseded STOP reply cancels the direction waiting behind it", async () => {
    const page = await setup(benchStatus);
    page.key("keydown", "KeyW");
    await page.reply();
    page.key("keyup", "KeyW");
    page.key("keydown", "KeyS");
    await page.reply(false, { fault: "Stop output not confirmed", connected: false,
      direction: "unknown", speed: null, control_epoch: "fault-stop" });
    assert.deepEqual(page.requests.map((request) => request.direction), ["forward", "stop"]);
    assert.equal(page.timerCount(500), 0);
    assert.match(page.get("#error-message").textContent, /cut motor power and restart service/);
    page.click("stop");
    assert.equal(page.moveBodies.at(-1).control_epoch, "fault-stop");
    await page.reply();
  });

  benchTest("a controller change resets the output to 20 percent and shows the new model", async () => {
    const page = await setup(benchStatus);
    page.get("#speed-slider").value = "40";
    const otherMode = motorMode === "tb6612" ? "drv8833" : "tb6612";
    page.setServerStatus({ motor_mode: otherMode, control_epoch: "new-controller" });
    await page.runTimer(1000);
    assert.equal(page.get("#motor-mode").textContent, `${otherMode.toUpperCase()} · Single motor bench`);
    assert.equal(page.get("#speed-slider").value, "20");
    assert.equal(page.get("#speed-slider").max, "40");
    assert.equal(page.get("#direction").textContent, "Output off");
    assert.equal(page.requests.length, 0);
    page.click("forward");
    assert.deepEqual(page.moveBodies[0], { direction: "forward", speed: 0.2, control_epoch: "new-controller" });
    await page.reply();
  });

  benchTest("reverse and a heartbeat timeout describe commands without claiming shaft feedback", async () => {
    const page = await setup({ ...benchStatus, direction: "backward", speed: 0.2 });
    assert.equal(page.get("#direction").textContent, "Reverse");
    page.setServerStatus({ direction: "stop", speed: 0, stop_reason: "timeout" });
    await page.runTimer(1000);
    assert.equal(page.get("#direction").textContent, "Output off");
    assert.match(page.get("#safety-status").textContent, /Output disabled: heartbeat lost/);
    assert.equal(page.requests.length, 0);
    assert.equal(page.timerCount(500), 0);
  });
}
