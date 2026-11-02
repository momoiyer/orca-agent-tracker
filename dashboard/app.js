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
  let selectedAgent = null;
  const camera = {angle:-26, tilt:54, zoom:1, width:600, height:400};
  const agentKey = agent => JSON.stringify([agent.provider,agent.id,agent.source]);
  function updateCamera() {
    const viewport = $("world-viewport");
    const fit = Math.min((viewport.clientWidth - 40) / (camera.width + camera.height * .5), (viewport.clientHeight - 80) / (camera.height * .65 + camera.width * .35 + 80), 1.4);
    const world = $("world");
    world.style.setProperty("--angle", `${camera.angle}deg`);
    world.style.setProperty("--tilt", `${camera.tilt}deg`);
    world.style.setProperty("--unangle", `${-camera.angle}deg`);
    world.style.setProperty("--untilt", `${-camera.tilt}deg`);
    world.style.transform = `translate(-50%,-50%) scale(${Math.max(.12,fit) * camera.zoom}) rotateX(${camera.tilt}deg) rotateZ(${camera.angle}deg)`;
  }
  function solid(className, width, length, height, x, y, z) {
    const box = element("span", `solid ${className}`);
    box.style.cssText = `--w:${width}px;--l:${length}px;--h:${height}px;transform:translate3d(${x}px,${y}px,${z}px)`;
    box.setAttribute("aria-hidden", "true");
    for (const face of ["top","front","side","back","left","bottom"]) box.append(element("span",`solid-${face}`));
    return box;
  }
  function inspectAgent(agent) {
    selectedAgent = agentKey(agent);
    for (const node of $("world").querySelectorAll(".world-agent")) node.setAttribute("aria-pressed", String(node.dataset.key === selectedAgent));
    const inspector = $("agent-inspector");
    inspector.replaceChildren(element("div",`inspector-symbol ${normalState(agent.state)}`,agent.provider === "claude" ? "C" : "⌘"),element("h3","",titleCase(agent.provider)),badge(normalState(agent.state)),element("p","inspector-project",agent.project || "Project not reported"),element("p","inspector-task",agent.task || "Assignment not reported by this source."));
    const details = element("dl","inspector-details");
    for (const [label,value] of [["Role",agent.role || "Not reported"],["Source",agent.source || "Not reported"],["Observed",age(agent.updated_at)],["Confidence",agent.confidence || "Not reported"],["Session",agent.id || "Not reported"],["Parent",agent.parent_id || "No parent reported"],["Checkout",agent.path || "Not reported"]]) details.append(element("dt","",label),element("dd","",value));
    inspector.append(details);
  }
  function renderWorld(agents) {
    const world = $("world");
    const focusKey = world.contains(document.activeElement) ? document.activeElement.dataset.key : null;
    const groups = new Map();
    for (const agent of agents) {
      const key = agent.path || agent.project || "Unassigned";
      if (!groups.has(key)) groups.set(key,{name:agent.project || "Project not reported",agents:[]});
      groups.get(key).agents.push(agent);
    }
    const columns = Math.max(1,Math.ceil(Math.sqrt(groups.size)));
    const rows = Math.max(1,Math.ceil(groups.size / columns));
    const groupValues = [...groups.values()];
    const islandLength = Math.max(190,...groupValues.map(group => Math.ceil(group.agents.length / 4) * 90 + 70));
    camera.width = columns * 300 + 60; camera.height = rows * (islandLength + 90) + 60;
    world.style.width = `${camera.width}px`; world.style.height = `${camera.height}px`;
    const floor = element("div","world-floor");
    const nodes = [floor];
    groupValues.forEach((group,index) => {
      const island = element("div","project-island");
      island.style.transform = `translate3d(${45 + index % columns * 300}px,${45 + Math.floor(index / columns) * (islandLength + 90)}px,0)`;
      island.append(solid("island-base",260,islandLength,12,0,0,0));
      const label = element("div","island-label",group.name);
      label.style.top = `${islandLength + 12}px`;
      island.append(label);
      group.agents.forEach((agent,position) => {
        const state = normalState(agent.state);
        const robot = element("button",`world-agent ${state}${agent.parent_id ? " child-agent" : ""}`);
        robot.type = "button"; robot.dataset.key = agentKey(agent);
        robot.setAttribute("aria-label",`${titleCase(agent.provider)}, ${agent.role || "role not reported"}, ${state}, ${group.name}${agent.parent_id ? ", child session" : ""}`);
        robot.setAttribute("aria-pressed",String(robot.dataset.key === selectedAgent));
        robot.style.transform = `translate3d(${25 + position % 4 * 60}px,${35 + Math.floor(position / 4) * 90}px,13px)`;
        robot.append(solid("robot-foot",12,17,8,1,4,0),solid("robot-foot",12,17,8,19,4,0),solid("robot-body",30,22,27,1,0,9),solid("robot-head",36,27,24,-2,-2,40));
        const visor = element("span","robot-visor",agent.provider === "claude" ? "C" : agent.provider === "codex" ? "⌘" : titleCase(agent.provider).slice(0,1));
        visor.setAttribute("aria-hidden","true");
        robot.append(visor);
        const name = element("span","robot-label",`${titleCase(agent.provider)}${agent.parent_id ? " ↳" : ""}`);
        robot.append(name);
        robot.addEventListener("click",() => inspectAgent(agent));
        island.append(robot);
      });
      nodes.push(island);
    });
    world.replaceChildren(...nodes);
    $("world-empty").hidden = agents.length > 0;
    $("world-empty").textContent = "No current sessions match this view. Try another filter, or check source health below.";
    const selection = agents.find(agent => agentKey(agent) === selectedAgent);
    if (selection) inspectAgent(selection);
    else if (selectedAgent) {
      selectedAgent = null;
      $("agent-inspector").replaceChildren(element("h3","","Select an agent"),element("p","","The selected session is no longer in this view. Select another figure to inspect its latest observation."));
    }
    if (focusKey) [...world.querySelectorAll(".world-agent")].find(node => node.dataset.key === focusKey)?.focus({preventScroll:true});
    updateCamera();
  }
  function renderAgents() {
    if (!snapshot) return;
    const agents = snapshot.agents.filter(matches);
    const current = agents.filter(agent => !isHistory(agent));
    const recent = agents.filter(isHistory);
    renderWorld(current);
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
        $("world-empty").textContent = "Local tracker unavailable. No verified session data is available yet.";
      }
      $("announcer").textContent = "Live refresh is unavailable. Displayed activity may be out of date.";
    } finally {
      clearTimeout(timeout); busy = false; $("refresh").disabled = false;
      clearTimeout(timer); timer = setTimeout(refresh, Math.max(2, Number(snapshot && snapshot.interval) || 5) * 1000);
    }
  }
  $("refresh").addEventListener("click", refresh);
  for (const view of ["world","list"]) $( `view-${view}`).addEventListener("click",() => {
    $("workspace").hidden = view !== "world";
    $("list-view").hidden = view !== "list";
    for (const option of ["world","list"]) $(`view-${option}`).setAttribute("aria-pressed",String(view === option));
    if (view === "world") updateCamera();
  });
  function zoom(delta) {camera.zoom = Math.max(.4,Math.min(2.5,camera.zoom + delta));updateCamera();}
  $("zoom-in").addEventListener("click",() => zoom(.15));
  $("zoom-out").addEventListener("click",() => zoom(-.15));
  $("reset-camera").addEventListener("click",() => {camera.angle=-26;camera.tilt=54;camera.zoom=1;updateCamera();});
  const viewport = $("world-viewport");
  let drag = null;
  viewport.addEventListener("pointerdown",event => {
    if (event.target.closest("button") || event.button !== 0) return;
    drag={x:event.clientX,y:event.clientY,angle:camera.angle,tilt:camera.tilt};
    viewport.setPointerCapture(event.pointerId);viewport.classList.add("orbiting");
  });
  viewport.addEventListener("pointermove",event => {
    if (!drag) return;
    camera.angle=drag.angle+(event.clientX-drag.x)*.3;
    camera.tilt=Math.max(25,Math.min(70,drag.tilt-(event.clientY-drag.y)*.2));updateCamera();
  });
  function endDrag() {drag=null;viewport.classList.remove("orbiting");}
  viewport.addEventListener("pointerup",endDrag);viewport.addEventListener("pointercancel",endDrag);
  viewport.addEventListener("keydown",event => {
    if (event.target !== viewport) return;
    if (["ArrowLeft","ArrowRight","ArrowUp","ArrowDown","+","=","-","0"].includes(event.key)) event.preventDefault();
    if (event.key === "ArrowLeft") camera.angle-=8;
    if (event.key === "ArrowRight") camera.angle+=8;
    if (event.key === "ArrowUp") camera.tilt=Math.min(70,camera.tilt+5);
    if (event.key === "ArrowDown") camera.tilt=Math.max(25,camera.tilt-5);
    if (["+","="].includes(event.key)) zoom(.15);
    if (event.key === "-") zoom(-.15);
    if (event.key === "0") {camera.angle=-26;camera.tilt=54;camera.zoom=1;}
    updateCamera();
  });
  new ResizeObserver(updateCamera).observe(viewport);
  for (const id of ["search", "provider", "state", "project"]) $(id).addEventListener(id === "search" ? "input" : "change", renderAgents);
  document.addEventListener("visibilitychange", () => {if (!document.hidden) refresh();});
  refresh();
})();
