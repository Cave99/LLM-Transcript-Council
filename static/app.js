function detailsStorageKey() {
  return `details:${location.pathname}`;
}

function detailsKey(details) {
  if (details.dataset.detailsKey) return details.dataset.detailsKey;
  const summary = details.querySelector("summary");
  return summary ? summary.textContent.trim() : "";
}

function restoreDetailsState() {
  const saved = JSON.parse(localStorage.getItem(detailsStorageKey()) || "{}");
  document.querySelectorAll("details").forEach((details) => {
    const key = detailsKey(details);
    if (!key) return;
    if (Object.prototype.hasOwnProperty.call(saved, key)) details.open = saved[key];
    details.addEventListener("toggle", () => {
      const current = JSON.parse(localStorage.getItem(detailsStorageKey()) || "{}");
      current[key] = details.open;
      localStorage.setItem(detailsStorageKey(), JSON.stringify(current));
    });
  });
}

function bindConfirmForms() {
  document.querySelectorAll("form[data-confirm-message]").forEach((form) => {
    form.addEventListener("submit", (event) => {
      const message = form.dataset.confirmMessage || "Are you sure?";
      if (!window.confirm(message)) {
        event.preventDefault();
      }
    });
  });
}

function bindProjectRename() {
  document.querySelectorAll("[data-project-rename-form='true']").forEach((form) => {
    const container = form.closest(".hero-copy");
    const toggle = container ? container.querySelector("[data-rename-toggle='true']") : null;
    const cancel = form.querySelector("[data-rename-cancel='true']");
    const input = form.querySelector("[data-rename-input='true']");
    if (!container || !toggle || !cancel || !input) return;

    const setEditing = (editing) => {
      form.hidden = !editing;
      container.classList.toggle("is-editing", editing);
      if (editing) {
        input.focus();
        input.select();
      } else {
        toggle.focus();
      }
    };

    toggle.addEventListener("click", () => setEditing(true));
    cancel.addEventListener("click", () => setEditing(false));
  });
}

function saveDetailsState() {
  const current = JSON.parse(localStorage.getItem(detailsStorageKey()) || "{}");
  document.querySelectorAll("details").forEach((details) => {
    const key = detailsKey(details);
    if (key) current[key] = details.open;
  });
  localStorage.setItem(detailsStorageKey(), JSON.stringify(current));
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", () => {
    restoreDetailsState();
    bindConfirmForms();
    bindProjectRename();
    bindAnalysisForms();
    bindNodeCanvas();
    bindGraphPreviewCanvas();
    bindDatasetSourceFields();
    bindReasoningFields();
    bindPreserveScrollLinks();
    bindLeaderboardViewLinks();
    restorePreservedScroll();
  });
} else {
  restoreDetailsState();
  bindConfirmForms();
  bindProjectRename();
  bindAnalysisForms();
  bindNodeCanvas();
  bindGraphPreviewCanvas();
  bindDatasetSourceFields();
  bindReasoningFields();
  bindPreserveScrollLinks();
  bindLeaderboardViewLinks();
  restorePreservedScroll();
}

window.addEventListener("beforeunload", saveAllCanvasViewports);

if ("scrollRestoration" in history) {
  history.scrollRestoration = "manual";
}

function preserveScrollKey(pathname = location.pathname) {
  return `scroll:${pathname}`;
}

function bindPreserveScrollLinks() {
  document.querySelectorAll("[data-preserve-scroll='true']").forEach((link) => {
    if (link.dataset.preserveScrollBound === "true") return;
    link.dataset.preserveScrollBound = "true";
    const save = () => savePreservedScroll(link);
    link.addEventListener("pointerdown", save);
    link.addEventListener("mousedown", save);
    link.addEventListener("touchstart", save, { passive: true });
    link.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") save();
    });
    link.addEventListener("click", save);
  });
}

