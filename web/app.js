// Skima Web UI — vanilla JS, no build step, no dependencies.
// Hash router with three views: Sources, Library, Updates.

const app = document.getElementById("app");

// Mirrors the "status" values `cli/skima check` writes to
// .skima/status.json, plus "unknown" for a source that hasn't been checked.
const STATE_META = {
  "up-to-date": { label: "Up to date", cls: "up-to-date" },
  behind: { label: "Behind", cls: "behind" },
  unreachable: { label: "Unreachable", cls: "unreachable" },
  unknown: { label: "Unknown", cls: "unknown" },
};

// Survives across re-renders of the Sources page so a Check result isn't
// lost the moment the page redraws itself.
let lastCheckNote = null; // { text, isError, detail } | null

function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key === "class") node.className = value;
    else node.setAttribute(key, value);
  }
  for (const child of [].concat(children)) {
    if (child == null) continue;
    node.appendChild(typeof child === "string" ? document.createTextNode(child) : child);
  }
  return node;
}

async function getJSON(url) {
  const res = await fetch(url);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `${url} -> ${res.status}`);
  return data;
}

async function postJSON(url) {
  const res = await fetch(url, { method: "POST" });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `${url} -> ${res.status}`);
  return data;
}

function setActiveNav(routeName) {
  document.querySelectorAll("nav a").forEach((a) => {
    a.classList.toggle("active", a.dataset.route === routeName);
  });
}

function statusBadge(state) {
  const meta = STATE_META[state] || STATE_META.unknown;
  return el("span", { class: `status-badge ${meta.cls}` }, meta.label);
}

function shortSha(sha) {
  return sha ? String(sha).slice(0, 10) : "—";
}

function formatCheckedAt(iso) {
  if (!iso) return "Never checked";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return `Checked ${iso}`;
  return `Checked ${d.toLocaleString()}`;
}

async function runCheck(onDone) {
  try {
    const result = await postJSON("/api/check");
    if (result && result.ok === false) {
      lastCheckNote = { text: result.error || "skima check failed.", isError: true, detail: result.stdout };
    } else {
      lastCheckNote = null;
    }
  } catch (e) {
    lastCheckNote = { text: e.message, isError: true, detail: null };
  } finally {
    onDone();
  }
}

async function renderSources() {
  app.innerHTML = "<p class=\"hint\">Loading sources…</p>";
  let sourcesData;
  let statusData;
  try {
    [sourcesData, statusData] = await Promise.all([getJSON("/api/sources"), getJSON("/api/status")]);
  } catch (e) {
    app.innerHTML = "";
    app.appendChild(el("p", { class: "error" }, `Failed to load sources.json: ${e.message}`));
    return;
  }

  const sources = sourcesData.sources || {};
  const names = Object.keys(sources).sort();
  const statusSources = statusData.sources || {};

  app.innerHTML = "";

  const checkBtn = el("button", { class: "btn", type: "button" }, "Check for updates");
  const checkNote = el("span", { class: "hint check-note" });
  const checkDetail = lastCheckNote && lastCheckNote.detail
    ? el("pre", { class: "check-detail" }, lastCheckNote.detail)
    : null;

  if (lastCheckNote) {
    checkNote.textContent = lastCheckNote.text;
    if (lastCheckNote.isError) checkNote.classList.add("error");
  } else {
    checkNote.textContent = formatCheckedAt(statusData.checked_at);
  }

  checkBtn.addEventListener("click", () => {
    checkBtn.disabled = true;
    checkBtn.textContent = "Checking…";
    runCheck(renderSources);
  });

  const toolbar = el("div", { class: "toolbar" }, [
    el("div", {}, [
      el("h2", {}, "Sources"),
      el("p", { class: "hint" }, `${names.length} tracked \u00b7 feeds Updates`),
    ]),
    el("div", { class: "toolbar-actions" }, [checkBtn, checkNote]),
  ]);

  app.appendChild(toolbar);
  if (checkDetail) app.appendChild(checkDetail);

  if (names.length === 0) {
    app.appendChild(el("p", {}, "No sources tracked yet."));
    return;
  }

  const rows = names.map((name) => {
    const s = sources[name] || {};
    const st = statusSources[name] || {};
    return el("tr", {}, [
      el("td", {}, el("a", { href: s.url || "#", target: "_blank", rel: "noopener" }, name)),
      el("td", {}, statusBadge(st.status || "unknown")),
      el("td", { class: "mono" }, shortSha(s.revision)),
      el("td", { class: "mono" }, shortSha(st.remote)),
      el("td", { class: "mono hint" }, s.path || "—"),
    ]);
  });

  const table = el("table", { class: "list" }, [
    el("thead", {}, el("tr", {}, [
      el("th", {}, "Name"),
      el("th", {}, "Status"),
      el("th", {}, "Pinned"),
      el("th", {}, "Remote"),
      el("th", {}, "Path"),
    ])),
    el("tbody", {}, rows),
  ]);

  app.appendChild(table);
}

