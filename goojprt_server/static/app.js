/* GoojPrt PT-210 Print Server — minimal live UI (vanilla JS, no framework).
 *
 * Responsibilities:
 *   - Poll /api/health every POLL_MS → update status pill + queue counter.
 *   - Poll /api/jobs every POLL_MS → re-render the "Recent jobs" tbody.
 *   - Intercept form submits → POST JSON to /api/print/* or /api/feed,
 *     show inline flash, immediately refresh jobs.
 *
 * Polling is suspended while the page is hidden (visibilitychange) so the
 * tab doesn't hammer the server when the user switches away.
 */
(() => {
  const POLL_MS = 1500;
  const STATUS_GLYPHS = { done: "✓", failed: "✗", running: "⋯", queued: "·" };

  const $ = (id) => document.getElementById(id);
  const pill = $("status-pill");
  const qSize = $("queue-size");
  const qMax = $("queue-max");
  const tbody = $("jobs-tbody");
  const flash = $("flash");
  const indicator = $("jobs-indicator");

  let pollTimer = null;
  let inflight = false;
  let lastJobsJSON = "";

  async function fetchJSON(url, opts = {}) {
    const res = await fetch(url, { headers: { "Accept": "application/json" }, ...opts });
    if (!res.ok) {
      let body = null;
      try { body = await res.json(); } catch (_) { /* ignore */ }
      const err = new Error(`HTTP ${res.status}`);
      err.status = res.status;
      err.body = body;
      throw err;
    }
    return res.json();
  }

  function renderStatus(health) {
    if (!pill) return;
    const ok = !!health.connected;
    pill.textContent = ok ? "● Connected" : "○ Disconnected";
    pill.classList.toggle("pill-ok", ok);
    pill.classList.toggle("pill-bad", !ok);
    if (qSize) qSize.textContent = String(health.queue_size);
    if (qMax) qMax.textContent = String(health.queue_max);
  }

  function renderJobs(jobs) {
    if (!tbody) return;
    // Skip DOM churn when nothing changed.
    const hash = JSON.stringify(jobs);
    if (hash === lastJobsJSON) return;
    lastJobsJSON = hash;

    const frag = document.createDocumentFragment();
    for (const j of jobs) {
      const tr = document.createElement("tr");
      tr.className = `row-${j.status}`;
      tr.dataset.jobId = j.id;

      const glyph = document.createElement("td");
      glyph.textContent = STATUS_GLYPHS[j.status] ?? "?";
      tr.appendChild(glyph);

      const id = document.createElement("td");
      const code = document.createElement("code");
      code.textContent = j.id;
      id.appendChild(code);
      tr.appendChild(id);

      const type = document.createElement("td");
      type.textContent = j.type;
      tr.appendChild(type);

      const status = document.createElement("td");
      status.textContent = j.status;
      tr.appendChild(status);

      const dur = document.createElement("td");
      dur.textContent = (j.duration_ms != null) ? `${j.duration_ms}ms` : "—";
      tr.appendChild(dur);

      frag.appendChild(tr);
    }
    tbody.replaceChildren(frag);
  }

  async function refresh() {
    if (inflight) return;
    inflight = true;
    indicator?.classList.add("indicator-live");
    try {
      const [health, jobs] = await Promise.all([
        fetchJSON("/api/health"),
        fetchJSON("/api/jobs?limit=20"),
      ]);
      renderStatus(health);
      renderJobs(jobs);
      indicator?.classList.remove("indicator-stale");
    } catch (err) {
      // Mark as stale but don't tear down the UI; next tick may recover.
      indicator?.classList.add("indicator-stale");
      console.warn("[goojprt] refresh failed", err);
    } finally {
      indicator?.classList.remove("indicator-live");
      inflight = false;
    }
  }

  function startPolling() {
    stopPolling();
    refresh();
    pollTimer = setInterval(refresh, POLL_MS);
  }

  function stopPolling() {
    if (pollTimer) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
  }

  document.addEventListener("visibilitychange", () => {
    if (document.hidden) stopPolling();
    else startPolling();
  });

  // ── Flash helpers ────────────────────────────────────────────────

  let flashTimer = null;
  function showFlash(message, kind) {
    if (!flash) return;
    clearTimeout(flashTimer);
    flash.textContent = message;
    flash.className = `flash flash-${kind} flash-visible`;
    flashTimer = setTimeout(() => {
      flash.classList.remove("flash-visible");
    }, 3500);
  }

  // ── Form submit handling ─────────────────────────────────────────

  const FORM_ENDPOINTS = {
    text: "/api/print/text",
    qr: "/api/print/qr",
    pdf417: "/api/print/pdf417",
    feed: "/api/feed",
  };

  function formToPayload(form, jobType) {
    const fd = new FormData(form);
    const raw = Object.fromEntries(fd.entries());
    delete raw._type;

    const toInt = (k) => raw[k] !== undefined ? parseInt(raw[k], 10) : undefined;
    const hasCheckbox = (k) => form.elements[k]?.type === "checkbox"
                              ? form.elements[k].checked : Boolean(raw[k]);

    if (jobType === "text") {
      return {
        text: raw.text ?? "",
        align: raw.align ?? "left",
        bold: hasCheckbox("bold"),
        underline: hasCheckbox("underline"),
        bitmap: hasCheckbox("bitmap"),
        feed_after: toInt("feed_after") ?? 0,
      };
    }
    if (jobType === "qr") {
      return { data: raw.data, size: toInt("size") ?? 6, align: raw.align ?? "center" };
    }
    if (jobType === "pdf417") {
      return {
        data: raw.data,
        align: raw.align ?? "center",
        columns: toInt("columns") ?? 5,
        scale: toInt("scale") ?? 2,
        row_height: toInt("row_height") ?? 5,
      };
    }
    if (jobType === "feed") {
      return { lines: toInt("lines") ?? 3 };
    }
    return {};
  }

  async function handleSubmit(e) {
    const form = e.target;
    const jobType = form.dataset.printType;
    const endpoint = FORM_ENDPOINTS[jobType];
    if (!endpoint) return;  // unknown form → fall back to native POST

    e.preventDefault();
    const submitBtn = form.querySelector("button[type=submit]");
    if (submitBtn) submitBtn.disabled = true;

    try {
      const payload = formToPayload(form, jobType);
      const res = await fetchJSON(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json", "Accept": "application/json" },
        body: JSON.stringify(payload),
      });
      showFlash(`Queued ${res.job_id} (position ${res.queue_position})`, "ok");
      // Immediate refresh so the user sees the new row.
      refresh();
    } catch (err) {
      const msg = err.body?.detail?.error
        || err.body?.detail?.[0]?.msg
        || err.body?.error
        || `Error ${err.status || ""}`.trim();
      showFlash(`Failed: ${msg}`, "bad");
    } finally {
      if (submitBtn) submitBtn.disabled = false;
    }
  }

  document.querySelectorAll("form[data-print-type]").forEach((f) => {
    f.addEventListener("submit", handleSubmit);
  });

  // ── Image print section ─────────────────────────────────────────

  const imageForm    = document.getElementById("image-form");
  const imageFile    = document.getElementById("image-file");
  const imageEditor  = document.getElementById("image-editor");
  const canvas       = document.getElementById("image-canvas");

  if (imageForm && canvas) {
    const ctx = canvas.getContext("2d");
    let srcImage = null;
    let rotation = 0;
    let crop = null;

    ["brightness", "contrast", "threshold", "scale"].forEach((id) => {
      const inp = document.getElementById(id);
      const lbl = document.getElementById(`${id}-val`);
      if (!inp || !lbl) return;
      inp.addEventListener("input", () => {
        lbl.textContent = id === "scale"
          ? `${Math.round(inp.value * 100)}%`
          : parseFloat(inp.value).toFixed(id === "threshold" ? 0 : 1);
        drawPreview();
      });
    });

    const ditherCb   = document.getElementById("dither");
    const threshLbl  = document.getElementById("threshold-label");
    const threshInp  = document.getElementById("threshold");
    function syncThresholdState() {
      if (!ditherCb || !threshInp) return;
      threshInp.disabled = ditherCb.checked;
      if (threshLbl) threshLbl.style.opacity = ditherCb.checked ? "0.4" : "1";
    }
    ditherCb?.addEventListener("change", () => { syncThresholdState(); drawPreview(); });
    syncThresholdState();

    document.getElementById("rotate-ccw")?.addEventListener("click", () => {
      rotation = (rotation + 270) % 360;
      document.getElementById("rotate-val").value = rotation;
      crop = null; resetCropFields(); drawPreview();
    });
    document.getElementById("rotate-cw")?.addEventListener("click", () => {
      rotation = (rotation + 90) % 360;
      document.getElementById("rotate-val").value = rotation;
      crop = null; resetCropFields(); drawPreview();
    });
    document.getElementById("rotate-180")?.addEventListener("click", () => {
      rotation = (rotation + 180) % 360;
      document.getElementById("rotate-val").value = rotation;
      crop = null; resetCropFields(); drawPreview();
    });

    imageFile?.addEventListener("change", (e) => {
      const file = e.target.files[0];
      if (!file) return;
      const reader = new FileReader();
      reader.onload = (ev) => {
        const img = new Image();
        img.onload = () => {
          srcImage = img;
          rotation = 0;
          document.getElementById("rotate-val").value = 0;
          crop = null; resetCropFields();
          imageEditor.style.display = "";
          drawPreview();
        };
        img.src = ev.target.result;
      };
      reader.readAsDataURL(file);
    });

    function drawPreview() {
      if (!srcImage) return;
      const brightness = parseFloat(document.getElementById("brightness")?.value ?? 1);
      const contrast   = parseFloat(document.getElementById("contrast")?.value ?? 1);
      const threshold  = parseInt(document.getElementById("threshold")?.value ?? 128, 10);
      const dither     = ditherCb?.checked ?? true;

      const rad = rotation * Math.PI / 180;
      const swapped = rotation === 90 || rotation === 270;
      const sw = swapped ? srcImage.height : srcImage.width;
      const sh = swapped ? srcImage.width  : srcImage.height;

      const off = document.createElement("canvas");
      off.width = sw; off.height = sh;
      const oc = off.getContext("2d");
      oc.translate(sw / 2, sh / 2);
      oc.rotate(rad);
      oc.drawImage(srcImage, -srcImage.width / 2, -srcImage.height / 2);

      const displayW = canvas.parentElement?.clientWidth || 300;
      canvas.width  = displayW;
      canvas.height = Math.round(sh * displayW / sw);

      ctx.filter = `brightness(${brightness}) contrast(${contrast})`;
      ctx.drawImage(off, 0, 0, canvas.width, canvas.height);
      ctx.filter = "none";

      const imgData = ctx.getImageData(0, 0, canvas.width, canvas.height);
      const d = imgData.data;
      if (dither) {
        for (let i = 0; i < d.length; i += 4) {
          const g = 0.299 * d[i] + 0.587 * d[i+1] + 0.114 * d[i+2];
          d[i] = d[i+1] = d[i+2] = g;
        }
      } else {
        for (let i = 0; i < d.length; i += 4) {
          const g = 0.299 * d[i] + 0.587 * d[i+1] + 0.114 * d[i+2];
          const bw = g > threshold ? 255 : 0;
          d[i] = d[i+1] = d[i+2] = bw;
        }
      }
      ctx.putImageData(imgData, 0, 0);

      if (crop) {
        ctx.strokeStyle = "rgba(6,170,255,0.85)";
        ctx.lineWidth = 2;
        ctx.setLineDash([5, 4]);
        ctx.strokeRect(crop.x, crop.y, crop.w, crop.h);
        ctx.setLineDash([]);
      }
    }

    let dragStart = null;

    canvas.addEventListener("mousedown", (e) => {
      const r = canvas.getBoundingClientRect();
      dragStart = { x: e.clientX - r.left, y: e.clientY - r.top };
    });
    canvas.addEventListener("mousemove", (e) => {
      if (!dragStart) return;
      const r = canvas.getBoundingClientRect();
      const mx = e.clientX - r.left;
      const my = e.clientY - r.top;
      crop = {
        x: Math.min(dragStart.x, mx),
        y: Math.min(dragStart.y, my),
        w: Math.abs(mx - dragStart.x),
        h: Math.abs(my - dragStart.y),
      };
      drawPreview();
    });
    canvas.addEventListener("mouseup", () => {
      dragStart = null;
      if (crop && (crop.w < 4 || crop.h < 4)) {
        crop = null; resetCropFields();
      } else if (crop) {
        document.getElementById("crop_x").value = (crop.x / canvas.width).toFixed(4);
        document.getElementById("crop_y").value = (crop.y / canvas.height).toFixed(4);
        document.getElementById("crop_w").value = (crop.w / canvas.width).toFixed(4);
        document.getElementById("crop_h").value = (crop.h / canvas.height).toFixed(4);
      }
    });

    function resetCropFields() {
      ["crop_x","crop_y"].forEach(id => document.getElementById(id).value = "0");
      ["crop_w","crop_h"].forEach(id => document.getElementById(id).value = "1");
    }

    imageForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      const btn = imageForm.querySelector("button[type=submit]");
      if (btn) btn.disabled = true;

      const fd = new FormData(imageForm);
      if (!ditherCb?.checked) fd.set("dither", "false");

      try {
        const res = await fetchJSON("/api/print/image", { method: "POST", body: fd });
        showFlash(`Queued ${res.job_id} (position ${res.queue_position})`, "ok");
        refresh();
      } catch (err) {
        const msg = err.body?.detail?.error
          || err.body?.detail?.[0]?.msg
          || err.body?.error
          || `Error ${err.status || ""}`.trim();
        showFlash(`Failed: ${msg}`, "bad");
      } finally {
        if (btn) btn.disabled = false;
      }
    });
  }

  startPolling();
})();
