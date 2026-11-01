(() => {
  const state = { user: null, cases: [], caseCache: new Map(), evidence: [], tasks: [], markers: [], activeCase: null, activeEvidence: null, casePage: 1, casePages: 1, view: "overview" };
  const byId = (id) => document.getElementById(id);
  const token = document.querySelector('meta[name="csrf-token"]')?.content || "";
  const graphViewport = { x: 0, y: 0, width: 900, height: 460, dragX: 0, dragY: 0, dragging: false };
  const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char]);
  let toastTimer;

  async function api(url, options = {}) {
    const headers = { "X-CSRFToken": token, ...(options.headers || {}) };
    if (options.body && !(options.body instanceof FormData)) headers["Content-Type"] = "application/json";
    const response = await fetch(url, { credentials: "same-origin", ...options, headers });
    const contentType = response.headers.get("content-type") || "";
    const payload = contentType.includes("application/json") ? await response.json() : null;
    if (!response.ok) throw new Error(payload?.error || `Request failed (${response.status}).`);
    return payload;
  }

  function notify(message, error = false) {
    const toast = byId("toast");
    toast.textContent = message;
    toast.classList.toggle("error", error);
    toast.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toast.classList.remove("show"), 3200);
  }

  function setBusy(form, busy) {
    const button = form.querySelector('button[type="submit"]');
    if (!button) return;
    if (busy) {
      button.dataset.originalLabel = button.textContent;
      button.disabled = true;
      button.textContent = "Working…";
    } else {
      button.disabled = false;
      button.textContent = button.dataset.originalLabel || "Submit";
    }
  }

  function formObject(form) {
    return Object.fromEntries(new FormData(form).entries());
  }

  async function withForm(form, work) {
    setBusy(form, true);
    try { await work(); }
    catch (error) {
      if (form.id === "login-form" || form.id === "register-form") byId("auth-error").textContent = error.message;
      else notify(error.message || "The request could not be completed.", true);
    }
    finally { setBusy(form, false); }
  }

  function switchAuthMode(register) {
    byId("login-form").classList.toggle("hidden", register);
    byId("register-form").classList.toggle("hidden", !register);
    byId("auth-heading").textContent = register ? "Create account" : "Sign in";
    byId("auth-copy").textContent = register ? "New accounts receive investigator access." : "Access is limited to authorized case personnel.";
    byId("auth-switch-label").textContent = register ? "Already registered?" : "New to this workspace?";
    byId("auth-switch").textContent = register ? "Sign in" : "Create account";
    byId("auth-error").textContent = "";
  }

  function enterWorkspace(user) {
    state.user = user;
    byId("auth-shell").classList.add("hidden");
    byId("workspace").classList.remove("hidden");
    byId("user-name").textContent = user.username;
    byId("user-role").textContent = user.role;
    byId("user-avatar").textContent = user.username.slice(0, 1).toUpperCase();
    if (user.role === "Administrator") initializeAdminView();
    const readOnly = user.role === "Reviewer";
    document.querySelectorAll("#case-form,#case-edit-form,#evidence-form,#task-form,#handling-form,#relationship-form,#marker-form,#generate-report,[data-action='new-case']").forEach((el) => {
      if (readOnly) el.classList.add("hidden");
    });
    loadCases();
    updateClock();
    setInterval(updateClock, 30000);
  }

  function updateClock() {
    byId("local-clock").textContent = new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit", timeZoneName: "short" }).format(new Date());
  }

  function showView(name) {
    state.view = name;
    document.querySelectorAll(".view").forEach((view) => view.classList.toggle("active", view.id === `view-${name}`));
    document.querySelectorAll(".nav-item").forEach((button) => button.classList.toggle("active", button.dataset.view === name));
    const label = { overview: "Overview", cases: "Case files", evidence: "Evidence", tasks: "Checklist", traceguard: "TraceGuard", links: "EvidenceLink", scene: "SceneReplay", reports: "Reports", users: "User access" }[name] || "Overview";
    byId("page-title").textContent = label;
    byId("case-detail-panel").classList.toggle("hidden", name !== "cases" || !activeCase());
    byId("sidebar").classList.remove("open");
    if (name === "overview") loadOverview();
    if (name === "evidence") loadEvidence();
    if (name === "tasks") loadTasks();
    if (name === "traceguard") loadHandling();
    if (name === "links") loadRelationships();
    if (name === "scene") {
      loadMarkers();
      window.dispatchEvent(new Event("resize"));
    }
    if (name === "reports") loadReports();
    if (name === "users") loadUsers();
  }

  function initializeAdminView() {
    if (byId("view-users")) return;
    const nav = document.createElement("button");
    nav.className = "nav-item";
    nav.dataset.view = "users";
    nav.innerHTML = '<span class="nav-glyph">♙</span>User access';
    document.querySelector(".main-nav[aria-label='Analysis tools']").append(nav);
    const view = document.createElement("section");
    view.id = "view-users";
    view.className = "view";
    view.innerHTML = '<div class="page-intro"><div><p class="eyebrow">ADMINISTRATION</p><h1>User access</h1><p class="muted">Assign a workspace role and enable or disable accounts.</p></div></div><section class="panel"><div class="panel-heading"><div><p class="eyebrow">REGISTERED ACCOUNTS</p><h2>Users</h2></div></div><div class="table-scroll"><table><thead><tr><th>ACCOUNT</th><th>ROLE</th><th>ACTIVE</th><th>CREATED</th></tr></thead><tbody id="users-table"></tbody></table></div></section>';
    document.querySelector(".content-wrap").append(view);
  }

  function activeCase() {
    return state.caseCache.get(state.activeCase) || state.cases.find((item) => item.id === state.activeCase) || null;
  }

  function renderCaseDetails() {
    const caseRecord = activeCase();
    const panel = byId("case-detail-panel");
    panel.classList.toggle("hidden", state.view !== "cases" || !caseRecord || state.user?.role === "Reviewer");
    if (!caseRecord) return;
    byId("case-detail-number").textContent = `${caseRecord.case_number} · UPDATED ${new Date(caseRecord.updated_at).toLocaleString()}`;
    const form = byId("case-edit-form");
    for (const field of ["title", "case_type", "status", "priority", "description"]) {
      form.elements[field].value = caseRecord[field] || "";
    }
  }

  async function loadCases(page = state.casePage) {
    state.casePage = Math.max(page, 1);
    const search = byId("case-search")?.value || "";
    const status = byId("case-status-filter")?.value || "";
    const params = new URLSearchParams();
    if (search) params.set("q", search);
    if (status) params.set("status", status);
    params.set("page", state.casePage);
    try {
      const result = await api(`/api/cases?${params}`);
      state.cases = result.items;
      for (const item of result.items) state.caseCache.set(item.id, item);
      state.casePage = result.page;
      state.casePages = Math.max(result.pages, 1);
      if (!state.activeCase || !state.caseCache.has(state.activeCase)) {
        const preferred = sessionStorage.getItem("forensight-active-case");
        state.activeCase = state.cases.some((item) => item.id === Number(preferred)) ? Number(preferred) : state.cases[0]?.id || null;
      }
      renderCases(result.items);
      renderCaseSelector();
      renderCaseDetails();
      await refreshCaseData();
      if (state.view === "overview") loadOverview();
    } catch (error) { notify(error.message, true); }
  }

  function renderCaseSelector() {
    const select = byId("case-selector");
    const options = [...state.cases];
    const selected = activeCase();
    if (selected && !options.some((item) => item.id === selected.id)) options.unshift(selected);
    select.innerHTML = '<option value="">No case selected</option>' + options.map((item) => `<option value="${item.id}">${escapeHtml(item.case_number)} · ${escapeHtml(item.title)}</option>`).join("");
    select.value = state.activeCase || "";
  }

  function caseStatusClass(status) {
    return `status-${String(status).toLowerCase().replaceAll(" ", "-")}`;
  }

  function renderCases(items) {
    const tbody = byId("cases-table");
    tbody.innerHTML = items.map((item) => `<tr data-case-id="${item.id}"><td class="table-case"><strong>${escapeHtml(item.title)}</strong><small>${escapeHtml(item.case_number)}</small></td><td>${escapeHtml(item.case_type)}</td><td><span class="status-pill ${caseStatusClass(item.status)}">${escapeHtml(item.status)}</span></td><td><span class="priority-pill priority-${escapeHtml(item.priority.toLowerCase())}">${escapeHtml(item.priority)}</span></td><td>${new Date(item.updated_at).toLocaleDateString()}</td><td class="row-link">→</td></tr>`).join("");
    byId("cases-empty").classList.toggle("hidden", items.length > 0);
    byId("cases-table").closest(".table-scroll").classList.toggle("hidden", items.length === 0);
    const pagination = byId("case-pagination");
    if (pagination) {
      pagination.classList.toggle("hidden", state.casePages <= 1);
      byId("case-page-label").textContent = `PAGE ${state.casePage} OF ${state.casePages}`;
      byId("case-page-prev").disabled = state.casePage <= 1;
      byId("case-page-next").disabled = state.casePage >= state.casePages;
    }
  }

  function initializeCasePagination() {
    const table = document.querySelector("#view-cases .table-scroll");
    if (!table || byId("case-pagination")) return;
    const controls = document.createElement("div");
    controls.id = "case-pagination";
    controls.className = "table-pagination hidden";
    controls.innerHTML = '<button class="button button-quiet button-small" id="case-page-prev" data-action="case-prev" type="button">← Previous</button><span class="mono" id="case-page-label"></span><button class="button button-quiet button-small" id="case-page-next" data-action="case-next" type="button">Next →</button>';
    table.after(controls);
  }

  async function selectCase(id) {
    state.activeCase = Number(id) || null;
    if (state.activeCase) sessionStorage.setItem("forensight-active-case", String(state.activeCase));
    else sessionStorage.removeItem("forensight-active-case");
    renderCaseSelector();
    renderCaseDetails();
    await refreshCaseData();
    if (["overview", "cases"].includes(state.view)) loadOverview();
    if (state.view === "evidence") renderEvidence();
    if (state.view === "tasks") renderTasks();
    if (state.view === "traceguard") loadHandling();
    if (state.view === "links") loadRelationships();
    if (state.view === "scene") loadMarkers();
    if (state.view === "reports") loadReports();
  }

  async function refreshCaseData() {
    const item = activeCase();
    state.evidence = [];
    state.tasks = [];
    byId("evidence-case-label").textContent = item ? item.case_number : "Select a case";
    byId("scene-case-label").textContent = item ? `${item.case_number} · ${item.title}` : "Select a case";
    if (!item) {
      state.activeEvidence = null;
      renderEvidence(); renderTasks(); renderEvidenceOptions();
      return;
    }
    const [evidenceResult, taskResult] = await Promise.all([
      api(`/api/cases/${item.id}/evidence`), api(`/api/cases/${item.id}/tasks`),
    ]);
    state.evidence = evidenceResult.items;
    state.tasks = taskResult.items;
    if (!state.evidence.some((entry) => entry.id === state.activeEvidence)) state.activeEvidence = state.evidence[0]?.id || null;
    renderEvidence(); renderTasks(); renderEvidenceOptions();
  }

  async function loadOverview() {
    try {
      const stats = await api("/api/dashboard/stats");
      const cards = [["ACTIVE CASES", stats.active_cases, "open or in progress"], ["EVIDENCE RECORDS", stats.evidence_records, "stored in assigned cases"], ["PENDING TASKS", stats.pending_tasks, "checklist items"], ["AWAITING REVIEW", stats.awaiting_review, "case status"]];
      byId("stats-grid").innerHTML = cards.map(([label, value, note]) => `<div class="stat-card"><span class="stat-label">${label}</span><strong class="stat-value">${value}<span class="stat-sub">${note}</span></strong></div>`).join("");
      const recent = [...state.cases].sort((a, b) => b.updated_at.localeCompare(a.updated_at)).slice(0, 5);
      byId("recent-cases").innerHTML = recent.length ? recent.map((item) => `<div class="case-row" data-case-id="${item.id}"><div class="case-primary"><strong>${escapeHtml(item.title)}</strong><small>${escapeHtml(item.case_number)}</small></div><span class="case-type">${escapeHtml(item.case_type)}</span><span class="status-pill ${caseStatusClass(item.status)}">${escapeHtml(item.status)}</span><span class="case-arrow">→</span></div>`).join("") : '<div class="empty-state compact-empty"><strong>No case records yet</strong><p>Create a case to begin.</p></div>';
      const pending = state.tasks.filter((task) => task.status !== "Completed").slice(0, 4);
      byId("overview-tasks").innerHTML = pending.length ? pending.map((task) => `<div class="task-row"><span class="task-check" aria-hidden="true">○</span><div><div class="task-title">${escapeHtml(task.title)}</div><div class="task-meta">${escapeHtml(task.priority)} · ${task.due_date || "No due date"}</div></div></div>`).join("") : '<div class="empty-state compact-empty"><strong>No open tasks</strong><p>Select a case to view its queue.</p></div>';
    } catch (error) { notify(error.message, true); }
  }

  function renderEvidence() {
    const list = byId("evidence-list");
    byId("evidence-count").textContent = state.evidence.length;
    list.innerHTML = state.evidence.map((item) => `<button class="evidence-row ${item.id === state.activeEvidence ? "selected" : ""}" data-evidence-id="${item.id}"><span class="evidence-icon">${item.mime_type.startsWith("image/") ? "▧" : "▤"}</span><span><strong>${escapeHtml(item.evidence_number)}</strong><small>${escapeHtml(item.category)} · ${escapeHtml(item.original_filename)}</small></span><time>${new Date(item.uploaded_at).toLocaleDateString()}</time></button>`).join("");
    byId("evidence-empty").classList.toggle("hidden", state.evidence.length > 0);
    if (state.activeEvidence) renderEvidenceDetail();
    else byId("evidence-detail").innerHTML = '<div class="panel-heading"><div><p class="eyebrow">RECORD DETAILS</p><h2>Evidence detail</h2></div></div><div class="detail-placeholder"><span class="detail-icon">▣</span><p>Select an evidence item to inspect its record, integrity, handling, and analysis status.</p></div>';
    renderEvidenceOptions();
  }

  async function loadEvidence() {
    if (!state.activeCase) {
      renderEvidence();
      return;
    }
    try {
      const result = await api(`/api/cases/${state.activeCase}/evidence`);
      state.evidence = result.items;
      if (!state.evidence.some((item) => item.id === state.activeEvidence)) state.activeEvidence = state.evidence[0]?.id || null;
      renderEvidence();
    } catch (error) { notify(error.message, true); }
  }

  function renderEvidenceDetail() {
    const item = state.evidence.find((entry) => entry.id === state.activeEvidence);
    if (!item) return;
    const preview = item.mime_type.startsWith("image/") ? `<img class="preview-image" src="/api/evidence/${item.id}/preview" alt="Preview of ${escapeHtml(item.original_filename)}">` : "";
    byId("evidence-detail").innerHTML = `<div class="panel-heading"><div><p class="eyebrow">${escapeHtml(item.case_number)} · ${escapeHtml(item.category)}</p><h2>Evidence detail</h2></div><span class="status-pill">${escapeHtml(item.verification_status)}</span></div><div class="evidence-detail-card"><h3>${escapeHtml(item.evidence_number)}</h3><div class="evidence-description">${escapeHtml(item.description || "No description recorded.")}</div>${preview}<div class="detail-grid"><div class="detail-cell"><span>ORIGINAL FILE</span><strong>${escapeHtml(item.original_filename)}</strong></div><div class="detail-cell"><span>SIZE / TYPE</span><strong>${(item.file_size / 1024).toFixed(1)} KB · ${escapeHtml(item.mime_type)}</strong></div><div class="detail-cell"><span>UPLOADED</span><strong>${new Date(item.uploaded_at).toLocaleString()}</strong></div><div class="detail-cell"><span>EXAMINATION</span><strong>${escapeHtml(item.examination_status)}</strong></div></div><div class="eyebrow">ORIGINAL SHA-256</div><div class="hash-box">${escapeHtml(item.sha256_hash)}</div><div class="detail-actions"><button class="button button-quiet button-small" data-action="integrity" data-id="${item.id}">Verify integrity</button><button class="button button-quiet button-small" data-action="analyze" data-id="${item.id}">Image metadata</button><a class="button button-quiet button-small" href="/api/evidence/${item.id}/download">Download original</a><button class="button button-quiet button-small" data-action="open-traceguard">Handling history</button></div><div id="analysis-results"></div></div>`;
    loadAnalysis(item.id);
  }

  async function loadAnalysis(evidenceId) {
    try {
      const result = await api(`/api/evidence/${evidenceId}/analysis`);
      const target = byId("analysis-results");
      if (!target || !result.items.length) return;
      target.innerHTML = `<div class="analysis-box"><strong>Recorded image metadata</strong><br>${result.items.map((row) => `${escapeHtml(row.result.width)} × ${escapeHtml(row.result.height)} px · ${escapeHtml(row.result.format)} · Review: ${escapeHtml(row.review_status)}`).join("<br>")}<br><span>Object detection is unavailable; no detections were generated.</span></div>`;
    } catch { /* Detail remains useful if analysis history is unavailable. */ }
  }

  function renderEvidenceOptions() {
    const optionMarkup = state.evidence.map((item) => `<option value="${item.id}">${escapeHtml(item.evidence_number)} · ${escapeHtml(item.category)}</option>`).join("");
    ["handling-evidence-select", "marker-form", "relationship-form"].forEach((id) => {
      const parent = byId(id);
      if (!parent) return;
      const selects = parent.tagName === "SELECT" ? [parent] : parent.querySelectorAll("select");
      selects.forEach((select) => {
        const old = select.value;
        select.innerHTML = optionMarkup || '<option value="">No evidence items</option>';
        if ([...select.options].some((option) => option.value === old)) select.value = old;
      });
    });
  }

  function initializeReferenceCheck() {
    const view = byId("view-links");
    if (!view || byId("reference-check-button")) return;
    const button = document.createElement("button");
    button.id = "reference-check-button";
    button.className = "button button-quiet";
    button.dataset.action = "analyze-references";
    button.textContent = "Check ID references";
    view.querySelector(".page-intro").append(button);
    const output = document.createElement("div");
    output.id = "reference-results";
    output.className = "reference-results hidden";
    view.querySelector(".page-intro").after(output);
  }

  async function loadTasks() {
    if (!state.activeCase) { renderTasks(); return; }
    try { state.tasks = (await api(`/api/cases/${state.activeCase}/tasks`)).items; renderTasks(); }
    catch (error) { notify(error.message, true); }
  }

  function renderTasks() {
    byId("task-count").textContent = state.tasks.length;
    byId("task-list").innerHTML = state.tasks.map((task) => `<div class="task-row ${task.status === "Completed" ? "completed" : ""}"><input class="task-check" type="checkbox" data-task-id="${task.id}" aria-label="Mark ${escapeHtml(task.title)} complete" ${task.status === "Completed" ? "checked" : ""}><div><div class="task-title">${escapeHtml(task.title)}</div><div class="task-meta">${escapeHtml(task.priority)} · ${task.due_date || "No due date"}</div></div><span class="task-state">${escapeHtml(task.status)}</span></div>`).join("");
    byId("tasks-empty").classList.toggle("hidden", state.tasks.length > 0);
  }

  async function loadHandling() {
    renderEvidenceOptions();
    const evidenceId = byId("handling-evidence-select").value || state.activeEvidence;
    const timeline = byId("handling-timeline");
    if (!evidenceId) { timeline.innerHTML = ""; byId("risk-warnings").innerHTML = ""; byId("handling-empty").classList.remove("hidden"); return; }
    byId("handling-evidence-select").value = evidenceId;
    try {
      const [events, screen] = await Promise.all([api(`/api/evidence/${evidenceId}/handling`), api(`/api/evidence/${evidenceId}/risk-checks`)]);
      timeline.innerHTML = events.items.map((event) => `<div class="timeline-item"><strong>${escapeHtml(event.action)}</strong><small>${event.event_timestamp ? new Date(event.event_timestamp).toLocaleString() : "Timestamp not recorded"} · ${escapeHtml(event.actor)}${event.recorded_location ? ` · ${escapeHtml(event.recorded_location)}` : ""}</small>${event.new_custodian || event.previous_custodian ? `<small>${escapeHtml(event.previous_custodian || "Unknown")} → ${escapeHtml(event.new_custodian || "Not recorded")}</small>` : ""}${event.notes ? `<p>${escapeHtml(event.notes)}</p>` : ""}</div>`).join("");
      byId("handling-empty").classList.toggle("hidden", events.items.length > 0);
      byId("risk-warnings").innerHTML = screen.warnings.length ? screen.warnings.map((warning) => `<div class="warning-item"><strong>${escapeHtml(warning.rule)} · ${escapeHtml(warning.review_status)}</strong>${escapeHtml(warning.explanation)}${warning.related_event_ids.length && warning.review_status !== "Resolved" ? ` <button class="text-button" data-action="review-warning" data-ids="${warning.related_event_ids.join(",")}">${warning.review_status === "Reviewed" ? "Resolve" : "Mark reviewed"}</button>` : ""}</div>`).join("") : '<div class="warning-empty">No configured documentation prompts were returned for these recorded events.</div>';
    } catch (error) { notify(error.message, true); }
  }

  async function loadRelationships() {
    renderEvidenceOptions();
    const svg = byId("evidence-graph");
    if (!state.activeCase) { svg.replaceChildren(); byId("graph-empty").classList.remove("hidden"); return; }
    try {
      const [graph, relationResult] = await Promise.all([api(`/api/cases/${state.activeCase}/evidence-graph`), api(`/api/cases/${state.activeCase}/relationships`)]);
      drawGraph(graph);
      byId("relationship-list").innerHTML = relationResult.items.map((relation) => `<div class="relationship-item"><strong>${escapeHtml(relation.source.evidence_number)} ↔ ${escapeHtml(relation.target.evidence_number)}</strong><small>${escapeHtml(relation.relationship_type)} · ${escapeHtml(relation.source_type)} · ${escapeHtml(relation.verification_status)}</small>${relation.verification_status !== "Accepted" ? `<button class="text-button" data-action="review-relationship" data-id="${relation.id}" data-status="Accepted">Accept review</button> ` : ""}${relation.verification_status !== "Rejected" ? `<button class="text-button" data-action="review-relationship" data-id="${relation.id}" data-status="Rejected">Reject</button>` : ""}</div>`).join("");
    } catch (error) { notify(error.message, true); }
  }

  function drawGraph(graph) {
    const svg = byId("evidence-graph");
    const namespace = "http://www.w3.org/2000/svg";
    svg.replaceChildren();
    graphViewport.x = 0; graphViewport.y = 0; graphViewport.width = 900; graphViewport.height = 460;
    svg.setAttribute("viewBox", "0 0 900 460");
    byId("graph-empty").classList.toggle("hidden", graph.nodes.length > 0);
    if (!graph.nodes.length) return;
    const positions = new Map();
    const cx = 450, cy = 226, radius = Math.min(155, 32 + graph.nodes.length * 22);
    graph.nodes.forEach((node, index) => {
      const angle = -Math.PI / 2 + (index * Math.PI * 2 / graph.nodes.length);
      positions.set(node.id, { x: cx + Math.cos(angle) * radius, y: cy + Math.sin(angle) * radius });
    });
    const edgeCounts = new Map();
    graph.edges.forEach((edge) => {
      const pair = [edge.source, edge.target].sort((a, b) => a - b).join(":");
      edgeCounts.set(pair, (edgeCounts.get(pair) || 0) + 1);
    });
    const edgeIndexes = new Map();
    graph.edges.forEach((edge) => {
      const start = positions.get(edge.source), end = positions.get(edge.target);
      const pair = [edge.source, edge.target].sort((a, b) => a - b).join(":");
      const edgeIndex = edgeIndexes.get(pair) || 0;
      edgeIndexes.set(pair, edgeIndex + 1);
      const offset = (edgeIndex - (edgeCounts.get(pair) - 1) / 2) * 12;
      const deltaX = end.x - start.x, deltaY = end.y - start.y;
      const length = Math.hypot(deltaX, deltaY) || 1;
      const offsetX = -deltaY / length * offset, offsetY = deltaX / length * offset;
      const line = document.createElementNS(namespace, "line");
      line.setAttribute("x1", start.x + offsetX); line.setAttribute("y1", start.y + offsetY); line.setAttribute("x2", end.x + offsetX); line.setAttribute("y2", end.y + offsetY); line.setAttribute("class", "graph-edge");
      svg.append(line);
      const label = document.createElementNS(namespace, "text");
      label.setAttribute("x", (start.x + end.x) / 2 + offsetX); label.setAttribute("y", (start.y + end.y) / 2 + offsetY - 7); label.setAttribute("class", "graph-edge-label"); label.setAttribute("text-anchor", "middle"); label.textContent = edge.label;
      svg.append(label);
    });
    graph.nodes.forEach((node) => {
      const point = positions.get(node.id);
      const group = document.createElementNS(namespace, "g");
      group.setAttribute("class", "graph-node"); group.setAttribute("tabindex", "0"); group.setAttribute("role", "button"); group.setAttribute("aria-label", `Evidence ${node.label}, ${node.category}`);
      const circle = document.createElementNS(namespace, "circle"); circle.setAttribute("cx", point.x); circle.setAttribute("cy", point.y); circle.setAttribute("r", 18);
      const text = document.createElementNS(namespace, "text"); text.setAttribute("x", point.x); text.setAttribute("y", point.y + 34); text.textContent = node.label;
      group.append(circle, text);
      const select = () => {
        state.activeEvidence = node.id;
        const evidence = state.evidence.find((item) => item.id === node.id);
        byId("graph-selection").innerHTML = `<strong>${escapeHtml(node.label)} · ${escapeHtml(node.category)}</strong><br>${escapeHtml(evidence?.description || "No description recorded.")} <button class="text-button" data-action="open-graph-evidence" data-id="${node.id}">Open evidence record →</button>`;
        document.querySelectorAll(".graph-node").forEach((item) => item.classList.remove("selected"));
        group.classList.add("selected");
      };
      group.addEventListener("click", select); group.addEventListener("keydown", (event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); select(); } });
      svg.append(group);
    });
  }

  function initializeGraphControls() {
    const svg = byId("evidence-graph");
    svg.addEventListener("wheel", (event) => {
      event.preventDefault();
      const bounds = svg.getBoundingClientRect();
      const ratio = event.deltaY > 0 ? 1.12 : 0.89;
      const nextWidth = Math.max(360, Math.min(1500, graphViewport.width * ratio));
      const nextHeight = nextWidth * (graphViewport.height / graphViewport.width);
      const xRatio = (event.clientX - bounds.left) / bounds.width;
      const yRatio = (event.clientY - bounds.top) / bounds.height;
      graphViewport.x += (graphViewport.width - nextWidth) * xRatio;
      graphViewport.y += (graphViewport.height - nextHeight) * yRatio;
      graphViewport.width = nextWidth; graphViewport.height = nextHeight;
      svg.setAttribute("viewBox", `${graphViewport.x} ${graphViewport.y} ${graphViewport.width} ${graphViewport.height}`);
    }, { passive: false });
    svg.addEventListener("pointerdown", (event) => {
      if (event.target.closest?.(".graph-node")) return;
      graphViewport.dragging = true;
      graphViewport.dragX = event.clientX;
      graphViewport.dragY = event.clientY;
      svg.setPointerCapture(event.pointerId);
    });
    svg.addEventListener("pointermove", (event) => {
      if (!graphViewport.dragging) return;
      const bounds = svg.getBoundingClientRect();
      graphViewport.x -= (event.clientX - graphViewport.dragX) * graphViewport.width / bounds.width;
      graphViewport.y -= (event.clientY - graphViewport.dragY) * graphViewport.height / bounds.height;
      graphViewport.dragX = event.clientX; graphViewport.dragY = event.clientY;
      svg.setAttribute("viewBox", `${graphViewport.x} ${graphViewport.y} ${graphViewport.width} ${graphViewport.height}`);
    });
    svg.addEventListener("pointerup", () => { graphViewport.dragging = false; });
    svg.addEventListener("pointercancel", () => { graphViewport.dragging = false; });
  }

  async function loadMarkers() {
    renderEvidenceOptions();
    if (!state.activeCase) { renderMarkers([]); return; }
    try {
      const result = await api(`/api/cases/${state.activeCase}/scene-markers`);
      state.markers = result.items;
      renderMarkers(result.items);
      window.dispatchEvent(new CustomEvent("forensight:markers", { detail: result.items }));
    } catch (error) { notify(error.message, true); }
  }

  function renderMarkers(markers) {
    byId("marker-list").innerHTML = markers.map((marker) => `<div class="marker-row"><span class="marker-swatch"></span><div><strong>${escapeHtml(marker.label)} · ${escapeHtml(marker.evidence_number)}</strong><small>X ${marker.x.toFixed(1)} · Y ${marker.y.toFixed(1)} · Z ${marker.z.toFixed(1)} <span>· approximate</span></small></div><div class="marker-actions"><button class="text-button" data-action="edit-marker" data-id="${marker.id}">Edit</button><button class="marker-delete" data-action="delete-marker" data-id="${marker.id}" aria-label="Remove ${escapeHtml(marker.label)}">×</button></div></div>`).join("");
    const select = document.querySelector("#marker-form select[name='evidence_id']");
    if (select) select.disabled = !state.evidence.length;
  }

  async function loadReports() {
    const list = byId("report-list");
    if (!state.activeCase) { list.innerHTML = ""; byId("reports-empty").classList.remove("hidden"); return; }
    try {
      const result = await api(`/api/cases/${state.activeCase}/reports`);
      list.innerHTML = result.items.map((report) => `<div class="report-row"><span class="report-icon">▧</span><span><strong>Case report · ${escapeHtml(activeCase()?.case_number || "")}</strong><small>${new Date(report.generated_at).toLocaleString()} · ${escapeHtml(report.report_type)}</small></span><a href="/api/reports/${report.id}/download">Download PDF ↗</a></div>`).join("");
      byId("reports-empty").classList.toggle("hidden", result.items.length > 0);
    } catch (error) { notify(error.message, true); }
  }

  async function loadUsers() {
    try {
      const result = await api("/api/admin/users");
      byId("users-table").innerHTML = result.items.map((user) => `<tr><td class="table-case"><strong>${escapeHtml(user.username)}</strong><small>${escapeHtml(user.email)}</small></td><td><select data-user-role="${user.id}" aria-label="Role for ${escapeHtml(user.username)}"><option ${user.role === "Administrator" ? "selected" : ""}>Administrator</option><option ${user.role === "Investigator" ? "selected" : ""}>Investigator</option><option ${user.role === "Reviewer" ? "selected" : ""}>Reviewer</option></select></td><td><input data-user-active="${user.id}" type="checkbox" aria-label="Active account for ${escapeHtml(user.username)}" ${user.is_active ? "checked" : ""}></td><td>${new Date(user.created_at).toLocaleDateString()}</td></tr>`).join("");
    } catch (error) { notify(error.message, true); }
  }

  function changeViewFromTarget(target) {
    const button = target.closest("[data-view],[data-view-link]");
    if (button) showView(button.dataset.view || button.dataset.viewLink);
  }

  document.addEventListener("click", async (event) => {
    changeViewFromTarget(event.target);
    const caseRow = event.target.closest("[data-case-id]");
    if (caseRow) selectCase(caseRow.dataset.caseId);
    const evidenceRow = event.target.closest("[data-evidence-id]");
    if (evidenceRow && evidenceRow.classList.contains("evidence-row")) {
      state.activeEvidence = Number(evidenceRow.dataset.evidenceId); renderEvidence();
    }
    const action = event.target.closest("[data-action]");
    if (!action) return;
    if (action.dataset.action === "case-prev" && state.casePage > 1) return loadCases(state.casePage - 1);
    if (action.dataset.action === "case-next" && state.casePage < state.casePages) return loadCases(state.casePage + 1);
    if (action.dataset.action === "new-case") {
      showView("cases");
      byId("case-create-panel").classList.remove("hidden");
    }
    if (action.dataset.action === "close-case-form") byId("case-create-panel").classList.add("hidden");
    if (action.dataset.action === "open-traceguard") showView("traceguard");
    if (action.dataset.action === "open-graph-evidence") {
      state.activeEvidence = Number(action.dataset.id);
      showView("evidence");
      loadEvidence();
    }
    if (action.dataset.action === "edit-marker") {
      const marker = state.markers.find((item) => item.id === Number(action.dataset.id));
      if (!marker) return;
      const form = byId("marker-form");
      form.dataset.editMarkerId = marker.id;
      form.elements.evidence_id.value = marker.evidence_id;
      form.elements.label.value = marker.label;
      form.elements.x.value = marker.x;
      form.elements.y.value = marker.y;
      form.elements.z.value = marker.z;
      form.elements.description.value = marker.description;
      const submit = form.querySelector('button[type="submit"]');
      submit.dataset.originalLabel = "Save marker";
      submit.textContent = "Save marker";
      form.scrollIntoView({ behavior: "smooth", block: "center" });
    }
    if (action.dataset.action === "integrity") {
      try {
        const result = await api(`/api/evidence/${action.dataset.id}/verify-integrity`, { method: "POST" });
        notify(result.matches ? "File hash matches the stored upload hash." : result.message, !result.matches);
        await refreshCaseData();
      } catch (error) { notify(error.message, true); }
    }
    if (action.dataset.action === "analyze") {
      try {
        const result = await api(`/api/evidence/${action.dataset.id}/analyze`, { method: "POST" });
        notify(`Image metadata recorded: ${result.analysis.result.width} × ${result.analysis.result.height} px. Object detection unavailable.`);
        renderEvidenceDetail();
      } catch (error) { notify(error.message, true); }
    }
    if (action.dataset.action === "delete-marker") {
      if (!window.confirm("Remove this scene marker?")) return;
      try { await api(`/api/scene-markers/${action.dataset.id}`, { method: "DELETE" }); await loadMarkers(); notify("Scene marker removed."); }
      catch (error) { notify(error.message, true); }
    }
    if (action.dataset.action === "review-warning") {
      const nextStatus = action.textContent.trim() === "Resolve" ? "Resolved" : "Reviewed";
      try {
        for (const id of action.dataset.ids.split(",")) await api(`/api/handling/${id}/review`, { method: "PATCH", body: JSON.stringify({ review_status: nextStatus }) });
        await loadHandling(); notify(`Documentation prompt marked ${nextStatus.toLowerCase()}.`);
      } catch (error) { notify(error.message, true); }
    }
    if (action.dataset.action === "review-relationship") {
      try {
        await api(`/api/relationships/${action.dataset.id}`, { method: "PATCH", body: JSON.stringify({ verification_status: action.dataset.status }) });
        await loadRelationships(); notify(`Relationship marked ${action.dataset.status.toLowerCase()}.`);
      } catch (error) { notify(error.message, true); }
    }
    if (action.dataset.action === "analyze-references") {
      if (!state.activeCase) return notify("Select a case first.", true);
      try {
        const result = await api(`/api/cases/${state.activeCase}/analyze-report`, { method: "POST", body: JSON.stringify({}) });
        const output = byId("reference-results");
        const matches = result.references.map((reference) => `<div class="reference-row">${escapeHtml(reference.source)} references <strong>${escapeHtml(reference.referenced_evidence_number)}</strong></div>`).join("");
        const warnings = result.warnings.map((warning) => `<div class="warning-item"><strong>${escapeHtml(warning.rule)} · ${escapeHtml(warning.source)}</strong>${escapeHtml(warning.explanation)} <span class="mono">${escapeHtml(warning.referenced_identifier)}</span></div>`).join("");
        output.innerHTML = `<div class="reference-title"><strong>Identifier pattern scan</strong><span>${escapeHtml(result.nlp.message)}</span></div>${matches || '<div class="reference-row">No explicit evidence-ID references found.</div>'}${warnings}`;
        output.classList.remove("hidden");
      } catch (error) { notify(error.message, true); }
    }
  });
  document.addEventListener("change", async (event) => {
    const roleControl = event.target.closest("[data-user-role]");
    const activeControl = event.target.closest("[data-user-active]");
    const control = roleControl || activeControl;
    if (!control) return;
    const id = roleControl?.dataset.userRole || activeControl?.dataset.userActive;
    const values = roleControl ? { role: roleControl.value } : { is_active: activeControl.checked };
    try {
      await api(`/api/admin/users/${id}/role`, { method: "PATCH", body: JSON.stringify(values) });
      notify("User access updated.");
      await loadUsers();
    } catch (error) { notify(error.message, true); await loadUsers(); }
  });

  byId("auth-switch").addEventListener("click", () => switchAuthMode(byId("register-form").classList.contains("hidden")));
  initializeReferenceCheck();
  initializeCasePagination();
  initializeGraphControls();
  window.addEventListener("forensight:marker-selected", (event) => {
    state.activeEvidence = event.detail.evidence_id;
    showView("evidence");
    loadEvidence();
  });
  byId("login-form").addEventListener("submit", (event) => {
    event.preventDefault();
    withForm(event.currentTarget, async () => {
      const response = await api("/api/auth/login", { method: "POST", body: JSON.stringify(formObject(event.currentTarget)) });
      enterWorkspace(response.user);
    });
  });
  byId("register-form").addEventListener("submit", (event) => {
    event.preventDefault();
    withForm(event.currentTarget, async () => {
      const response = await api("/api/auth/register", { method: "POST", body: JSON.stringify(formObject(event.currentTarget)) });
      enterWorkspace(response.user);
    });
  });
  byId("logout-button").addEventListener("click", async () => {
    try { await api("/api/auth/logout", { method: "POST" }); sessionStorage.removeItem("forensight-active-case"); location.reload(); }
    catch (error) { notify(error.message, true); }
  });
  byId("case-selector").addEventListener("change", (event) => selectCase(event.target.value));
  byId("menu-toggle").addEventListener("click", () => byId("sidebar").classList.toggle("open"));
  byId("notice-dismiss").addEventListener("click", () => byId("notice-dismiss").parentElement.remove());

  byId("case-form").addEventListener("submit", (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    withForm(form, async () => {
      const result = await api("/api/cases", { method: "POST", body: JSON.stringify(formObject(form)) });
      form.reset(); byId("case-create-panel").classList.add("hidden"); await loadCases(1); await selectCase(result.case.id); showView("cases"); notify("Case record created.");
    });
  });
  byId("case-edit-form").addEventListener("submit", (event) => {
    event.preventDefault();
    if (!state.activeCase) return notify("Select a case before editing it.", true);
    const form = event.currentTarget;
    const caseId = state.activeCase;
    withForm(form, async () => {
      const result = await api(`/api/cases/${caseId}`, { method: "PUT", body: JSON.stringify(formObject(form)) });
      state.caseCache.set(caseId, result.case);
      await loadCases();
      await selectCase(caseId);
      notify("Case record updated.");
    });
  });
  let searchTimer;
  byId("case-search").addEventListener("input", () => { clearTimeout(searchTimer); searchTimer = setTimeout(() => loadCases(1), 220); });
  byId("case-status-filter").addEventListener("change", () => loadCases(1));
  byId("evidence-form").addEventListener("submit", (event) => {
    event.preventDefault();
    if (!state.activeCase) return notify("Select a case before adding evidence.", true);
    const form = event.currentTarget;
    withForm(form, async () => {
      const result = await api(`/api/cases/${state.activeCase}/evidence`, { method: "POST", body: new FormData(form) });
      form.reset(); state.activeEvidence = result.evidence.id; await refreshCaseData(); notify("Evidence record stored with a SHA-256 hash.");
    });
  });
  byId("task-form").addEventListener("submit", (event) => {
    event.preventDefault();
    if (!state.activeCase) return notify("Select a case before adding a task.", true);
    const form = event.currentTarget;
    withForm(form, async () => {
      await api(`/api/cases/${state.activeCase}/tasks`, { method: "POST", body: JSON.stringify(formObject(form)) });
      form.reset(); await loadTasks(); if (state.view === "overview") loadOverview(); notify("Investigation task added.");
    });
  });
  byId("task-list").addEventListener("change", async (event) => {
    const checkbox = event.target.closest("[data-task-id]");
    if (!checkbox) return;
    try { await api(`/api/tasks/${checkbox.dataset.taskId}`, { method: "PATCH", body: JSON.stringify({ status: checkbox.checked ? "Completed" : "Pending" }) }); await loadTasks(); }
    catch (error) { checkbox.checked = !checkbox.checked; notify(error.message, true); }
  });
  byId("handling-evidence-select").addEventListener("change", loadHandling);
  byId("handling-form").addEventListener("submit", (event) => {
    event.preventDefault();
    const evidenceId = byId("handling-evidence-select").value;
    if (!evidenceId) return notify("Select an evidence item first.", true);
    const form = event.currentTarget;
    const values = formObject(form);
    if (values.event_timestamp) values.event_timestamp = new Date(values.event_timestamp).toISOString();
    withForm(form, async () => {
      await api(`/api/evidence/${evidenceId}/handling`, { method: "POST", body: JSON.stringify(values) }); form.reset(); await loadHandling(); notify("Handling event recorded.");
    });
  });
  byId("relationship-form").addEventListener("submit", (event) => {
    event.preventDefault();
    if (!state.activeCase) return notify("Select a case first.", true);
    const form = event.currentTarget;
    withForm(form, async () => {
      await api(`/api/cases/${state.activeCase}/relationships`, { method: "POST", body: JSON.stringify(formObject(form)) }); form.reset(); await loadRelationships(); notify("Evidence relationship recorded.");
    });
  });
  byId("marker-form").addEventListener("submit", (event) => {
    event.preventDefault();
    if (!state.activeCase) return notify("Select a case first.", true);
    const form = event.currentTarget;
    withForm(form, async () => {
      const markerId = form.dataset.editMarkerId;
      const url = markerId ? `/api/scene-markers/${markerId}` : `/api/cases/${state.activeCase}/scene-markers`;
      await api(url, { method: markerId ? "PUT" : "POST", body: JSON.stringify(formObject(form)) });
      delete form.dataset.editMarkerId;
      const button = form.querySelector('button[type="submit"]');
      button.dataset.originalLabel = "＋ Place marker";
      button.textContent = button.dataset.originalLabel;
      form.reset();
      await loadMarkers();
      notify(markerId ? "Scene marker updated." : "Approximate scene marker saved.");
    });
  });
  byId("generate-report").addEventListener("click", async (event) => {
    if (!state.activeCase) return notify("Select a case before generating a report.", true);
    const button = event.currentTarget;
    button.disabled = true;
    try { await api(`/api/cases/${state.activeCase}/reports`, { method: "POST", body: JSON.stringify({}) }); await loadReports(); notify("PDF report generated from stored case records."); }
    catch (error) { notify(error.message, true); }
    finally { button.disabled = false; }
  });
  byId("handling-evidence-select").addEventListener("focus", renderEvidenceOptions);

  if (document.body.dataset.authenticated === "true") {
    api("/api/auth/me").then((result) => { if (result.user) enterWorkspace(result.user); }).catch(() => {});
  }
})();