function bindLeaderboardViewLinks() {
  document.querySelectorAll(".leaderboard-view-toggle a[data-preserve-scroll='true']").forEach((link) => {
    if (link.dataset.leaderboardViewBound === "true") return;
    link.dataset.leaderboardViewBound = "true";
    link.addEventListener("click", async (event) => {
      if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.button) return;
      event.preventDefault();
      savePreservedScroll(link);
      const section = link.closest("[data-leaderboard-section='true']");
      if (!section) {
        window.location.href = link.href;
        return;
      }
      const scrollTop = window.scrollY;
      section.classList.add("is-loading");
      try {
        const response = await fetch(link.href, {
          method: "GET",
          headers: { "Cache-Control": "no-store" },
        });
        const html = await response.text();
        const doc = new DOMParser().parseFromString(html, "text/html");
        const nextSection = doc.querySelector("[data-leaderboard-section='true']");
        if (!nextSection) {
          window.location.href = link.href;
          return;
        }
        section.replaceWith(nextSection);
        history.pushState({}, "", link.href);
        bindAnalysisForms();
        bindPreserveScrollLinks();
        bindLeaderboardViewLinks();
        window.scrollTo(window.scrollX, scrollTop);
      } catch (_error) {
        window.location.href = link.href;
      } finally {
        const currentSection = document.querySelector("[data-leaderboard-section='true']");
        if (currentSection) currentSection.classList.remove("is-loading");
      }
    });
  });
}

function savePreservedScroll(link) {
  const href = link.getAttribute("href") || "";
  let pathname = location.pathname;
  try {
    pathname = new URL(href, location.href).pathname;
  } catch (_error) {
    pathname = location.pathname;
  }
  sessionStorage.setItem(preserveScrollKey(pathname), String(window.scrollY));
}

function restorePreservedScroll() {
  const key = preserveScrollKey();
  const saved = sessionStorage.getItem(key);
  if (saved === null) return;
  const top = parseInt(saved, 10);
  if (Number.isNaN(top)) return;
  const restore = () => window.scrollTo(window.scrollX, top);
  restore();
  requestAnimationFrame(() => {
    restore();
    requestAnimationFrame(restore);
  });
  window.addEventListener("load", () => {
    restore();
    window.setTimeout(() => {
      restore();
      sessionStorage.removeItem(key);
    }, 100);
  }, { once: true });
}

function bindGraphPreviewCanvas() {
  document.querySelectorAll("[data-graph-canvas='view']").forEach((canvas) => {
    bindZoomControls(canvas);
    bindCanvasPanAndWheel(canvas, true);
    canvas.addEventListener("scroll", () => saveCanvasViewport(canvas), { passive: true });
    if (!restoreCanvasViewport(canvas)) {
      requestAnimationFrame(() => zoomGraphPreviewToFit(canvas));
    }
  });
}

setInterval(() => {
  const pill = document.querySelector(".pill-running");
  if (pill && !document.hidden) {
    saveDetailsState();
    saveAllCanvasViewports();
    window.location.reload();
  }
}, 5000);

function bindAnalysisForms() {
  document.querySelectorAll("[data-analysis-form='true']").forEach((form) => {
    if (form.dataset.analysisBound === "true") return;
    form.dataset.analysisBound = "true";
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      saveDetailsState();

      const button = form.querySelector("button");
      const progress = form.querySelector(".analysis-progress");
      const panel = form.closest("[data-analysis-panel='true']");
      const initialCardCount = panel ? panel.querySelectorAll(".analysis-card").length : 0;
      const messages = [
        "Sampling judge reasoning traces...",
        "Asking analyzer model for patterns...",
        "Waiting for response...",
        "Saving trend summary...",
      ];
      let index = 0;

      button.disabled = true;
      button.dataset.originalText = button.textContent;
      button.textContent = "Analyzing...";
      progress.textContent = messages[index];

      const timer = setInterval(() => {
        index = Math.min(index + 1, messages.length - 1);
        progress.textContent = messages[index];
      }, 2500);

      try {
        await fetch(form.action, { method: "POST", body: new FormData(form) });
        await pollAnalysisResult(panel, initialCardCount);
        clearInterval(timer);
      } catch (error) {
        clearInterval(timer);
        button.disabled = false;
        button.textContent = button.dataset.originalText || "Judge Pattern Analysis";
        progress.textContent = "Analysis request failed. Try again.";
      }
    });
  });
}

