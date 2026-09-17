"use strict";

// Navigation of an already-rendered SVG. Layout, source, and export geometry stay
// with the diagram renderer; this camera belongs to one opening of a file.
(() => {
  function mount(canvas, { controls, view }) {
    const svg = canvas.querySelector("svg");
    const { width: diagramWidth, height: diagramHeight } = svg.viewBox.baseVal;
    if (!(diagramWidth > 0 && diagramHeight > 0)) throw new Error("Diagram has no drawable bounds.");
    const plane = document.createElement("div");
    plane.className = "diagram-viewport-plane";
    plane.style.width = `${diagramWidth}px`;
    plane.style.height = `${diagramHeight}px`;
    plane.append(svg);
    canvas.replaceChildren(plane);
    canvas.classList.add("is-interactive");
    canvas.tabIndex = 0;
    canvas.setAttribute("role", "region");
    canvas.setAttribute("aria-label", "Interactive diagram");
    canvas.setAttribute("aria-describedby", "diagram-navigation-help");
    const abort = new AbortController();
    const pointers = new Map();
    const buttons = [...controls.querySelectorAll("button")];
    const level = controls.querySelector("output");
    let width = 0, height = 0, scale = 1, x = 0, y = 0, disposed = false;
    const padding = 24;
    const clamp = (value, min, max) => Math.max(min, Math.min(max, value));
    const fitScale = () => Math.min(1, Math.max(1, width - padding * 2) / diagramWidth,
      Math.max(1, height - padding * 2) / diagramHeight);
    const minScale = () => Math.min(0.1, fitScale());
    const constrain = (offset, extent, available) => extent <= available - padding * 2
      ? (available - extent) / 2 : clamp(offset, available - padding - extent, padding);

    function paint() {
      if (disposed || !width || !height) return;
      if (view.mode === "fit" || !Number.isFinite(view.scale)) {
        view.mode = "fit";
        scale = fitScale();
        view.centerX = diagramWidth / 2;
        view.centerY = diagramHeight / 2;
      } else scale = clamp(view.scale, minScale(), 4);
      x = constrain(width / 2 - view.centerX * scale, diagramWidth * scale, width);
      y = constrain(height / 2 - view.centerY * scale, diagramHeight * scale, height);
      view.scale = scale;
      view.centerX = (width / 2 - x) / scale;
      view.centerY = (height / 2 - y) / scale;
      plane.style.transform = `translate(${x}px, ${y}px) scale(${scale})`;
      const percent = scale * 100;
      level.value = `${percent < 10 ? Number(percent.toFixed(1)) : Math.round(percent)}%`;
      for (const button of buttons) {
        const action = button.dataset.diagramZoom;
        button.disabled = action === "out" ? scale <= minScale() + 0.000001
          : action === "in" ? scale >= 4 : false;
      }
      controls.querySelector('[data-diagram-zoom="fit"]').setAttribute("aria-pressed", String(view.mode === "fit"));
    }

    function fit() { view.mode = "fit"; paint(); }
    function zoom(next, anchorX = width / 2, anchorY = height / 2) {
      const nextScale = clamp(next, minScale(), 4);
      const localX = (anchorX - x) / scale, localY = (anchorY - y) / scale;
      view.mode = "manual";
      view.scale = nextScale;
      view.centerX = localX + (width / 2 - anchorX) / nextScale;
      view.centerY = localY + (height / 2 - anchorY) / nextScale;
      paint();
    }
    function pan(dx, dy) {
      if (!dx && !dy) return;
      if (constrain(x + dx, diagramWidth * scale, width) === x
          && constrain(y + dy, diagramHeight * scale, height) === y) return;
      view.mode = "manual";
      view.centerX -= dx / scale;
      view.centerY -= dy / scale;
      paint();
    }
    function listen(target, event, handler, options = {}) {
      target.addEventListener(event, handler, { ...options, signal: abort.signal });
    }
    listen(controls, "click", (event) => {
      const action = event.target.closest("[data-diagram-zoom]")?.dataset.diagramZoom;
      if (action === "fit") fit();
      if (action === "actual") zoom(1);
      if (action === "in") zoom(scale * 1.25);
      if (action === "out") zoom(scale / 1.25);
    });
    listen(canvas, "keydown", (event) => {
      if (event.ctrlKey || event.metaKey || event.altKey || event.target !== canvas) return;
      const actions = {
        "+": () => zoom(scale * 1.25), "=": () => zoom(scale * 1.25), "-": () => zoom(scale / 1.25),
        "0": fit, Home: fit, "1": () => zoom(1),
        ArrowLeft: () => pan(48, 0), ArrowRight: () => pan(-48, 0),
        ArrowUp: () => pan(0, 48), ArrowDown: () => pan(0, -48),
      };
      if (actions[event.key]) { event.preventDefault(); actions[event.key](); }
    });
    listen(canvas, "wheel", (event) => {
      event.preventDefault();
      const unit = event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? height : 1;
      if (event.ctrlKey || event.metaKey) {
        const rect = canvas.getBoundingClientRect();
        zoom(scale * Math.exp(-clamp(event.deltaY * unit, -100, 100) * 0.01),
          event.clientX - rect.left - canvas.clientLeft, event.clientY - rect.top - canvas.clientTop);
      } else {
        pan(-(event.shiftKey && !event.deltaX ? event.deltaY : event.deltaX) * unit,
          -(event.shiftKey && !event.deltaX ? 0 : event.deltaY) * unit);
      }
    }, { passive: false });

    const point = (event) => {
      const rect = canvas.getBoundingClientRect();
      return { x: event.clientX - rect.left - canvas.clientLeft, y: event.clientY - rect.top - canvas.clientTop };
    };
    function gesture() {
      const [a, b = a] = [...pointers.values()];
      return { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2, distance: Math.hypot(a.x - b.x, a.y - b.y) };
    }
    listen(canvas, "pointerdown", (event) => {
      if (event.pointerType === "mouse" && event.button !== 0) return;
      if (pointers.size >= 2) return;
      canvas.focus({ preventScroll: true });
      canvas.setPointerCapture(event.pointerId);
      pointers.set(event.pointerId, point(event));
      canvas.classList.add("is-panning");
    });
    listen(canvas, "pointermove", (event) => {
      if (!pointers.has(event.pointerId)) return;
      const before = gesture();
      pointers.set(event.pointerId, point(event));
      const after = gesture();
      if (pointers.size === 2 && before.distance > 0 && after.distance > 0) {
        zoom(scale * after.distance / before.distance, before.x, before.y);
      }
      pan(after.x - before.x, after.y - before.y);
    });
    function release(event) {
      pointers.delete(event.pointerId);
      if (canvas.hasPointerCapture(event.pointerId)) canvas.releasePointerCapture(event.pointerId);
      canvas.classList.toggle("is-panning", pointers.size > 0);
    }
    for (const event of ["pointerup", "pointercancel", "lostpointercapture"]) listen(canvas, event, release);

    const observer = new ResizeObserver(() => {
      width = canvas.clientWidth;
      height = canvas.clientHeight;
      paint();
    });
    observer.observe(canvas);
    width = canvas.clientWidth;
    height = canvas.clientHeight;
    paint();
    return () => {
      disposed = true;
      observer.disconnect();
      abort.abort();
      for (const id of pointers.keys()) if (canvas.hasPointerCapture(id)) canvas.releasePointerCapture(id);
      pointers.clear();
    };
  }
  window.TinDiagramViewport = Object.freeze({ mount });
})();
