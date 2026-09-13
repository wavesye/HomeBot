// 用可控的 HTTP 替身测试按键行为和慢请求，不启动服务器或摄像头。
const assert = require("node:assert/strict");
const { test } = require("node:test");
const { readFileSync } = require("node:fs");
const { join } = require("node:path");
const vm = require("node:vm");

const tick = () => new Promise((resolve) => setImmediate(resolve));

async function setup() {
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
  const initialStatus = { connected: true, direction: "stop", speed: 0, battery: 100 };
  const document = {
    hidden: false,
    querySelector: get,
    querySelectorAll: () => buttons,
    addEventListener(name, handler) { (listeners[name] ||= []).push(handler); },
  };
  const context = vm.createContext({
    document,
    window: { addEventListener(name, handler) { windowListeners[name] = handler; } },
    AbortSignal, setTimeout, clearTimeout, URL,
    fetch(path, options) {
      if (path === "/api/status") return Promise.resolve({ ok: true, json: async () => initialStatus });
      assert.equal(path, "/api/move");
      const command = JSON.parse(options.body);
      requests.push(command);
      return new Promise((resolve, reject) => waiting.push({ resolve, reject, command }));
    },
  });
  vm.runInContext(readFileSync(join(__dirname, "../web/app.js"), "utf8"), context);
  await tick();

  return {
    get, buttons, requests,
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
      else request.resolve({ ok: true, json: async () => ({ ...initialStatus, ...request.command }) });
      await tick();
    },
    blur() { windowListeners.blur(); },
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