async function pollAnalysisResult(panel, initialCardCount) {
  if (!panel) return;

  const panelKey = panel.dataset.analysisKey;
  const maxAttempts = 80;
  for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
    await new Promise((resolve) => setTimeout(resolve, attempt === 0 ? 1000 : 3000));
    const response = await fetch(window.location.href, {
      method: "GET",
      headers: { "Cache-Control": "no-store" },
    });
    const html = await response.text();
    const doc = new DOMParser().parseFromString(html, "text/html");
    const selector = panelKey
      ? `[data-analysis-panel='true'][data-analysis-key="${CSS.escape(panelKey)}"]`
      : "[data-analysis-panel='true']";
    const nextPanel = doc.querySelector(selector);
    if (!nextPanel) continue;

    const nextCardCount = nextPanel.querySelectorAll(".analysis-card").length;
    if (nextCardCount > initialCardCount) {
      panel.replaceWith(nextPanel);
      bindAnalysisForms();
      return;
    }

    const progress = panel.querySelector(".analysis-progress");
    if (progress && attempt > 0) {
      progress.textContent = "Still waiting for the summary...";
    }
  }

  const button = panel.querySelector("button");
  const progress = panel.querySelector(".analysis-progress");
  if (button) {
    button.disabled = false;
    button.textContent = button.dataset.originalText || "Summarize Top Model";
  }
  if (progress) progress.textContent = "Still running. Refresh later to see the summary.";
}

function getCanvasZoom(canvas) {
  const saved = localStorage.getItem(canvasZoomKey(canvas));
  if (saved) {
    const parsed = parseFloat(saved);
    if (!isNaN(parsed)) return parsed;
  }
  return parseFloat(canvas.style.getPropertyValue("--canvas-zoom")) || 1;
}

function canvasViewportKey(canvas) {
  return `viewport:${canvas.dataset.graphId}:${location.pathname}:${location.search || "view"}`;
}

function canvasZoomKey(canvas) {
  return `zoom:${canvas.dataset.graphId}:${canvas.dataset.graphCanvas || "canvas"}`;
}

function saveCanvasViewport(canvas) {
  if (!canvas || !canvas.dataset.graphId) return;
  canvas.dataset.viewportTouched = "true";
  localStorage.setItem(canvasViewportKey(canvas), JSON.stringify({
    left: canvas.scrollLeft,
    top: canvas.scrollTop,
    zoom: getCanvasZoom(canvas),
  }));
}

function saveAllCanvasViewports() {
  document.querySelectorAll("[data-graph-canvas]").forEach(saveCanvasViewport);
}

function restoreCanvasViewport(canvas) {
  const saved = JSON.parse(localStorage.getItem(canvasViewportKey(canvas)) || "null");
  if (!saved) return false;
  canvas.dataset.viewportTouched = "true";
  if (typeof saved.zoom === "number") setCanvasZoom(canvas, saved.zoom);
  requestAnimationFrame(() => {
    canvas.scrollLeft = saved.left || 0;
    canvas.scrollTop = saved.top || 0;
    updateCanvasEdges(canvas);
  });
  return true;
}

function setCanvasZoom(canvas, zoom) {
  const clamped = Math.max(0.25, Math.min(3, Math.round(zoom * 100) / 100));
  canvas.style.setProperty("--canvas-zoom", String(clamped));
  localStorage.setItem(canvasZoomKey(canvas), String(clamped));
  const wrap = canvas.closest(".canvas-wrap") || canvas;
  const label = wrap.querySelector("[data-zoom='1']");
  if (label) label.textContent = `${Math.round(clamped * 100)}%`;
  updateCanvasEdges(canvas);
}

function bindZoomControls(canvas) {
  const wrap = canvas.closest(".canvas-wrap") || canvas;
  wrap.querySelectorAll("[data-zoom]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const current = getCanvasZoom(canvas);
      const step = btn.dataset.zoom;
      if (step === "+") setCanvasZoom(canvas, current + 0.15);
      else if (step === "-") setCanvasZoom(canvas, current - 0.15);
      else setCanvasZoom(canvas, 1);
      saveCanvasViewport(canvas);
    });
  });
}