async function renderCapabilityDetail(container, bucket, id, status) {
  container.innerHTML = "<p>Loading…</p>";
  const qs = `bucket=${encodeURIComponent(bucket)}&id=${encodeURIComponent(id)}&status=${encodeURIComponent(status)}`;

  let meta;
  try {
    meta = await getJSON(`/api/capability?${qs}`);
  } catch (e) {
    container.innerHTML = "";
    container.appendChild(el("p", { class: "error" }, e.message));
    return;
  }

  const provenanceBlock = meta.provenance
    ? el("dl", {}, [
        el("dt", {}, "Source"),
        el("dd", {}, meta.provenance.source || "—"),
        el("dt", {}, "Upstream URL"),
        el("dd", {}, meta.provenance.url || "—"),
        el("dt", {}, "Revision"),
        el("dd", { class: "mono" }, shortSha(meta.provenance.revision)),
      ])
    : el("p", { class: "hint" }, "Library-authored — no provenance.");

  const docNames = (meta.files || []).filter((name) => /\.md$/i.test(name) || name === "LICENSE");
  const preview = el("pre", { class: "preview" }, docNames.length ? "Loading…" : "No previewable docs in this capability.");

  const docSelect = el(
    "select",
    {},
    docNames.map((name) => el("option", { value: name }, name))
  );

  container.innerHTML = "";
  container.appendChild(
    el("div", {}, [
      el("h2", {}, meta.id),
      el("p", { class: "detail-meta" }, [
        el("span", { class: `badge ${meta.status}` }, meta.status),
        ` \u00b7 ${meta.kind} \u00b7 ${meta.bucket}`,
      ]),
      provenanceBlock,
      el("p", { class: "mono hint" }, meta.path),
      docNames.length
        ? el("div", { class: "files" }, [el("label", {}, "Preview: "), docSelect])
        : null,
      preview,
    ])
  );

  async function loadPreview(name) {
    if (!name) return;
    preview.textContent = "Loading…";
    try {
      const fileRes = await getJSON(`/api/file?${qs}&name=${encodeURIComponent(name)}`);
      preview.textContent = fileRes.content;
    } catch (e) {
      preview.textContent = `Failed to load ${name}: ${e.message}`;
    }
  }

  docSelect.addEventListener("change", (e) => loadPreview(e.target.value));
  if (docNames.length) loadPreview(docNames.includes("SKILL.md") ? "SKILL.md" : docNames[0]);
}

async function renderLibrary() {
  app.innerHTML = "<p class=\"hint\">Loading library…</p>";
  let data;
  try {
    data = await getJSON("/api/buckets");
  } catch (e) {
    app.innerHTML = "";
    app.appendChild(el("p", { class: "error" }, `Failed to load library: ${e.message}`));
    return;
  }

  const buckets = data.buckets || {};
  const bucketNames = Object.keys(buckets).sort();
  const totalCaps = bucketNames.reduce((sum, name) => sum + buckets[name].length, 0);

  app.innerHTML = "";
  app.appendChild(
    el("div", { class: "toolbar" }, [
      el("div", {}, [
        el("h2", {}, "Library"),
        el("p", { class: "hint" }, `${totalCaps} capabilities \u00b7 ${bucketNames.length} buckets`),
      ]),
    ])
  );

  const list = el("div", { class: "bucket-list" });
  for (const bucket of bucketNames) {
    const caps = [...buckets[bucket]].sort((a, b) => a.id.localeCompare(b.id));
    const items = caps.map((cap) =>
      el(
        "li",
        {},
        el(
          "a",
          {
            href: "#",
            class: "cap",
            "data-bucket": cap.bucket,
            "data-id": cap.id,
            "data-status": cap.status,
          },
          [cap.id, el("span", { class: `badge ${cap.status}` }, cap.status)]
        )
      )
    );
    list.appendChild(el("div", { class: "bucket" }, [el("h3", {}, `${bucket} (${caps.length})`), el("ul", {}, items)]));
  }

  const detail = el("div", { class: "detail" }, el("p", { class: "hint" }, "Select a capability to view details."));

  app.appendChild(
    el("section", { class: "library" }, [
      bucketNames.length ? list : el("p", {}, "No capabilities in the library yet."),
      detail,
    ])
  );

  list.addEventListener("click", (e) => {
    const link = e.target.closest("a.cap");
    if (!link) return;
    e.preventDefault();
    list.querySelectorAll("a.cap").forEach((n) => n.classList.remove("selected"));
    link.classList.add("selected");
    renderCapabilityDetail(detail, link.dataset.bucket, link.dataset.id, link.dataset.status);
  });
}

