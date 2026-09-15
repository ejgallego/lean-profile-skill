// AI-generated deterministic Perfetto handoff tests: no network or timer waits.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const source = fs.readFileSync(
  path.join(__dirname, "../assets/review.js"),
  "utf8",
);
const origin = "https://ui.perfetto.dev";

test("decision and case-insensitive text filters compose without changing evidence", () => {
  const handlers = {};
  const elements = Object.fromEntries(["filter", "decision-filter", "count"].map(id => [id, {
    value: id === "decision-filter" ? "all" : "",
    addEventListener: (event, fn) => { handlers[`${id}/${event}`] = fn; },
  }]));
  const cards = [
    { textContent: "Cache experiment", dataset: { decision: "accepted" } },
    { textContent: "Cache experiment; valid samples", dataset: { decision: "rejected" } },
    { textContent: "Native experiment", dataset: { decision: "inconclusive" } },
    { textContent: "Native experiment", dataset: { decision: "unclassified" } },
  ];
  vm.runInNewContext(source, { document: {
    getElementById: id => elements[id],
    querySelectorAll: selector => selector === ".comparison" ? cards : [],
  }});
  assert.equal(elements.count.textContent, "4 comparisons");
  elements["decision-filter"].value = "rejected";
  handlers["decision-filter/change"]();
  assert.deepEqual(cards.map(c => c.hidden), [true, false, true, true]);
  elements.filter.value = "NATIVE";
  handlers["filter/input"]();
  assert.equal(elements.count.textContent, "0 comparisons");
  elements["decision-filter"].value = "unclassified";
  handlers["decision-filter/change"]();
  assert.deepEqual(cards.map(c => c.hidden), [true, true, true, false]);
  elements.filter.value = "";
  elements["decision-filter"].value = "all";
  handlers["filter/input"]();
  assert.equal(elements.count.textContent, "4 comparisons");
});

function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}

test("group filters keep workload rows, their evidence and summary navigation together", () => {
  const handlers = {};
  const a = { textContent: "Edit", dataset: { decision: "accepted", context: "Cache layer" } };
  const b = { textContent: "No change", dataset: { decision: "accepted", context: "Cache layer" } };
  const c = { textContent: "Edit", dataset: { decision: "rejected", context: "Native layer" } };
  const groups = [[a, b], [c]].map(rows => ({ querySelectorAll: () => rows }));
  for (const [id, card] of Object.entries({ a, b, c })) card.id = id;
  const details = ["a", "b", "c"].map(id => ({ dataset: { for: id }, textContent: `command-${id}` }));
  details.push({ dataset: { for: "a" }, textContent: "profile-only-token" });
  const elements = { a, b, c, count: {}, filter: { value: "" }, "decision-filter": { value: "all" } };
  for (const id of ["filter", "decision-filter"])
    elements[id].addEventListener = (event, fn) => { handlers[id] = fn; };
  const anchor = { addEventListener: (event, fn) => { handlers.jump = fn; } };
  vm.runInNewContext(source, { document: {
    getElementById: id => elements[id],
    querySelectorAll: selector => ({
      ".comparison": [a, b, c], ".comparison-group": groups,
      ".comparison-evidence": details, 'a[href^="#"]': [anchor],
    })[selector] || [],
  }});
  elements.filter.value = "CACHE no change";
  handlers.filter();
  assert.equal(elements.count.textContent, "0 comparisons");
  elements.filter.value = "no change";
  handlers.filter();
  assert.deepEqual([a.hidden,b.hidden,c.hidden], [true,false,true]);
  assert.deepEqual(groups.map(g => g.hidden), [false,true]);
  assert.deepEqual(details.map(d => d.hidden), [true,false,true,true]);
  for (const token of ["COMMAND-a", "profile-only-token"]) {
    elements.filter.value = token;
    handlers.filter();
    assert.deepEqual([a.hidden,b.hidden,c.hidden], [false,true,true]);
    assert.deepEqual(details.map(d => d.hidden), [false,true,true,false]);
    assert.equal(elements.count.textContent, "1 comparisons");
  }
  elements["decision-filter"].value = "rejected";
  handlers["decision-filter"]();
  assert.equal(elements.count.textContent, "0 comparisons");
  handlers.jump();
  assert.equal(elements.count.textContent, "3 comparisons");
  assert.ok(groups.every(g => !g.hidden));
  assert.ok(details.every(d => !d.hidden));
});
async function flush() {
  for (let i = 0; i < 12; i++) await Promise.resolve();
}
function harness({ blocked = false } = {}) {
  const timers = new Map(),
    intervals = new Map(),
    listeners = new Map();
  const headers = deferred(),
    body = deferred();
  const toast = { hidden: true, textContent: "" };
  const messages = [],
    requests = [];
  let nextId = 0,
    settled = false;
  const win = {
    closed: false,
    postMessage(message, target, transfer) {
      messages.push({ message, target, transfer, closed: win.closed });
    },
  };
  const context = vm.createContext({
    AbortController,
    document: {
      getElementById: (id) => (id === "toast" ? toast : null),
      querySelectorAll: () => [],
    },
    window: {
      open: (url, target) => {
        assert.equal(url, origin);
        assert.equal(target, "_blank");
        return blocked ? null : win;
      },
      addEventListener: (type, fn) => listeners.set(type, fn),
      removeEventListener: (type, fn) => {
        assert.equal(listeners.get(type), fn);
        listeners.delete(type);
      },
    },
    setTimeout: (fn, delay) => {
      const id = ++nextId;
      timers.set(id, { fn, delay });
      return id;
    },
    clearTimeout: (id) => timers.delete(id),
    setInterval: (fn) => {
      const id = ++nextId;
      intervals.set(id, fn);
      return id;
    },
    clearInterval: (id) => intervals.delete(id),
    fetch: (url, options = {}) => {
      requests.push({ url, signal: options.signal });
      // Deliberately ignore abort: a late response must still never be transferred.
      return headers.promise;
    },
  });
  vm.runInContext(source, context);
  const button = {
    dataset: { perfetto: "trace.json", title: "Fixture" },
    disabled: false,
  };
  const run = context.openPerfetto(button).then(() => {
    settled = true;
  });
  const h = {
    win,
    toast,
    requests,
    messages,
    button,
    run,
    body,
    get settled() {
      return settled;
    },
    get transfers() {
      return messages.filter(({ message }) => message.perfetto);
    },
    pong(overrides = {}) {
      listeners.get("message")?.({
        source: win,
        origin,
        data: "PONG",
        ...overrides,
      });
    },
    respond(status = 200) {
      headers.resolve({
        ok: status === 200,
        status,
        arrayBuffer: () => body.promise,
      });
    },
    tick() {
      for (const fn of intervals.values()) fn();
    },
    deadline() {
      const deadline = [...timers.values()].find(
        ({ delay }) => delay === 45000,
      );
      assert.ok(deadline, "whole-operation deadline must remain active");
      deadline.fn();
    },
    assertClean() {
      assert.equal(settled, true);
      assert.equal(button.disabled, false);
      assert.equal(intervals.size, 0);
      assert.equal(listeners.size, 0);
      assert.equal(
        [...timers.values()].some(({ delay }) => delay === 45000),
        false,
      );
    },
    assertFailed(pattern) {
      h.assertClean();
      assert.equal(requests[0].signal.aborted, true);
      assert.equal(h.transfers.length, 0);
      assert.match(toast.textContent, pattern);
    },
  };
  return h;
}