function bindNodeCanvas() {
  document.querySelectorAll("[data-graph-canvas='true']").forEach((canvas) => {
    if (canvas.dataset.graphCanvas !== "true") return;
    bindPaletteDrops(canvas);
    bindSocketConnections(canvas);
    bindZoomControls(canvas);
    bindCanvasPanAndWheel(canvas, false);
    const savedZoom = getCanvasZoom(canvas);
    if (savedZoom !== 1) setCanvasZoom(canvas, savedZoom);
    restoreCanvasViewport(canvas);

    canvas.querySelectorAll("form").forEach((form) => {
      form.addEventListener("submit", () => saveCanvasViewport(canvas));
    });

    canvas.addEventListener("scroll", () => saveCanvasViewport(canvas), { passive: true });

    canvas.querySelectorAll(".canvas-node").forEach((node) => {
      const form = node.querySelector("[data-node-position-form='true']");
      if (!form) return;
      const resizeHandle = node.querySelector("[data-resize-handle='true']");

      let drag = null;
      let resize = null;
      let suppressClick = false;
      node.addEventListener("pointerdown", (event) => {
        if (event.button !== 0) return;
        if (event.target.closest("button, input, textarea, select, a, .socket, [data-resize-handle='true']")) return;
        const rect = node.getBoundingClientRect();
        const zoom = getCanvasZoom(canvas.closest(".node-canvas")) || 1;
        drag = {
          startX: event.clientX,
          startY: event.clientY,
          baseX: parseInt(node.style.getPropertyValue("--node-x") || "0", 10),
          baseY: parseInt(node.style.getPropertyValue("--node-y") || "0", 10),
          width: rect.width / zoom,
          moved: false,
        };
        node.setPointerCapture(event.pointerId);
      });

      if (resizeHandle) {
        resizeHandle.addEventListener("pointerdown", (event) => {
          if (event.button !== 0) return;
          event.preventDefault();
          event.stopPropagation();
          const zoom = getCanvasZoom(canvas.closest(".node-canvas")) || 1;
          const rect = node.getBoundingClientRect();
          resize = {
            startX: event.clientX,
            startY: event.clientY,
            baseW: parseInt(node.style.getPropertyValue("--node-w") || String(Math.round(rect.width / zoom)), 10),
            baseH: parseInt(node.style.getPropertyValue("--node-h") || String(Math.round(rect.height / zoom)), 10),
            moved: false,
          };
          resizeHandle.setPointerCapture(event.pointerId);
        });

        resizeHandle.addEventListener("pointermove", (event) => {
          if (!resize) return;
          if (event.buttons !== 1) {
            finishResize(event);
            return;
          }
          const zoom = getCanvasZoom(canvas.closest(".node-canvas")) || 1;
          const deltaX = (event.clientX - resize.startX) / zoom;
          const deltaY = (event.clientY - resize.startY) / zoom;
          if (!resize.moved && Math.hypot(deltaX * zoom, deltaY * zoom) < 5) return;
          resize.moved = true;
          suppressClick = true;
          const nextW = Math.max(300, Math.min(1100, Math.round(resize.baseW + deltaX)));
          const nextH = Math.max(160, Math.min(1000, Math.round(resize.baseH + deltaY)));
          node.style.setProperty("--node-w", String(nextW));
          node.style.setProperty("--node-h", String(nextH));
          updateCanvasEdges(canvas);
        });

        async function finishResize(event) {
          if (!resize) return;
          const moved = resize.moved;
          try {
            if (resizeHandle.hasPointerCapture(event.pointerId)) resizeHandle.releasePointerCapture(event.pointerId);
          } catch (_error) {
            // Pointer capture may already be released by the browser.
          }
          resize = null;
          if (!moved) return;
          await saveNodeGeometry(form, node);
        }

        resizeHandle.addEventListener("pointerup", finishResize);
        resizeHandle.addEventListener("pointercancel", finishResize);
      }

      node.addEventListener("pointermove", (event) => {
        if (!drag) return;
        if (event.buttons !== 1) {
          finishDrag(event);
          return;
        }
        const zoom = getCanvasZoom(canvas.closest(".node-canvas")) || 1;
        const deltaX = (event.clientX - drag.startX) / zoom;
        const deltaY = (event.clientY - drag.startY) / zoom;
        if (!drag.moved && Math.hypot(deltaX * zoom, deltaY * zoom) < 5) return;
        drag.moved = true;
        suppressClick = true;
        node.classList.add("is-dragging");
        event.preventDefault();
        const svg = canvas.querySelector(".graph-edge-layer");
        const canvasW = svg ? parseInt(svg.getAttribute("width") || "12000", 10) : 12000;
        const canvasH = svg ? parseInt(svg.getAttribute("height") || "8000", 10) : 8000;
        const maxX = Math.max(canvasW - drag.width, 0);
        const maxY = Math.max(canvasH - 200, 0);
        const nextX = Math.max(0, Math.min(maxX, drag.baseX + deltaX));
        const nextY = Math.max(0, Math.min(maxY, drag.baseY + deltaY));
        node.style.setProperty("--node-x", String(Math.round(nextX)));
        node.style.setProperty("--node-y", String(Math.round(nextY)));
        updateCanvasEdges(canvas);
      });

      async function finishDrag(event) {
        if (!drag) return;
        const moved = drag.moved;
        try {
          if (node.hasPointerCapture(event.pointerId)) node.releasePointerCapture(event.pointerId);
        } catch (_error) {
          // Pointer capture may already be released by the browser.
        }
        node.classList.remove("is-dragging");
        drag = null;
        if (!moved) return;
        await saveNodeGeometry(form, node);
      }

      node.addEventListener("pointerup", finishDrag);
      node.addEventListener("pointercancel", finishDrag);
      node.addEventListener("click", (event) => {
        if (!suppressClick) return;
        event.preventDefault();
        event.stopPropagation();
        suppressClick = false;
      }, true);
      node.addEventListener("lostpointercapture", () => {
        if (!drag) return;
        node.classList.remove("is-dragging");
        drag = null;
      });
    });
    updateCanvasEdges(canvas);
  });
}

