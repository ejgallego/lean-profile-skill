// AI-generated reusable evidence viewer. Trace transfer requires a user click.
"use strict";
const $ = (id) => document.getElementById(id);
function filter() {
  if (!$("filter")) return;
  const q = $("filter").value.toLowerCase();
  const decision = $("decision-filter")?.value || "all";
  let count = 0;
  for (const card of document.querySelectorAll(".comparison")) {
    card.hidden =
      !card.textContent.toLowerCase().includes(q) ||
      (decision !== "all" && card.dataset.decision !== decision);
    if (!card.hidden) count++;
  }
  $("count").textContent = `${count} comparisons`;
}
$("filter")?.addEventListener("input", filter);
$("decision-filter")?.addEventListener("change", filter);
filter();
for (const button of document.querySelectorAll("[data-viewer]"))
  button.addEventListener("click", () => {
    const frame = $(button.dataset.viewer);
    if (!frame.hasAttribute("src")) frame.src = frame.dataset.source;
    frame.hidden = !frame.hidden;
    button.setAttribute("aria-expanded", String(!frame.hidden));
    button.textContent = frame.hidden
      ? "Show interactive profile"
      : "Hide interactive profile";
  });
let toastTimer;
function toast(msg, timeout = 8000) {
  clearTimeout(toastTimer);
  $("toast").textContent = msg;
  $("toast").hidden = false;
  if (timeout)
    toastTimer = setTimeout(() => ($("toast").hidden = true), timeout);
}
async function openPerfetto(button) {
  // Open synchronously within the user's click so browser popup blockers can permit it.
  const origin = "https://ui.perfetto.dev";
  const win = window.open(origin, "_blank");
  if (!win) {
    toast(
      "The browser blocked the Perfetto tab. Allow popups or download the trace and open it in ui.perfetto.dev.",
    );
    return;
  }
  button.disabled = true;
  toast("Opening Perfetto… Waiting for its UI to be ready.", 0);
  const controller = new AbortController();
  let interval, timer, listener;
  let fail;
  const failure = new Promise((_, reject) => {
    fail = reject;
  });
  const ready = new Promise((resolve) => {
    listener = (e) => {
      if (e.source === win && e.origin === origin && e.data === "PONG")
        resolve();
    };
    window.addEventListener("message", listener);
  });
  // These guards cover the entire operation, including a body stalled after PONG.
  try {
    interval = setInterval(() => {
      if (win.closed) {
        fail(new Error("Perfetto tab was closed."));
        return;
      }
      win.postMessage("PING", origin);
    }, 150);
    timer = setTimeout(
      () =>
        fail(
          new Error(
            "Opening the trace in Perfetto timed out. Download the trace and use Open trace file in ui.perfetto.dev.",
          ),
        ),
      45000,
    );
    const [buffer] = await Promise.race([
      Promise.all([
        fetch(button.dataset.perfetto, { signal: controller.signal }).then(
          (r) => {
            if (!r.ok) throw new Error(`Trace request failed (${r.status}).`);
            return r.arrayBuffer();
          },
        ),
        ready,
      ]),
      failure,
    ]);
    if (win.closed) throw new Error("Perfetto tab was closed.");
    win.postMessage(
      {
        perfetto: {
          buffer,
          title: button.dataset.title,
          fileName: button.dataset.perfetto.split("/").pop(),
          localOnly: true,
        },
      },
      origin,
      [buffer],
    );
    toast("Trace sent to the Perfetto tab for local viewing.");
  } catch (err) {
    controller.abort();
    toast(err.message, 14000);
  } finally {
    clearInterval(interval);
    clearTimeout(timer);
    window.removeEventListener("message", listener);
    button.disabled = false;
  }
}
for (const button of document.querySelectorAll("[data-perfetto]"))
  button.addEventListener("click", () => openPerfetto(button));