for (const readyFirst of [false, true]) {
  test(`normal handshake, ${readyFirst ? "PONG" : "body"} first`, async () => {
    const h = harness();
    h.tick();
    assert.equal(h.messages[0].message, "PING");
    assert.equal(h.messages[0].target, origin);
    h.pong({ origin: "https://wrong.example" });
    h.pong({ source: {} });
    const buffer = new ArrayBuffer(8);
    if (readyFirst) h.pong();
    else {
      h.respond();
      h.body.resolve(buffer);
    }
    await flush();
    assert.equal(h.settled, false);
    assert.equal(h.transfers.length, 0);
    if (readyFirst) {
      h.respond();
      h.body.resolve(buffer);
    } else h.pong();
    await flush();
    h.assertClean();
    assert.equal(h.requests[0].signal.aborted, false);
    assert.equal(h.transfers.length, 1);
    const sent = h.transfers[0];
    assert.equal(sent.closed, false);
    assert.equal(sent.target, origin);
    assert.equal(sent.message.perfetto.buffer, buffer);
    assert.equal(sent.message.perfetto.title, "Fixture");
    assert.equal(sent.message.perfetto.fileName, "trace.json");
    assert.equal(sent.message.perfetto.localOnly, true);
    assert.equal(sent.transfer.length, 1);
    assert.equal(sent.transfer[0], buffer);
    assert.match(h.toast.textContent, /Trace sent/);
    await h.run;
  });
}

for (const failure of ["timeout", "close"]) {
  test(`PONG then stalled body: ${failure} aborts; late body cannot transfer`, async () => {
    const h = harness();
    h.respond();
    h.pong();
    await flush();
    assert.equal(h.settled, false);
    if (failure === "timeout") h.deadline();
    else {
      h.win.closed = true;
      h.tick();
    }
    await flush();
    h.assertFailed(failure === "timeout" ? /timed out/ : /was closed/);
    const status = h.toast.textContent;
    h.body.resolve(new ArrayBuffer(8));
    await flush();
    assert.equal(h.transfers.length, 0);
    assert.equal(h.toast.textContent, status);
    await h.run;
  });
}

test("closure immediately before transfer is caught without a polling tick", async () => {
  const h = harness();
  h.respond();
  h.pong();
  await flush();
  h.win.closed = true;
  h.body.resolve(new ArrayBuffer(8));
  await flush();
  h.assertFailed(/was closed/);
  await h.run;
});

test("deadline also bounds missing PONG and stalled response headers", async () => {
  const h = harness();
  h.deadline();
  await flush();
  h.assertFailed(/timed out/);
  await h.run;
});

for (const failure of ["HTTP", "body"]) {
  test(`${failure} failure aborts and releases controls`, async () => {
    const h = harness();
    h.respond(failure === "HTTP" ? 503 : 200);
    h.pong();
    await flush();
    if (failure === "body") h.body.reject(new Error("body failed"));
    await flush();
    h.assertFailed(
      failure === "HTTP" ? /Trace request failed \(503\)/ : /body failed/,
    );
    await h.run;
  });
}

test("blocked popup does not start a trace request", async () => {
  const h = harness({ blocked: true });
  await flush();
  h.assertClean();
  assert.equal(h.requests.length, 0);
  assert.match(h.toast.textContent, /blocked/);
  await h.run;
});