function bindCanvasPanAndWheel(canvas, allowNodePan) {
  if (canvas.dataset.panZoomBound === "true") return;
  canvas.dataset.panZoomBound = "true";
  let pan = null;

  canvas.addEventListener("pointerdown", (event) => {
    if (event.button !== 0) return;
    if (event.target.closest(".socket, button, input, textarea, select, a")) return;
    if (!allowNodePan && event.target.closest(".canvas-node")) return;
    pan = { startX: event.clientX, startY: event.clientY, scrollLeft: canvas.scrollLeft, scrollTop: canvas.scrollTop };
    canvas.setPointerCapture(event.pointerId);
    canvas.classList.add("is-panning");
  });

  canvas.addEventListener("pointermove", (event) => {
    if (!pan) return;
    if (event.buttons !== 1) {
      finishPan();
      return;
    }
    canvas.scrollLeft = pan.scrollLeft - (event.clientX - pan.startX);
    canvas.scrollTop = pan.scrollTop - (event.clientY - pan.startY);
    saveCanvasViewport(canvas);
  });

  function finishPan() {
    if (!pan) return;
    canvas.classList.remove("is-panning");
    pan = null;
    saveCanvasViewport(canvas);
  }

  canvas.addEventListener("pointerup", finishPan);
  canvas.addEventListener("pointercancel", finishPan);

  canvas.addEventListener("wheel", (event) => {
    if (event.target.closest(".node-form input, .node-form textarea, .node-form select")) return;
    if (Math.abs(event.deltaX) > Math.abs(event.deltaY)) {
      event.preventDefault();
      canvas.scrollLeft += event.deltaX;
      saveCanvasViewport(canvas);
      return;
    }
    event.preventDefault();
    const rect = canvas.getBoundingClientRect();
    const mouseX = event.clientX - rect.left + canvas.scrollLeft;
    const mouseY = event.clientY - rect.top + canvas.scrollTop;
    const current = getCanvasZoom(canvas);
    const delta = -event.deltaY * 0.0015;
    const next = Math.max(0.25, Math.min(3, current + delta));
    if (Math.abs(next - current) > 0.001) {
      canvas.scrollLeft = mouseX - (mouseX - canvas.scrollLeft) * (next / current);
      canvas.scrollTop = mouseY - (mouseY - canvas.scrollTop) * (next / current);
      setCanvasZoom(canvas, next);
      saveCanvasViewport(canvas);
    }
  }, { passive: false });
}