async function renderUpdates() {
  app.innerHTML = "<p class=\"hint\">Loading updates…</p>";
  let sourcesData;
  let statusData;
  try {
    [sourcesData, statusData] = await Promise.all([getJSON("/api/sources"), getJSON("/api/status")]);
  } catch (e) {
    app.innerHTML = "";
    app.appendChild(el("p", { class: "error" }, `Failed to load status: ${e.message}`));
    return;
  }

  const sources = sourcesData.sources || {};
  const statusSources = statusData.sources || {};
  const names = Object.keys(sources).sort();

  app.innerHTML = "";
  app.appendChild(
    el("div", { class: "toolbar" }, [
      el("div", {}, [
        el("h2", {}, "Updates"),
        el("p", { class: "hint" }, formatCheckedAt(statusData.checked_at)),
      ]),
    ])
  );

  if (!statusData.checked_at) {
    app.appendChild(
      el("div", { class: "empty-state" }, [
        el("p", {}, statusData.message || "Run skima check to see which Sources are behind."),
        el("p", { class: "hint" }, "Then revisit this page, or use \u201cCheck for updates\u201d on Sources."),
      ])
    );
    return;
  }

  const behindNames = names.filter((name) => (statusSources[name] || {}).status === "behind");
  const flaggedNames = names.filter((name) => {
    const status = (statusSources[name] || {}).status;
    return status && status !== "behind" && status !== "up-to-date";
  });

  if (behindNames.length === 0) {
    app.appendChild(el("div", { class: "empty-state" }, [el("p", {}, "All Sources are up to date.")]));
  } else {
    const items = behindNames.map((name) => {
      const s = sources[name] || {};
      const st = statusSources[name] || {};
      return el("li", { class: "update-item" }, [
        el("div", { class: "update-item-head" }, [
          el("span", { class: "update-name" }, name),
          statusBadge("behind"),
        ]),
        el("p", { class: "mono hint" }, `pinned ${shortSha(s.revision)} \u2192 remote ${shortSha(st.remote)}`),
        el("p", { class: "cta" }, [
          "Run ",
          el("code", {}, `cli/skima sync ${name}`),
          " in the CLI, then review Library copies.",
        ]),
      ]);
    });
    app.appendChild(el("ul", { class: "update-list" }, items));
  }

  if (flaggedNames.length) {
    const items = flaggedNames.map((name) => {
      const st = statusSources[name] || {};
      return el("li", {}, [
        name,
        " ",
        statusBadge(st.status),
        st.error ? el("span", { class: "hint" }, ` \u2014 ${st.error}`) : null,
      ]);
    });
    app.appendChild(
      el("div", { class: "update-other" }, [el("h3", {}, "Needs attention"), el("ul", { class: "plain-list" }, items)])
    );
  }
}

const routes = { sources: renderSources, library: renderLibrary, updates: renderUpdates };
const ROUTE_ALIASES = { review: "updates" };

function route() {
  let hash = location.hash.replace(/^#\/?/, "") || "sources";
  hash = ROUTE_ALIASES[hash] || hash;
  const name = routes[hash] ? hash : "sources";
  setActiveNav(name);
  routes[name]();
}

window.addEventListener("hashchange", route);
window.addEventListener("DOMContentLoaded", route);
