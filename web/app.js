// Skima Web UI — vanilla JS, no build step, no dependencies.
// Hash router with three views: Sources, Library, Change review.

const app = document.getElementById("app");

// Mirrors the "status" values `cli/skima check` writes to
// .skima/status.json, plus "unknown" for a source that hasn't been checked.
const STATE_META = {
  "up-to-date": { label: "Up to date", cls: "up-to-date" },
  behind: { label: "Behind", cls: "behind" },
  unreachable: { label: "Unreachable", cls: "unreachable" },
  unknown: { label: "Unknown", cls: "unknown" },
};

// Survives across re-renders of a page so a check result isn't lost the
// moment the page redraws itself.
let lastCheckNote = null; // { text, isError, detail } | null

// Generation counters. Every async render claims the next value and then
// re-checks it before touching the DOM, so a slow response from an earlier
// click can never overwrite what a later click already painted.
let viewGen = 0;
let detailGen = 0;
let previewGen = 0;

function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value == null) continue;
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else node.setAttribute(key, value);
  }
  for (const child of [].concat(children)) {
    if (child == null) continue;
    node.appendChild(typeof child === "string" ? document.createTextNode(child) : child);
  }
  return node;
}

// The server rejects state-changing requests without a same-origin signal;
// this header is the fallback proof for clients that send neither Origin nor
// Fetch Metadata. Sending it on reads too costs nothing.
const REQUEST_HEADERS = { "X-Skima-Request": "1" };

async function getJSON(url) {
  const res = await fetch(url, { headers: REQUEST_HEADERS });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `${url} -> ${res.status}`);
  return data;
}