function zoomGraphPreviewToFit(canvas) {
  if (canvas.dataset.viewportTouched === "true") return;
  const nodes = Array.from(canvas.querySelectorAll(".canvas-node"));
  if (!nodes.length) return;
  const bounds = nodes.reduce((acc, node) => {
    const x = parseInt(node.style.getPropertyValue("--node-x") || "0", 10);
    const y = parseInt(node.style.getPropertyValue("--node-y") || "0", 10);
    const w = parseInt(node.style.getPropertyValue("--node-w") || "460", 10);
    const h = parseInt(node.style.getPropertyValue("--node-h") || "260", 10);
    return {
      minX: Math.min(acc.minX, x),
      minY: Math.min(acc.minY, y),
      maxX: Math.max(acc.maxX, x + w),
      maxY: Math.max(acc.maxY, y + h),
    };
  }, { minX: Infinity, minY: Infinity, maxX: 0, maxY: 0 });
  const pad = 120;
  const width = Math.max(bounds.maxX - bounds.minX + pad * 2, 1);
  const height = Math.max(bounds.maxY - bounds.minY + pad * 2, 1);
  const zoom = Math.max(0.65, Math.min(1, Math.min(canvas.clientWidth / width, canvas.clientHeight / height)));
  canvas.style.setProperty("--canvas-zoom", String(Math.round(zoom * 100) / 100));
  canvas.scrollLeft = Math.max(0, bounds.minX - pad);
  canvas.scrollTop = Math.max(0, bounds.minY - pad);
  updateCanvasEdges(canvas);
}

function bindSocketConnections(canvas) {
  let selected = null;
  let draggingConnection = null;
  let connectionMoved = false;

  function clearConnectionUI() {
    clearTempLine(canvas);
    clearTargetHighlights(canvas);
  }

  canvas.querySelectorAll(".socket").forEach((socket) => {
    socket.addEventListener("pointerdown", (event) => {
      if (socket.dataset.socketSide !== "output") return;
      event.preventDefault();
      event.stopPropagation();
      draggingConnection = {
        nodeId: socket.dataset.nodeId,
        socketName: socket.dataset.socketName,
      };
      connectionMoved = false;
      selected = draggingConnection;
      canvas.querySelectorAll(".socket.is-selected").forEach((el) => el.classList.remove("is-selected"));
      socket.classList.add("is-selected");
      socket.setPointerCapture(event.pointerId);
    });

    socket.addEventListener("pointermove", (event) => {
      if (!draggingConnection) return;
      connectionMoved = true;
      const zoom = getCanvasZoom(canvas.closest(".node-canvas")) || 1;
      const sourceSocket = canvas.querySelector(
        `.socket-output[data-node-id="${draggingConnection.nodeId}"][data-socket-name="${cssEscape(draggingConnection.socketName)}"]`
      );
      const sourceNode = canvas.querySelector(`[data-node-id="${draggingConnection.nodeId}"]`);
      const source = socketPoint(canvas, sourceNode, sourceSocket, "output");
      const canvasRect = canvas.getBoundingClientRect();
      const mx = (event.clientX - canvasRect.left + canvas.scrollLeft) / zoom;
      const my = (event.clientY - canvasRect.top + canvas.scrollTop) / zoom;
      updateTempLine(canvas, source, { x: mx, y: my });
      highlightValidTargets(canvas, event.clientX, event.clientY);
    });

    socket.addEventListener("pointerup", async (event) => {
      clearConnectionUI();
      if (!draggingConnection) return;
      event.preventDefault();
      event.stopPropagation();
      try {
        if (socket.hasPointerCapture(event.pointerId)) socket.releasePointerCapture(event.pointerId);
      } catch (_error) {
        // Pointer capture may already be released.
      }
      const target = document.elementFromPoint(event.clientX, event.clientY);
      const input = target ? target.closest(".socket-input") : null;
      if (connectionMoved && input) {
        await createSocketEdge(canvas, draggingConnection, input);
      } else if (!connectionMoved) {
        await deleteSocketEdges(canvas, socket);
      }
      draggingConnection = null;
      connectionMoved = false;
    });

    socket.addEventListener("click", async (event) => {
      clearConnectionUI();
      event.preventDefault();
      event.stopPropagation();
      if (!connectionMoved && socket.classList.contains("is-connected")) {
        await deleteSocketEdges(canvas, socket);
        return;
      }
      const side = socket.dataset.socketSide;
      if (side === "output") {
        canvas.querySelectorAll(".socket.is-selected").forEach((el) => el.classList.remove("is-selected"));
        selected = {
          nodeId: socket.dataset.nodeId,
          socketName: socket.dataset.socketName,
        };
        socket.classList.add("is-selected");
        return;
      }
      if (side !== "input" || !selected) return;
      await createSocketEdge(canvas, selected, socket);
    });
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      document.querySelectorAll(".connection-drag-line").forEach((el) => el.remove());
      document.querySelectorAll(".socket.is-selected, .socket.is-target").forEach((el) => el.classList.remove("is-selected", "is-target"));
      selected = null;
      draggingConnection = null;
    }
  });
}

