// 用可控的 HTTP 替身测试按键行为和慢请求，不启动服务器或摄像头。
const assert = require("node:assert/strict");
const { test } = require("node:test");
const { readFileSync } = require("node:fs");
const { join } = require("node:path");
const vm = require("node:vm");

const tick = () => new Promise((resolve) => setImmediate(resolve));

async function setup(statusOverrides = {}) {
  function element(tagName = "DIV") {
    return {
      tagName, value: "50", disabled: false, hidden: true, textContent: "", dataset: {},
      classes: new Set(), listeners: {},
      addEventListener(name, handler) { this.listeners[name] = handler; },
      classList: { toggle() {} },
    };
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
  const waiting = [];
  const initialStatus = { connected: true, direction: "stop", speed: 0, battery: 100,
    command_id: null, stop_reason: null, watchdog_timeout_ms: 2000, ...statusOverrides };
  let serverStatus = initialStatus;
  let commandCount = 0;
  const heartbeats = [];
  const waitingHeartbeats = [];
  const waitingStatus = [];
  const beacons = [];
  const timers = new Map();
  let nextTimer = 0;
  let deferStatus = false;
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
    AbortSignal, URL, Blob,
    setTimeout(handler, delay) { timers.set(++nextTimer, { handler, delay }); return nextTimer; },
    clearTimeout(id) { timers.delete(id); },
    fetch(path, options) {
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
      requests.push(command);
      return new Promise((resolve, reject) => waiting.push({ resolve, reject, command }));
    },
  });
  vm.runInContext(readFileSync(join(__dirname, "../web/app.js"), "utf8"), context);
  await tick();

  return {
    get, buttons, requests, heartbeats, beacons,
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
    click(direction) { buttons.find((button) => button.dataset.direction === direction).listeners.click(); },
    async reply(fail = false) {
      const request = waiting.shift();
      assert.ok(request, "Expected an outstanding move request");
      if (fail) request.reject(new Error("Test network failure"));
      else {
        serverStatus = { ...initialStatus, ...request.command,
          command_id: request.command.direction === "stop" ? null : `command-${++commandCount}`,
          stop_reason: request.command.direction === "stop" ? "manual" : null };
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