async function postJSON(url) {
  const res = await fetch(url, { method: "POST", headers: REQUEST_HEADERS });
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

// "Run check" button + its result note, shared by Sources and Change review.
function checkControls(checkedAt, rerender) {
  const button = el("button", { class: "btn", type: "button" }, "Run check");
  const note = el("span", { class: "hint check-note" });

  if (lastCheckNote) {
    note.textContent = lastCheckNote.text;
    if (lastCheckNote.isError) note.classList.add("error");
  } else {
    note.textContent = formatCheckedAt(checkedAt);
  }

  button.addEventListener("click", () => {
    button.disabled = true;
    button.textContent = "Checking…";
    runCheck(rerender);
  });

  const detail = lastCheckNote && lastCheckNote.detail
    ? el("pre", { class: "check-detail" }, lastCheckNote.detail)
    : null;

  return { actions: el("div", { class: "toolbar-actions" }, [button, note]), detail };
}

async function renderSources() {
  const gen = ++viewGen;
  app.innerHTML = "<p class=\"hint\">Loading Sources…</p>";

  let sourcesData;
  let statusData;
  try {
    [sourcesData, statusData] = await Promise.all([getJSON("/api/sources"), getJSON("/api/status")]);
  } catch (e) {
    if (gen !== viewGen) return;
    app.innerHTML = "";
    app.appendChild(el("p", { class: "error" }, `Failed to load Sources: ${e.message}`));
    return;
  }
  if (gen !== viewGen) return;

  const sources = sourcesData.sources || {};
  const names = Object.keys(sources).sort();
  const statusSources = statusData.sources || {};
  const controls = checkControls(statusData.checked_at, renderSources);

  app.innerHTML = "";
  app.appendChild(
    el("div", { class: "toolbar" }, [
      el("div", {}, [
        el("h2", {}, "Sources"),
        el("p", { class: "hint" }, `${names.length} tracked · feeds Change review`),
      ]),
      controls.actions,
    ])
  );
  if (controls.detail) app.appendChild(controls.detail);
  if (sourcesData.error) app.appendChild(el("p", { class: "error" }, sourcesData.error));

  if (names.length === 0) {
    app.appendChild(el("p", {}, "No Sources tracked yet."));
    return;
  }

  const rows = names.map((name) => {
    const s = sources[name] || {};
    const st = statusSources[name] || {};
    return el("tr", {}, [
      el("td", {}, el("a", { href: s.url || "#", target: "_blank", rel: "noopener" }, name)),
      el("td", {}, statusBadge(st.status || "unknown")),
      el("td", { class: "mono", title: s.revision || "" }, shortSha(s.revision)),
      el("td", { class: "mono", title: st.remote || "" }, shortSha(st.remote)),
      el("td", { class: "mono hint" }, s.path || "—"),
    ]);
  });

  app.appendChild(
    el("table", { class: "list" }, [
      el("thead", {}, el("tr", {}, [
        el("th", {}, "Name"),
        el("th", {}, "Check state"),
        el("th", {}, "Pinned"),
        el("th", {}, "Remote"),
        el("th", {}, "Path"),
      ])),
      el("tbody", {}, rows),
    ])
  );
}

function provenanceBlock(provenance) {
  if (!provenance || typeof provenance !== "object") {
    return el("p", { class: "hint" }, "Library-authored — no provenance.");
  }
  const source = provenance.source || provenance.name || null;
  const url = provenance.url || provenance.repo || null;
  const upstreamPath = provenance.path || provenance.upstream_path || null;
  const revision = provenance.revision || provenance.rev || provenance.sha || null;

  return el("dl", { class: "provenance" }, [
    el("dt", {}, "Source"),
    el("dd", {}, source || "—"),
    el("dt", {}, "Repository"),
    el("dd", {}, url ? el("a", { href: url, target: "_blank", rel: "noopener" }, url) : "—"),
    el("dt", {}, "Upstream path"),
    el("dd", { class: "mono" }, upstreamPath || "—"),
    el("dt", {}, "Last-reviewed revision"),
    el("dd", { class: "mono", title: revision || "" }, shortSha(revision)),
  ]);
}

function warningsBlock(warnings) {
  if (!warnings || !warnings.length) return null;
  return el("div", { class: "warnings" }, [
    el("h3", {}, warnings.length === 1 ? "1 metadata warning" : `${warnings.length} metadata warnings`),
    el("ul", { class: "plain-list" }, warnings.map((w) => el("li", {}, w))),
  ]);
}

async function renderCapabilityDetail(container, bucket, id, status) {
  const gen = ++detailGen;
  container.innerHTML = "<p class=\"hint\">Loading…</p>";
  const qs = `bucket=${encodeURIComponent(bucket)}&id=${encodeURIComponent(id)}&status=${encodeURIComponent(status)}`;

  let meta;
  try {
    meta = await getJSON(`/api/capability?${qs}`);
  } catch (e) {
    if (gen !== detailGen) return;
    container.innerHTML = "";
    container.appendChild(el("p", { class: "error" }, e.message));
    return;
  }
  if (gen !== detailGen) return;

  // The server lists exactly the docs it will serve (any depth up to 3,
  // escaping symlinks excluded), so every option here is loadable.
  const docNames = meta.docs || [];
  const initial = docNames.includes("SKILL.md") ? "SKILL.md" : docNames[0];
  const preview = el("pre", { class: "preview" }, docNames.length ? "Loading…" : "No previewable docs in this capability.");
  const docSelect = el(
    "select",
    {},
    docNames.map((name) => el("option", { value: name }, name))
  );
  if (initial) docSelect.value = initial; // keep the control in sync with what loads

  container.innerHTML = "";
  container.appendChild(
    el("div", {}, [
      el("h2", {}, meta.id),
      el("p", { class: "detail-meta" }, [
        el("span", { class: `badge ${meta.status}` }, meta.status),
        ` · ${meta.kind} · ${meta.bucket}`,
      ]),
      warningsBlock(meta.warnings),
      el("h3", { class: "section-label" }, "Provenance"),
      provenanceBlock(meta.provenance),
      el("p", { class: "mono hint" }, meta.path),
      docNames.length
        ? el("div", { class: "files" }, [el("label", {}, "Preview: "), docSelect])
        : null,
      preview,
    ])
  );

  async function loadPreview(name) {
    if (!name) return;
    const pgen = ++previewGen;
    preview.textContent = "Loading…";
    try {
      const fileRes = await getJSON(`/api/file?${qs}&name=${encodeURIComponent(name)}`);
      if (pgen !== previewGen || gen !== detailGen) return;
      preview.textContent = fileRes.truncated
        ? `${fileRes.content}\n\n… truncated (file is larger than the preview limit).`
        : fileRes.content;
    } catch (e) {
      if (pgen !== previewGen || gen !== detailGen) return;
      preview.textContent = `Failed to load ${name}: ${e.message}`;
    }
  }

  docSelect.addEventListener("change", (e) => loadPreview(e.target.value));
  if (initial) loadPreview(initial);
}

async function renderLibrary() {
  const gen = ++viewGen;
  app.innerHTML = "<p class=\"hint\">Loading Library…</p>";

  let data;
  try {
    data = await getJSON("/api/buckets");
  } catch (e) {
    if (gen !== viewGen) return;
    app.innerHTML = "";
    app.appendChild(el("p", { class: "error" }, `Failed to load Library: ${e.message}`));
    return;
  }
  if (gen !== viewGen) return;

  const buckets = data.buckets || {};
  const bucketNames = Object.keys(buckets).sort();
  const totalCaps = bucketNames.reduce((sum, name) => sum + buckets[name].length, 0);

  app.innerHTML = "";
  app.appendChild(
    el("div", { class: "toolbar" }, [
      el("div", {}, [
        el("h2", {}, "Library"),
        el("p", { class: "hint" }, `${totalCaps} capabilities · ${bucketNames.length} buckets`),
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
          [
            cap.id,
            el("span", { class: "cap-marks" }, [
              cap.warnings && cap.warnings.length
                ? el("span", { class: "warn-mark", title: cap.warnings.join("\n") }, "!")
                : null,
              el("span", { class: `badge ${cap.status}` }, cap.status),
            ]),
          ]
        )
      )
    );
    const body = caps.length
      ? el("ul", {}, items)
      : el("p", { class: "hint empty-bucket" }, "No capabilities yet.");
    list.appendChild(el("div", { class: "bucket" }, [el("h3", {}, `${bucket} (${caps.length})`), body]));
  }

  const detail = el("div", { class: "detail" }, el("p", { class: "hint" }, "Select a capability to view details."));

  app.appendChild(
    el("section", { class: "library" }, [
      bucketNames.length ? list : el("p", {}, "No buckets in the Library yet."),
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

// Scope note shown on every Change review render. This page compares pinned
// Revisions to remote HEADs and nothing more; saying so beats implying a
// depth the page does not have.
function reviewScopeNote() {
  return el("div", { class: "scope-note" }, [
    el("p", {}, [
      "Shows: each tracked Source's pinned Revision against its remote HEAD, as recorded by the last ",
      el("code", {}, "skima check"),
      ".",
    ]),
    el("p", {}, [
      "Not yet shown: the file-level changes behind a Source that is behind, and whether an adopted ",
      "Library copy has drifted from its provenance Revision. Adoption and updates stay CLI actions — ",
      "there is no adopt or update button here.",
    ]),
  ]);
}

async function renderChangeReview() {
  const gen = ++viewGen;
  app.innerHTML = "<p class=\"hint\">Loading Change review…</p>";

  let sourcesData;
  let statusData;
  try {
    [sourcesData, statusData] = await Promise.all([getJSON("/api/sources"), getJSON("/api/status")]);
  } catch (e) {
    if (gen !== viewGen) return;
    app.innerHTML = "";
    app.appendChild(el("p", { class: "error" }, `Failed to load check status: ${e.message}`));
    return;
  }
  if (gen !== viewGen) return;

  const sources = sourcesData.sources || {};
  const statusSources = statusData.sources || {};
  const names = Object.keys(sources).sort();
  const controls = checkControls(statusData.checked_at, renderChangeReview);

  app.innerHTML = "";
  app.appendChild(
    el("div", { class: "toolbar" }, [
      el("div", {}, [
        el("h2", {}, "Change review"),
        el("p", { class: "hint" }, formatCheckedAt(statusData.checked_at)),
      ]),
      controls.actions,
    ])
  );
  if (controls.detail) app.appendChild(controls.detail);
  app.appendChild(reviewScopeNote());

  if (!statusData.checked_at) {
    app.appendChild(
      el("div", { class: "empty-state" }, [
        el("p", {}, statusData.message || "Run skima check to see which Sources are behind."),
        el("p", { class: "hint" }, "Use “Run check” above, or run ./cli/skima check in a terminal."),
      ])
    );
    return;
  }

  const behindNames = names.filter((name) => (statusSources[name] || {}).status === "behind");
  const upToDateNames = names.filter((name) => (statusSources[name] || {}).status === "up-to-date");
  const flaggedNames = names.filter((name) => !behindNames.includes(name) && !upToDateNames.includes(name));

  if (behindNames.length === 0) {
    app.appendChild(el("div", { class: "empty-state" }, [el("p", {}, "No tracked Source is behind its remote.")]));
  } else {
    const items = behindNames.map((name) => {
      const s = sources[name] || {};
      const st = statusSources[name] || {};
      return el("li", { class: "review-item" }, [
        el("div", { class: "review-item-head" }, [
          el("span", { class: "review-name" }, name),
          statusBadge("behind"),
        ]),
        el("p", { class: "mono hint" }, `pinned ${shortSha(st.pinned || s.revision)} → remote ${shortSha(st.remote)}`),
        el("p", { class: "cta" }, [
          "Run ",
          el("code", {}, `./cli/skima sync ${name}`),
          " to move the pinned Revision, then adopt or update Library copies deliberately.",
        ]),
      ]);
    });
    app.appendChild(el("ul", { class: "review-list" }, items));
  }

  if (flaggedNames.length) {
    const items = flaggedNames.map((name) => {
      const st = statusSources[name] || {};
      return el("li", {}, [
        name,
        " ",
        statusBadge(st.status || "unknown"),
        st.error ? el("span", { class: "hint" }, ` — ${st.error}`) : null,
      ]);
    });
    app.appendChild(
      el("div", { class: "review-other" }, [el("h3", {}, "Needs attention"), el("ul", { class: "plain-list" }, items)])
    );
  }

  app.appendChild(
    el("p", { class: "hint review-summary" }, `${upToDateNames.length} of ${names.length} tracked Sources up to date.`)
  );
}

const routes = { sources: renderSources, library: renderLibrary, review: renderChangeReview };
// "updates" was the old name for this page; keep old links working.
const ROUTE_ALIASES = { updates: "review" };

function route() {
  let hash = location.hash.replace(/^#\/?/, "") || "sources";
  hash = ROUTE_ALIASES[hash] || hash;
  const name = routes[hash] ? hash : "sources";
  setActiveNav(name);
  routes[name]();
}

window.addEventListener("hashchange", route);
window.addEventListener("DOMContentLoaded", route);