async function deleteSocketEdges(canvas, socket) {
  saveCanvasViewport(canvas);
  await saveNodeForms(canvas);
  const form = new FormData();
  form.set("node_id", socket.dataset.nodeId);
  form.set("socket", socket.dataset.socketName);
  form.set("side", socket.dataset.socketSide);
  try {
    const response = await fetch(`/graphs/${canvas.dataset.graphId}/socket-edges/delete`, { method: "POST", body: form });
    window.location.href = response.url || window.location.href;
  } catch (_error) {
    window.location.href = window.location.href;
  }
}

async function createSocketEdge(canvas, source, inputSocket) {
  saveCanvasViewport(canvas);
  await saveNodeForms(canvas);
  const form = new FormData();
  form.set("from_node_id", source.nodeId);
  form.set("from_socket", source.socketName);
  form.set("to_node_id", inputSocket.dataset.nodeId);
  form.set("to_socket", inputSocket.dataset.socketName);
  try {
    const response = await fetch(`/graphs/${canvas.dataset.graphId}/edges`, { method: "POST", body: form });
    window.location.href = response.url || window.location.href;
  } catch (_error) {
    window.location.href = window.location.href;
  }
}

function updateTempLine(canvas, source, target) {
  const svg = canvas.querySelector(".graph-edge-layer");
  if (!svg) return;
  let line = svg.querySelector(".connection-drag-line");
  if (!line) {
    line = document.createElementNS("http://www.w3.org/2000/svg", "path");
    line.setAttribute("class", "connection-drag-line");
    svg.appendChild(line);
  }
  const mid = Math.max(40, Math.abs(target.x - source.x) / 2);
  line.setAttribute(
    "d",
    `M ${source.x} ${source.y} C ${source.x + mid} ${source.y}, ${target.x - mid} ${target.y}, ${target.x} ${target.y}`
  );
}

function clearTempLine(canvas) {
  const line = canvas.querySelector(".connection-drag-line");
  if (line) line.remove();
}

function highlightValidTargets(canvas, clientX, clientY) {
  canvas.querySelectorAll(".socket-input").forEach((input) => {
    const rect = input.getBoundingClientRect();
    const hovered = clientX >= rect.left && clientX <= rect.right && clientY >= rect.top && clientY <= rect.bottom;
    input.classList.toggle("is-target", hovered);
  });
}

function clearTargetHighlights(canvas) {
  canvas.querySelectorAll(".socket.is-target").forEach((el) => el.classList.remove("is-target"));
}

function updateCanvasEdges(canvas) {
  const paths = canvas.querySelectorAll(".graph-edge-path");
  paths.forEach((path) => {
    const fromNode = canvas.querySelector(`[data-node-id="${path.dataset.fromNode}"]`);
    const toNode = canvas.querySelector(`[data-node-id="${path.dataset.toNode}"]`);
    if (!fromNode || !toNode) return;
    const fromSocket = fromNode.querySelector(`.socket-output[data-socket-name="${cssEscape(path.dataset.fromSocket)}"]`);
    const toSocket = toNode.querySelector(`.socket-input[data-socket-name="${cssEscape(path.dataset.toSocket)}"]`);
    const source = socketPoint(canvas, fromNode, fromSocket, "output");
    const target = socketPoint(canvas, toNode, toSocket, "input");
    const mid = Math.max(40, Math.abs(target.x - source.x) / 2);
    path.setAttribute("d", `M ${source.x} ${source.y} C ${source.x + mid} ${source.y}, ${target.x - mid} ${target.y}, ${target.x} ${target.y}`);
  });
}

