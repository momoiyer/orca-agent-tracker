"use strict";
(() => {
  const $ = id => document.getElementById(id);
  let snapshot = null;
  let busy = false;
  let failed = false;
  let timer = null;
  const states = new Set(["working", "waiting", "idle", "stopped", "unknown", "recent"]);
  const element = (tag, className, text) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  };
  const normalState = value => states.has(value) ? value : "unknown";
  const display = value => String(value || "Unknown");
  const titleCase = value => display(value).replace(/(^|[ -])\w/g, part => part.toUpperCase());
  function timestamp(value) {
    if (!value) return null;
    const result = typeof value === "number" ? new Date(value < 1e12 ? value * 1000 : value) : new Date(value);
    return Number.isNaN(result.getTime()) ? null : result;
  }
  function age(value) {
    const date = timestamp(value);
    if (!date) return "Time unavailable";
    const seconds = Math.max(0, Math.floor((Date.now() - date.getTime()) / 1000));
    if (seconds < 10) return "Just now";
    if (seconds < 60) return `${seconds}s ago`;
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
    if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
    return `${Math.floor(seconds / 86400)}d ago`;
  }
  function observation(agent, compact = false) {
    const node = element("div", compact ? "recent-observed" : "observation-cell");
    node.append(element("div", "observed", age(agent.updated_at)));
    const date = timestamp(agent.updated_at);
    node.append(element("div", "observed-date", date ? date.toLocaleString([], {month:"short",day:"numeric",hour:"2-digit",minute:"2-digit"}) : "No timestamp"));
    return node;
  }
  function badge(state) { return element("span", `state-badge ${state}`, state === "recent" ? "History" : titleCase(state)); }
  function isHistory(agent) { return ["recent", "stopped"].includes(normalState(agent.state)); }
  function isOpen(agent) { return ["working", "waiting", "idle"].includes(normalState(agent.state)); }
  function matches(agent) {
    const query = $("search").value.toLocaleLowerCase().trim();
    return (!query || [agent.provider, agent.role, agent.project, agent.path, agent.task, agent.id].some(value => String(value || "").toLocaleLowerCase().includes(query))) &&
      (!$("provider").value || agent.provider === $("provider").value) &&
      (!$("state").value || normalState(agent.state) === $("state").value) &&
      (!$("project").value || (agent.path || agent.project) === $("project").value);
  }
  function fillSelect(id, values) {
    const select = $(id), previous = select.value;
    const first = select.options[0].cloneNode(true);
    select.replaceChildren(first);
    for (const [value,label] of values) {
      const option = element("option", "", label); option.value = value; select.append(option);
    }
    if ([...select.options].some(option => option.value === previous)) select.value = previous;
  }
  function renderSession(agent) {
    const row = element("article", "session-row");
    row.setAttribute("aria-label", `${titleCase(agent.provider)} in ${display(agent.project)}: ${normalState(agent.state)}`);
    const identity = element("div", "identity-cell");
    const name = element("div", "agent-name");
    const mark = element("span", `provider-mark ${agent.provider === "claude" ? "claude" : ""}`, agent.provider === "claude" ? "C" : agent.provider === "codex" ? "⌘" : display(agent.provider).slice(0,1).toUpperCase());
    mark.setAttribute("aria-hidden", "true");
    name.append(mark, document.createTextNode(titleCase(agent.provider)));
    identity.append(name, element("div", "agent-role", agent.role ? titleCase(agent.role) : "Role not reported"), element("div", "session-id", agent.id));
    if (agent.parent_id) identity.append(element("div", "session-id", `Child of ${String(agent.parent_id).slice(0,12)}`));
    const assignment = element("div", "assignment-cell");
    assignment.append(element("div", "project-name", agent.project || "Project not reported"), element("div", "task-text", agent.task || "Assignment not reported by this source."));
    if (agent.path) assignment.append(element("div", "session-path", agent.path));
    const state = element("div", "state-cell");
    state.append(badge(normalState(agent.state)), element("div", "source-name", agent.source || "Source not reported"));
    if (agent.confidence) state.append(element("div", "source-name", agent.confidence));
    row.append(identity, assignment, state, observation(agent));
    return row;
  }
  function renderRecent(agent) {
    const row = element("article", "recent-row");
    const body = element("div", "recent-content");
    const heading = element("div", "recent-title", titleCase(agent.provider));
    heading.append(element("span", "muted", agent.project || "Project not reported"), badge(normalState(agent.state)));
    body.append(heading, element("div", "recent-task", agent.task || agent.role || "Assignment not reported"));
    row.append(body, observation(agent, true)); return row;
  }
  function renderAgents() {
    if (!snapshot) return;
    const agents = snapshot.agents.filter(matches);
    const current = agents.filter(agent => !isHistory(agent));
    const recent = agents.filter(isHistory);
    $("sessions").replaceChildren(...(current.length ? current.map(renderSession) : [element("p", "empty", snapshot.agents.length ? "No current sessions match these filters." : "No current sessions reported. Sources will update this view when activity is observed.")]));
    $("recent").replaceChildren(...(recent.length ? recent.map(renderRecent) : [element("p", "empty", "No matching recent sessions.")]));
    $("session-total").textContent = String(current.length);
  }
  function renderProjects() {
    const agents = snapshot.agents;
    const cards = snapshot.projects.map(project => {
      const card = element("article", "project-card");
      card.append(element("h3", "", project.name || project.path), element("p", "", project.path || "Path unavailable"));
      const meta = element("div", "project-meta");
      const sessions = agents.filter(agent => isOpen(agent) && agent.path === project.path);
      meta.append(element("span", "branch", project.branch ? `⑂ ${project.branch}` : "Branch unavailable"), element("span", "project-agents", `${sessions.length} open ${sessions.length === 1 ? "session" : "sessions"}`));
      card.append(meta); return card;
    });
    $("project-list").replaceChildren(...(cards.length ? cards : [element("p", "empty", "No projects discovered yet.")]));
  }
  function renderSources() {
    const errors = snapshot.sources.filter(source => !source.ok);
    const alert = $("source-alert");
    alert.hidden = !failed && !snapshot.stale && !errors.length;
    if (failed || snapshot.stale) alert.textContent = "Live refresh is unavailable. Showing the last successful snapshot; session states may be out of date. Retrying automatically.";
    else alert.textContent = errors.map(source => `${source.name}: ${source.error || "source unavailable"}`).join(" · ");
    $("source-list").replaceChildren(...snapshot.sources.map(source => {
      const row = element("div", "source-row");
      row.append(element("span", "", source.name), element("span", source.ok ? "source-ok" : "source-error", source.ok ? "Connected" : "Unavailable"));
      if (source.error) row.title = String(source.error);
      return row;
    }));
    const connection = $("connection");
    connection.className = `connection ${failed || snapshot.stale || errors.length ? "stale" : ""}`;
    connection.textContent = failed || snapshot.stale ? "Snapshot is out of date" : errors.length ? "Live view · some sources unavailable" : "Live view · local sources connected";
  }
  function render() {
    const agents = snapshot.agents;
    $("working-count").textContent = String(agents.filter(agent => agent.state === "working").length);
    $("waiting-count").textContent = String(agents.filter(agent => agent.state === "waiting").length);
    $("open-count").textContent = String(agents.filter(isOpen).length);
    $("project-count").textContent = String(snapshot.projects.length);
    $("updated").textContent = `Snapshot ${age(snapshot.updated_at)}`;
    fillSelect("provider", [...new Set(agents.map(agent => agent.provider).filter(Boolean))].sort().map(value => [value,titleCase(value)]));
    const projects = new Map(agents.map(agent => [agent.path || agent.project, agent.project || agent.path]).filter(([value]) => value));
    fillSelect("project", [...projects].sort((a,b) => String(a[1]).localeCompare(String(b[1]))));
    renderAgents(); renderProjects(); renderSources();
    $("role-list").replaceChildren(...(snapshot.roles.length ? snapshot.roles.map(role => {
      const row = element("div", "role-row"); row.append(element("strong", "", role.name),element("p", "", role.description)); return row;
    }) : [element("p", "empty", "No specialist role definitions found.")]));
    for (const provider of ["codex", "claude"]) {
      const node = $(`${provider}-policy`), ready = snapshot.policy[provider] === true;
      node.textContent = ready ? "Installed" : "Not confirmed";
      node.className = `policy-status ${ready ? "ready" : "missing"}`;
    }
    $("interval-label").textContent = `Refreshes automatically every ${Math.max(2, Number(snapshot.interval) || 5)} seconds.`;
  }
  async function refresh() {
    if (busy) return;
    busy = true; $("refresh").disabled = true;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 15000);
    try {
      const response = await fetch("/api/status", {cache:"no-store", credentials:"same-origin", signal:controller.signal});
      if (!response.ok) throw new Error(`Status ${response.status}`);
      const data = await response.json();
      if (!data || !Array.isArray(data.agents) || !Array.isArray(data.projects) || !Array.isArray(data.sources)) throw new Error("Invalid snapshot");
      const stale = data.stale === true || !timestamp(data.updated_at) || Date.now() - timestamp(data.updated_at).getTime() > 20000;
      snapshot = {...data, stale, agents:data.agents.map(agent => stale && ["working","waiting","idle"].includes(agent.state) ? {...agent,state:"unknown",confidence:"stale observation"} : agent), roles:Array.isArray(data.roles) ? data.roles : [], policy:data.policy || {}};
      const recovered = failed; failed = false; render();
      if (recovered) $("announcer").textContent = "Live agent activity is connected again.";
    } catch (_) {
      failed = true;
      if (snapshot) {
        snapshot = {...snapshot, stale:true, agents:snapshot.agents.map(agent => ["working","waiting","idle"].includes(agent.state) ? {...agent,state:"unknown",confidence:"stale observation"} : agent)};
        render();
      }
      else {
        $("source-alert").hidden = false;
        $("source-alert").textContent = "Cannot connect to the local tracker. Check that the dashboard service is running. Retrying automatically.";
        $("connection").className = "connection stale";
        $("connection").textContent = "Local tracker unavailable";
        $("sessions").replaceChildren(element("p", "empty", "No verified session data is available yet."));
      }
      $("announcer").textContent = "Live refresh is unavailable. Displayed activity may be out of date.";
    } finally {
      clearTimeout(timeout); busy = false; $("refresh").disabled = false;
      clearTimeout(timer); timer = setTimeout(refresh, Math.max(2, Number(snapshot && snapshot.interval) || 5) * 1000);
    }
  }
  $("refresh").addEventListener("click", refresh);
  for (const id of ["search", "provider", "state", "project"]) $(id).addEventListener(id === "search" ? "input" : "change", renderAgents);
  document.addEventListener("visibilitychange", () => {if (!document.hidden) refresh();});
  refresh();
})();