async function saveNodeGeometry(form, node) {
  const x = node.style.getPropertyValue("--node-x") || "0";
  const y = node.style.getPropertyValue("--node-y") || "0";
  const width = node.style.getPropertyValue("--node-w") || "460";
  const height = node.style.getPropertyValue("--node-h") || "260";
  form.querySelector("[data-node-x='true']").value = x;
  form.querySelector("[data-node-y='true']").value = y;
  const widthInput = form.querySelector("[data-node-width='true']");
  const heightInput = form.querySelector("[data-node-height='true']");
  if (widthInput) widthInput.value = width;
  if (heightInput) heightInput.value = height;
  try {
    await fetch(form.action, { method: "POST", body: new FormData(form) });
  } catch (_error) {
    // Geometry saves are ergonomic only; editing and launching still work.
  }
}

function socketPoint(canvas, node, socket, side) {
  const zoom = getCanvasZoom(canvas.closest(".node-canvas")) || 1;
  const nodeX = parseInt(node.style.getPropertyValue("--node-x") || "0", 10);
  const nodeY = parseInt(node.style.getPropertyValue("--node-y") || "0", 10);
  const nodeW = parseInt(node.style.getPropertyValue("--node-w") || "460", 10);
  if (!socket) {
    return {
      x: side === "output" ? nodeX + nodeW : nodeX,
      y: nodeY + 56,
    };
  }
  const nodeRect = node.getBoundingClientRect();
  const port = socket.querySelector(".socket-port") || socket;
  const socketRect = port.getBoundingClientRect();
  return {
    x: nodeX + (socketRect.left - nodeRect.left) / zoom + socketRect.width / (2 * zoom),
    y: nodeY + (socketRect.top - nodeRect.top) / zoom + socketRect.height / (2 * zoom),
  };
}

function cssEscape(value) {
  if (window.CSS && window.CSS.escape) return window.CSS.escape(value || "");
  return String(value || "").replace(/["\\]/g, "\\$&");
}

function bindPaletteDrops(canvas) {
  document.querySelectorAll("[data-palette-node='true']").forEach((button) => {
    button.addEventListener("dragstart", (event) => {
      const form = button.closest("form");
      if (!form) return;
      event.dataTransfer.effectAllowed = "copy";
      event.dataTransfer.setData("text/plain", form.action);
    });
  });

  canvas.addEventListener("dragover", (event) => {
    if (!Array.from(event.dataTransfer.types).includes("text/plain")) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = "copy";
  });

  canvas.addEventListener("drop", async (event) => {
    const action = event.dataTransfer.getData("text/plain");
    if (!action) return;
    event.preventDefault();
    const rect = canvas.getBoundingClientRect();
    const form = Array.from(document.querySelectorAll(".palette-form")).find((candidate) => candidate.action === action);
    if (!form) return;
    form.querySelector("[data-palette-x='true']").value = Math.max(0, Math.round(event.clientX - rect.left + canvas.scrollLeft - 130));
    form.querySelector("[data-palette-y='true']").value = Math.max(0, Math.round(event.clientY - rect.top + canvas.scrollTop - 32));
    try {
      await saveNodeForms(canvas);
      saveCanvasViewport(canvas);
      const response = await fetch(form.action, { method: "POST", body: new FormData(form) });
      window.location.href = response.url || window.location.href;
    } catch (_error) {
      form.submit();
    }
  });
}

async function saveNodeForms(canvas) {
  const forms = Array.from(canvas.querySelectorAll(".node-form"));
  await Promise.all(
    forms.map(async (form) => {
      if (!form.action) return;
      try {
        await fetch(form.action, { method: "POST", body: new FormData(form) });
      } catch (_error) {
        // The next reload will keep the last persisted version if one form fails.
      }
    })
  );
}

function bindDatasetSourceFields() {
  document.querySelectorAll("[data-dataset-source='true']").forEach((select) => {
    const form = select.closest("form");
    const csvFields = form ? form.querySelector(".csv-only-fields") : null;
    if (!csvFields) return;
    const sync = () => {
      csvFields.hidden = select.value !== "csv";
    };
    select.addEventListener("change", sync);
    sync();
  });
}

function bindReasoningFields() {
  document.querySelectorAll("[data-reasoning-toggle='true']").forEach((toggle) => {
    const form = toggle.closest("form");
    const field = form ? form.querySelector(".reasoning-effort-field") : null;
    if (!field) return;
    const sync = () => {
      field.hidden = !toggle.checked;
    };
    toggle.addEventListener("change", sync);
    sync();
  });
}
