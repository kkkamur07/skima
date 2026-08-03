// Skima Web UI — vanilla JS, no build step, no dependencies.
// Hash router with four views: Sources, Explore, Library, Change review.

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

// View state that must survive a repaint: a filter the user typed, the row
// they selected, the result of the last adopt. Kept out of the DOM so
// repainting the list never resets any of it.
const exploreState = { query: "", kind: "all", hideAdopted: false, selected: null, note: null };
const libraryState = { query: "", selected: null };
let exploreData = null;

function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value == null || value === false) continue;
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else if (key === "onclick") node.addEventListener("click", value);
    else node.setAttribute(key, value === true ? "" : value);
  }
  for (const child of [].concat(children)) {
    if (child == null || child === false) continue;
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

async function postJSON(url, body) {
  const options = { method: "POST", headers: { ...REQUEST_HEADERS } };
  if (body !== undefined) {
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(body);
  }
  const res = await fetch(url, options);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `${url} -> ${res.status}`);
  return data;
}

function setActiveNav(routeName) {
  document.querySelectorAll(".sidebar nav a").forEach((a) => {
    a.classList.toggle("active", a.dataset.route === routeName);
  });
}

function statusBadge(state) {
  const meta = STATE_META[state] || STATE_META.unknown;
  return el("span", { class: `status-badge ${meta.cls}` }, meta.label);
}

function kindBadge(kind) {
  return el("span", { class: `badge kind-${kind || "skill"}` }, kind || "skill");
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

function plural(n, one, many) {
  return n === 1 ? one : many;
}

// ---------------------------------------------------------------------------
// Markdown preview
//
// A SKILL.md read as raw text is a wall of hashes and backticks, which makes
// the one screen where you decide "do I want this?" the hardest to read. This
// renders the common subset instead.
//
// Everything is HTML-escaped BEFORE any transform runs, so no markup in a file
// survives into the DOM; the transforms below then emit a fixed, known set of
// tags. Link hrefs are additionally scheme-checked.
// ---------------------------------------------------------------------------

function escapeHtml(text) {
  return String(text).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
  );
}

function inlineMarkdown(text) {
  return text
    .replace(/`([^`\n]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|[\s(])\*([^*\n]+)\*/g, "$1<em>$2</em>")
    .replace(/\[([^\]\n]+)\]\(([^)\s]+)\)/g, (match, label, href) =>
      /^https?:\/\//i.test(href) ? `<a href="${href}" target="_blank" rel="noopener">${label}</a>` : label
    );
}

function renderMarkdown(source) {
  // Code blocks are lifted out before anything else touches the text and put
  // back last, so markdown syntax inside a fenced example stays literal. The
  // placeholder is NUL-delimited: it cannot occur in a source file, and it
  // survives both the HTML escape and the per-line trim below.
  const fences = [];
  let text = String(source).replace(/\r\n?/g, "\n");

  // Frontmatter is metadata, not prose — show it verbatim rather than letting
  // the "---" fences render as horizontal rules with stray text between them.
  const front = text.match(/^---\n([\s\S]*?)\n---\n?/);
  if (front) {
    fences.push(front[1]);
    text = `\u0000F0\u0000\n${text.slice(front[0].length)}`;
  }

  text = text.replace(/```[^\n]*\n([\s\S]*?)```/g, (match, code) => {
    fences.push(code.replace(/\n+$/, ""));
    return `\u0000F${fences.length - 1}\u0000`;
  });

  const lines = escapeHtml(text).split("\n");
  const out = [];
  let listTag = null;
  let paragraph = [];

  const closeParagraph = () => {
    if (paragraph.length) {
      out.push(`<p>${inlineMarkdown(paragraph.join(" "))}</p>`);
      paragraph = [];
    }
  };
  const closeList = () => {
    if (listTag) {
      out.push(`</${listTag}>`);
      listTag = null;
    }
  };

  for (const raw of lines) {
    const line = raw.trimEnd();
    const trimmed = line.trim();

    const fence = trimmed.match(/^\u0000F(\d+)\u0000$/);
    if (fence) {
      closeParagraph();
      closeList();
      out.push(`<pre><code>${escapeHtml(fences[Number(fence[1])])}</code></pre>`);
      continue;
    }

    if (!trimmed) {
      closeParagraph();
      closeList();
      continue;
    }

    const heading = trimmed.match(/^(#{1,6})\s+(.*)$/);
    if (heading) {
      closeParagraph();
      closeList();
      const level = Math.min(heading[1].length + 1, 6); // the panel owns <h2>
      out.push(`<h${level}>${inlineMarkdown(heading[2])}</h${level}>`);
      continue;
    }

    if (/^(-{3,}|\*{3,}|_{3,})$/.test(trimmed)) {
      closeParagraph();
      closeList();
      out.push("<hr />");
      continue;
    }

    const bullet = trimmed.match(/^[-*+]\s+(.*)$/);
    const numbered = trimmed.match(/^\d+[.)]\s+(.*)$/);
    if (bullet || numbered) {
      closeParagraph();
      const wanted = bullet ? "ul" : "ol";
      if (listTag !== wanted) {
        closeList();
        out.push(`<${wanted}>`);
        listTag = wanted;
      }
      out.push(`<li>${inlineMarkdown((bullet || numbered)[1])}</li>`);
      continue;
    }

    const quote = trimmed.match(/^&gt;\s?(.*)$/);
    if (quote) {
      closeParagraph();
      closeList();
      out.push(`<blockquote>${inlineMarkdown(quote[1])}</blockquote>`);
      continue;
    }

    closeList();
    paragraph.push(trimmed);
  }
  closeParagraph();
  closeList();

  return out.join("\n");
}

function previewNode(name, content, truncated) {
  const body = truncated
    ? `${content}\n\n… truncated (file is larger than the preview limit).`
    : content;
  if (!/\.(md|markdown)$/i.test(name)) {
    return el("pre", { class: "preview" }, body);
  }
  const node = el("div", { class: "preview md" });
  node.innerHTML = renderMarkdown(body);
  return node;
}

// ---------------------------------------------------------------------------
// Shared pieces
// ---------------------------------------------------------------------------

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
    ? el("pre", { class: "output" }, lastCheckNote.detail)
    : null;

  return { actions: el("div", { class: "toolbar-actions" }, [button, note]), detail };
}

function toolbar(title, subtitle, actions) {
  return el("div", { class: "toolbar" }, [
    el("div", {}, [el("h2", {}, title), el("p", { class: "hint" }, subtitle)]),
    actions,
  ]);
}

function searchField(placeholder, value, onInput) {
  const input = el("input", { type: "search", placeholder, value, "aria-label": placeholder });
  input.addEventListener("input", () => onInput(input.value));
  return input;
}

function chipGroup(options, current, onPick) {
  const group = el("div", { class: "chips" });
  for (const option of options) {
    group.appendChild(
      el(
        "button",
        {
          type: "button",
          class: `chip${option.value === current ? " on" : ""}`,
          onclick: () => onPick(option.value),
        },
        option.label
      )
    );
  }
  return group;
}

function errorView(message) {
  app.innerHTML = "";
  app.appendChild(el("p", { class: "error" }, message));
}

// ---------------------------------------------------------------------------
// Sources
// ---------------------------------------------------------------------------

async function renderSources() {
  const gen = ++viewGen;
  app.innerHTML = "<p class=\"hint\">Loading Sources…</p>";

  let sourcesData;
  let statusData;
  let explore;
  try {
    [sourcesData, statusData, explore] = await Promise.all([
      getJSON("/api/sources"),
      getJSON("/api/status"),
      getJSON("/api/explore").catch(() => null),
    ]);
  } catch (e) {
    if (gen !== viewGen) return;
    return errorView(`Failed to load Sources: ${e.message}`);
  }
  if (gen !== viewGen) return;

  const sources = sourcesData.sources || {};
  const names = Object.keys(sources).sort();
  const statusSources = statusData.sources || {};
  const controls = checkControls(statusData.checked_at, renderSources);

  const discovered = {};
  for (const record of (explore && explore.sources) || []) {
    discovered[record.name] = record.capabilities || [];
  }

  app.innerHTML = "";
  app.appendChild(
    toolbar("Sources", `${names.length} tracked · feeds Explore and Change review`, controls.actions)
  );
  if (controls.detail) app.appendChild(controls.detail);
  if (sourcesData.error) app.appendChild(el("p", { class: "error" }, sourcesData.error));

  if (names.length === 0) {
    app.appendChild(el("div", { class: "empty-state" }, el("p", {}, "No Sources tracked yet.")));
    return;
  }

  const rows = names.map((name) => {
    const s = sources[name] || {};
    const st = statusSources[name] || {};
    const caps = discovered[name];
    const adopted = (caps || []).filter((c) => c.adopted).length;
    return el("tr", {}, [
      el("td", {}, el("a", { href: s.url || "#", target: "_blank", rel: "noopener" }, name)),
      el("td", {}, statusBadge(st.status || "unknown")),
      el("td", { class: "mono", title: s.revision || "" }, shortSha(s.revision)),
      el("td", { class: "mono", title: st.remote || "" }, shortSha(st.remote)),
      el(
        "td",
        { class: "hint" },
        caps ? `${caps.length} found · ${adopted} in Library` : "—"
      ),
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
        el("th", {}, "Capabilities"),
        el("th", {}, "Path"),
      ])),
      el("tbody", {}, rows),
    ])
  );
}

// ---------------------------------------------------------------------------
// Explore — browse the tracked Sources and adopt from them
// ---------------------------------------------------------------------------

const KIND_FILTERS = [
  { value: "all", label: "All" },
  { value: "skill", label: "Skills" },
  { value: "plugin", label: "Plugins" },
  { value: "hook", label: "Hooks" },
];

function capabilityMatches(cap, sourceName, query, kind, hideAdopted) {
  if (kind !== "all" && cap.kind !== kind) return false;
  if (hideAdopted && cap.adopted) return false;
  if (!query) return true;
  const haystack = [cap.id, cap.name, cap.description, cap.path, sourceName]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
  return query.split(/\s+/).every((term) => haystack.includes(term));
}

async function renderExplore() {
  const gen = ++viewGen;
  app.innerHTML = "<p class=\"hint\">Scanning Sources…</p>";

  let data;
  try {
    data = await getJSON("/api/explore");
  } catch (e) {
    if (gen !== viewGen) return;
    return errorView(`Failed to scan Sources: ${e.message}`);
  }
  if (gen !== viewGen) return;

  exploreData = data;
  paintExplore();
}

// Refresh the underlying data without redrawing the whole page — used after an
// adopt so the "in Library" ticks appear without losing the panel or filters.
async function refreshExploreData(listBox) {
  try {
    exploreData = await getJSON("/api/explore");
    if (listBox) paintExploreList(listBox);
  } catch (e) {
    /* the panel already shows what the adopt itself reported */
  }
}

function paintExplore() {
  const data = exploreData || { sources: [], buckets: [] };
  const all = (data.sources || []).flatMap((s) => s.capabilities || []);
  const adopted = all.filter((c) => c.adopted).length;

  app.innerHTML = "";
  app.appendChild(
    toolbar(
      "Explore",
      `${all.length} capabilities across ${(data.sources || []).length} Sources · ${adopted} already in your Library`,
      null
    )
  );
  if (data.error) app.appendChild(el("p", { class: "error" }, data.error));

  const listBox = el("div", { class: "split-list" });
  const panel = el("div", { class: "panel" });

  const filters = el("div", { class: "filters" }, [
    searchField("Search skills, plugins and hooks…", exploreState.query, (value) => {
      exploreState.query = value;
      paintExploreList(listBox);
    }),
    chipGroup(KIND_FILTERS, exploreState.kind, (value) => {
      exploreState.kind = value;
      paintExplore();
    }),
    (() => {
      const box = el("input", { type: "checkbox", checked: exploreState.hideAdopted });
      box.addEventListener("change", () => {
        exploreState.hideAdopted = box.checked;
        paintExplore();
      });
      return el("label", { class: "toggle" }, [box, "Hide what I already have"]);
    })(),
  ]);
  app.appendChild(filters);

  app.appendChild(el("section", { class: "split" }, [listBox, panel]));

  paintExploreList(listBox);
  paintExplorePanel(panel, listBox);
}

function paintExploreList(listBox) {
  const data = exploreData || { sources: [] };
  const { query, kind, hideAdopted } = exploreState;
  const needle = query.trim().toLowerCase();

  listBox.innerHTML = "";
  let shown = 0;

  for (const source of data.sources || []) {
    const caps = (source.capabilities || []).filter((cap) =>
      capabilityMatches(cap, source.name, needle, kind, hideAdopted)
    );
    if (!caps.length) continue;
    shown += caps.length;

    const body = el("div", { class: "group-body" });
    for (const cap of caps) {
      const selected =
        exploreState.selected &&
        exploreState.selected.source === source.name &&
        exploreState.selected.path === cap.path;

      const marks = el("span", { class: "row-marks" }, [
        cap.adopted && cap.adopted.behind_source
          ? el("span", { class: "warn-mark", title: "Your Library copy is older than this Source's pinned Revision." }, "!")
          : null,
        cap.adopted ? el("span", { class: "tick", title: `In Library: ${cap.adopted.bucket}/${cap.adopted.id}` }, "✓") : null,
      ]);

      const row = el(
        "button",
        { type: "button", class: `row${selected ? " selected" : ""}` },
        [
          kindBadge(cap.kind),
          el("span", { class: "row-main" }, [
            el("span", { class: "row-title" }, el("span", { class: "row-id" }, cap.id)),
            cap.description ? el("p", { class: "row-desc" }, cap.description) : null,
          ]),
          marks,
        ]
      );
      row.addEventListener("click", () => {
        exploreState.selected = { source: source.name, path: cap.path };
        exploreState.note = null;
        paintExploreList(listBox);
        paintExplorePanel(document.querySelector(".panel"), listBox);
      });
      body.appendChild(row);
    }

    const group = el("details", { class: "group", open: needle ? true : source.capabilities.length <= 30 }, [
      el("summary", {}, [
        el("span", { class: "group-name" }, source.name),
        !source.present ? el("span", { class: "badge" }, "missing tree") : null,
        el("span", { class: "group-count" }, `${caps.length} ${plural(caps.length, "capability", "capabilities")}`),
      ]),
      body,
    ]);
    listBox.appendChild(group);
  }

  if (!shown) {
    listBox.appendChild(
      el("div", { class: "empty-state" }, [
        el("p", {}, "Nothing matches those filters."),
        el("p", { class: "hint" }, "Clear the search, or switch the kind filter back to All."),
      ])
    );
  }
}

function bringsBlock(components) {
  const entries = Object.entries(components || {}).filter(([, items]) => items && items.length);
  if (!entries.length) return null;

  const labels = { skills: "Skills", agents: "Agents", hooks: "Hook events", commands: "Commands" };
  const rows = entries.map(([key, items]) => {
    const visible = items.slice(0, 12);
    const rest = items.length - visible.length;
    return el("div", { class: "brings-row" }, [
      el("span", { class: "brings-label" }, `${labels[key] || key} ${items.length}`),
      el("span", { class: "tags" }, [
        ...visible.map((item) => el("span", { class: "tag" }, item)),
        rest > 0 ? el("span", { class: "tag more" }, `+${rest} more`) : null,
      ]),
    ]);
  });

  return el("div", {}, [
    el("h3", { class: "section-label" }, "What it brings"),
    el("div", { class: "brings" }, rows),
  ]);
}

function noteNode(note) {
  if (!note) return null;
  const box = el("div", { class: `note ${note.tone || ""}` }, [el("p", {}, note.text)]);
  if (note.output) box.appendChild(el("pre", { class: "output" }, note.output));
  if (note.actions) box.appendChild(note.actions);
  return box;
}

async function paintExplorePanel(panel, listBox) {
  const gen = ++detailGen;
  if (!panel) return;

  const selection = exploreState.selected;
  if (!selection) {
    panel.innerHTML = "";
    panel.appendChild(
      el("div", { class: "empty-state" }, [
        el("p", {}, "Pick anything on the left."),
        el("p", { class: "hint" }, "You get its docs, what it brings, and a one-click add to your Library."),
      ])
    );
    return;
  }

  panel.innerHTML = "<p class=\"hint\">Loading…</p>";
  const qs = `source=${encodeURIComponent(selection.source)}&path=${encodeURIComponent(selection.path)}`;

  let cap;
  try {
    cap = await getJSON(`/api/source-capability?${qs}`);
  } catch (e) {
    if (gen !== detailGen) return;
    panel.innerHTML = "";
    panel.appendChild(el("p", { class: "error" }, e.message));
    return;
  }
  if (gen !== detailGen) return;

  panel.innerHTML = "";
  panel.appendChild(el("h2", {}, cap.id));
  panel.appendChild(
    el("p", { class: "panel-meta" }, [
      kindBadge(cap.kind),
      el("span", {}, cap.source),
      el("span", { class: "mono hint" }, cap.path === "." ? "whole repository" : cap.path),
    ])
  );
  if (cap.description) panel.appendChild(el("p", { class: "panel-desc" }, cap.description));

  const brings = bringsBlock(cap.components);
  if (brings) panel.appendChild(brings);

  panel.appendChild(adoptBlock(cap, listBox));

  const docNames = cap.docs || [];
  if (docNames.length) {
    const initial = docNames.includes("SKILL.md") ? "SKILL.md" : docNames[0];
    const select = el("select", { "aria-label": "Preview file" }, docNames.map((n) => el("option", { value: n }, n)));
    select.value = initial;
    const holder = el("div", {});
    panel.appendChild(el("h3", { class: "section-label" }, "Documentation"));
    panel.appendChild(el("div", { class: "files" }, [select]));
    panel.appendChild(holder);

    const load = async (name) => {
      const pgen = ++previewGen;
      holder.innerHTML = "<p class=\"hint\">Loading…</p>";
      try {
        const file = await getJSON(`/api/source-file?${qs}&name=${encodeURIComponent(name)}`);
        if (pgen !== previewGen || gen !== detailGen) return;
        holder.innerHTML = "";
        holder.appendChild(previewNode(name, file.content, file.truncated));
      } catch (e) {
        if (pgen !== previewGen || gen !== detailGen) return;
        holder.innerHTML = "";
        holder.appendChild(el("p", { class: "error" }, `Failed to load ${name}: ${e.message}`));
      }
    };
    select.addEventListener("change", () => load(select.value));
    load(initial);
  }
}

// The "add this to my Library" control — and, once something has been added,
// the offer to push it out to the Agents. Install stays a second, explicit
// click: adopting is a Library decision, installing writes into ~/.cursor and
// ~/.claude, and those are not the same choice.
function adoptBlock(cap, listBox) {
  const box = el("div", { class: "adopt" });

  if (cap.adopted) {
    const where = `${cap.adopted.bucket}/${cap.adopted.id}`;
    box.appendChild(
      el("div", { class: "note ok" }, [
        el("p", {}, [
          el("span", { class: "badge in-library" }, "In Library"),
          ` ${where}`,
        ]),
        cap.adopted_match === "id"
          ? el("p", { class: "hint" }, "Matched by Id, not provenance — this Library copy may have come from somewhere else.")
          : null,
      ])
    );
    if (cap.adopted.behind_source) {
      box.appendChild(
        el("div", { class: "note warn" }, [
          el("p", {}, `Your copy was taken at ${shortSha(cap.adopted.revision)}; this Source is pinned at ${shortSha(cap.source_revision)}.`),
          el("p", { class: "hint" }, "Updating an adopted Library copy is not automated yet — adopt refuses to overwrite it."),
        ])
      );
    }
    return box;
  }

  const buckets = (exploreData && exploreData.buckets) || [];
  const NEW_BUCKET = "\u0000new";
  const select = el(
    "select",
    { "aria-label": "Bucket" },
    [
      ...buckets.map((b) => el("option", { value: b }, b)),
      el("option", { value: NEW_BUCKET }, "＋ New bucket…"),
    ]
  );
  const newBucket = el("input", { type: "text", placeholder: "bucket name", hidden: true, "aria-label": "New bucket name" });
  select.addEventListener("change", () => {
    newBucket.hidden = select.value !== NEW_BUCKET;
    if (!newBucket.hidden) newBucket.focus();
  });

  const button = el("button", { class: "btn wide", type: "button" }, "Add to Library");
  const noteHolder = el("div", {});

  button.addEventListener("click", async () => {
    const bucket = select.value === NEW_BUCKET ? newBucket.value.trim() : select.value;
    if (!bucket) {
      noteHolder.innerHTML = "";
      noteHolder.appendChild(noteNode({ tone: "bad", text: "Name a Bucket first." }));
      return;
    }
    button.disabled = true;
    button.textContent = "Adding…";
    noteHolder.innerHTML = "";

    try {
      const result = await postJSON("/api/adopt", {
        source: cap.source,
        path: cap.path,
        bucket,
        kind: cap.kind,
        id: cap.id,
      });
      if (result.ok === false) {
        noteHolder.appendChild(noteNode({ tone: "bad", text: result.error || "Adopt failed.", output: result.output }));
        button.disabled = false;
        button.textContent = "Add to Library";
        return;
      }
      button.textContent = "Added";
      noteHolder.appendChild(
        noteNode({
          tone: "ok",
          text: `${cap.id} is now a Library copy in ${bucket}.`,
          actions: installButton(),
        })
      );
      refreshExploreData(listBox);
    } catch (e) {
      noteHolder.appendChild(noteNode({ tone: "bad", text: e.message }));
      button.disabled = false;
      button.textContent = "Add to Library";
    }
  });

  box.appendChild(el("div", { class: "adopt-field" }, [el("label", {}, "Bucket"), select, newBucket]));
  box.appendChild(button);
  box.appendChild(noteHolder);
  return box;
}

function installButton() {
  const wrapper = el("div", {});
  const button = el("button", { class: "btn ghost wide", type: "button" }, "Install to detected Agents");
  const result = el("div", {});

  button.addEventListener("click", async () => {
    button.disabled = true;
    button.textContent = "Installing…";
    result.innerHTML = "";
    try {
      const data = await postJSON("/api/install");
      result.appendChild(
        noteNode({
          tone: data.ok === false ? "bad" : "ok",
          text: data.ok === false ? data.error || "Install failed." : "Installed.",
          output: data.output,
        })
      );
    } catch (e) {
      result.appendChild(noteNode({ tone: "bad", text: e.message }));
    } finally {
      button.disabled = false;
      button.textContent = "Install to detected Agents";
    }
  });

  wrapper.appendChild(button);
  wrapper.appendChild(result);
  return wrapper;
}

// ---------------------------------------------------------------------------
// Library
// ---------------------------------------------------------------------------

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

async function renderCapabilityDetail(panel, bucket, id, status) {
  const gen = ++detailGen;
  panel.innerHTML = "<p class=\"hint\">Loading…</p>";
  const qs = `bucket=${encodeURIComponent(bucket)}&id=${encodeURIComponent(id)}&status=${encodeURIComponent(status)}`;

  let meta;
  try {
    meta = await getJSON(`/api/capability?${qs}`);
  } catch (e) {
    if (gen !== detailGen) return;
    panel.innerHTML = "";
    panel.appendChild(el("p", { class: "error" }, e.message));
    return;
  }
  if (gen !== detailGen) return;

  // The server lists exactly the docs it will serve (any depth up to 3,
  // escaping symlinks excluded), so every option here is loadable.
  const docNames = meta.docs || [];
  const initial = docNames.includes("SKILL.md") ? "SKILL.md" : docNames[0];
  const holder = el("div", {});
  const select = el("select", { "aria-label": "Preview file" }, docNames.map((n) => el("option", { value: n }, n)));
  if (initial) select.value = initial;

  panel.innerHTML = "";
  panel.appendChild(el("h2", {}, meta.id));
  panel.appendChild(
    el("p", { class: "panel-meta" }, [
      kindBadge(meta.kind),
      el("span", { class: `badge ${meta.status}` }, meta.status),
      el("span", {}, meta.bucket),
    ])
  );
  const warnings = warningsBlock(meta.warnings);
  if (warnings) panel.appendChild(warnings);
  panel.appendChild(el("h3", { class: "section-label" }, "Provenance"));
  panel.appendChild(provenanceBlock(meta.provenance));
  panel.appendChild(el("p", { class: "mono hint" }, meta.path));

  if (docNames.length) {
    panel.appendChild(el("h3", { class: "section-label" }, "Documentation"));
    panel.appendChild(el("div", { class: "files" }, [select]));
    panel.appendChild(holder);
  } else {
    panel.appendChild(el("p", { class: "hint" }, "No previewable docs in this capability."));
  }

  const load = async (name) => {
    if (!name) return;
    const pgen = ++previewGen;
    holder.innerHTML = "<p class=\"hint\">Loading…</p>";
    try {
      const file = await getJSON(`/api/file?${qs}&name=${encodeURIComponent(name)}`);
      if (pgen !== previewGen || gen !== detailGen) return;
      holder.innerHTML = "";
      holder.appendChild(previewNode(name, file.content, file.truncated));
    } catch (e) {
      if (pgen !== previewGen || gen !== detailGen) return;
      holder.innerHTML = "";
      holder.appendChild(el("p", { class: "error" }, `Failed to load ${name}: ${e.message}`));
    }
  };
  select.addEventListener("change", () => load(select.value));
  if (initial) load(initial);
}

async function renderLibrary() {
  const gen = ++viewGen;
  app.innerHTML = "<p class=\"hint\">Loading Library…</p>";

  let data;
  try {
    data = await getJSON("/api/buckets");
  } catch (e) {
    if (gen !== viewGen) return;
    return errorView(`Failed to load Library: ${e.message}`);
  }
  if (gen !== viewGen) return;

  const buckets = data.buckets || {};
  const bucketNames = Object.keys(buckets).sort();
  const total = bucketNames.reduce((sum, name) => sum + buckets[name].length, 0);

  const listBox = el("div", { class: "split-list" });
  const panel = el("div", { class: "panel" });

  const paintList = () => {
    const needle = libraryState.query.trim().toLowerCase();
    listBox.innerHTML = "";
    let shown = 0;

    for (const bucket of bucketNames) {
      const caps = [...buckets[bucket]]
        .sort((a, b) => a.id.localeCompare(b.id))
        .filter((cap) => !needle || `${cap.id} ${bucket} ${cap.kind}`.toLowerCase().includes(needle));
      if (!caps.length) continue;
      shown += caps.length;

      const body = el("div", { class: "group-body" });
      for (const cap of caps) {
        const selected =
          libraryState.selected &&
          libraryState.selected.id === cap.id &&
          libraryState.selected.bucket === cap.bucket;
        const row = el("button", { type: "button", class: `row${selected ? " selected" : ""}` }, [
          kindBadge(cap.kind),
          el("span", { class: "row-main" }, el("span", { class: "row-title" }, el("span", { class: "row-id" }, cap.id))),
          el("span", { class: "row-marks" }, [
            cap.warnings && cap.warnings.length
              ? el("span", { class: "warn-mark", title: cap.warnings.join("\n") }, "!")
              : null,
            cap.status === "deprecated" ? el("span", { class: "badge deprecated" }, "deprecated") : null,
          ]),
        ]);
        row.addEventListener("click", () => {
          libraryState.selected = { bucket: cap.bucket, id: cap.id, status: cap.status };
          paintList();
          renderCapabilityDetail(panel, cap.bucket, cap.id, cap.status);
        });
        body.appendChild(row);
      }

      listBox.appendChild(
        el("details", { class: "group", open: true }, [
          el("summary", {}, [
            el("span", { class: "group-name" }, bucket),
            el("span", { class: "group-count" }, String(caps.length)),
          ]),
          body,
        ])
      );
    }

    if (!shown) {
      listBox.appendChild(
        el("div", { class: "empty-state" }, el("p", {}, needle ? "Nothing matches that search." : "No buckets in the Library yet."))
      );
    }
  };

  app.innerHTML = "";
  app.appendChild(
    toolbar("Library", `${total} capabilities · ${bucketNames.length} buckets`, null)
  );
  app.appendChild(
    el("div", { class: "filters" }, [
      searchField("Filter the Library…", libraryState.query, (value) => {
        libraryState.query = value;
        paintList();
      }),
    ])
  );
  app.appendChild(el("section", { class: "split" }, [listBox, panel]));

  paintList();
  if (libraryState.selected) {
    renderCapabilityDetail(panel, libraryState.selected.bucket, libraryState.selected.id, libraryState.selected.status);
  } else {
    panel.appendChild(
      el("div", { class: "empty-state" }, [
        el("p", {}, "Select a capability."),
        el("p", { class: "hint" }, "You'll see its Kind, Provenance and docs."),
      ])
    );
  }
}

// ---------------------------------------------------------------------------
// Change review
// ---------------------------------------------------------------------------

// Scope note shown on every Change review render. This page compares pinned
// Revisions to remote HEADs, and Library copies to the Revision they were
// taken at; saying so beats implying a depth the page does not have.
function reviewScopeNote() {
  return el("div", { class: "scope-note" }, [
    el("p", {}, [
      "Shows: each tracked Source's pinned Revision against its remote HEAD, as recorded by the last ",
      el("code", {}, "skima check"),
      ", plus every Library copy whose provenance Revision is older than the Source it came from.",
    ]),
    el("p", {}, [
      "Not yet shown: the file-level changes behind either. Updating an adopted Library copy is still a manual edit — ",
      el("code", {}, "adopt"),
      " refuses to overwrite one.",
    ]),
  ]);
}

async function renderChangeReview() {
  const gen = ++viewGen;
  app.innerHTML = "<p class=\"hint\">Loading Change review…</p>";

  let sourcesData;
  let statusData;
  let explore;
  try {
    [sourcesData, statusData, explore] = await Promise.all([
      getJSON("/api/sources"),
      getJSON("/api/status"),
      getJSON("/api/explore").catch(() => null),
    ]);
  } catch (e) {
    if (gen !== viewGen) return;
    return errorView(`Failed to load check status: ${e.message}`);
  }
  if (gen !== viewGen) return;

  const sources = sourcesData.sources || {};
  const statusSources = statusData.sources || {};
  const names = Object.keys(sources).sort();
  const controls = checkControls(statusData.checked_at, renderChangeReview);

  app.innerHTML = "";
  app.appendChild(toolbar("Change review", formatCheckedAt(statusData.checked_at), controls.actions));
  if (controls.detail) app.appendChild(controls.detail);
  app.appendChild(reviewScopeNote());

  if (statusData.checked_at) {
    const behindNames = names.filter((name) => (statusSources[name] || {}).status === "behind");
    const upToDate = names.filter((name) => (statusSources[name] || {}).status === "up-to-date");
    const flagged = names.filter((name) => !behindNames.includes(name) && !upToDate.includes(name));

    app.appendChild(el("h3", { class: "section-label" }, "Sources behind their remote"));
    if (!behindNames.length) {
      app.appendChild(el("div", { class: "empty-state" }, el("p", {}, "No tracked Source is behind its remote.")));
    } else {
      app.appendChild(
        el(
          "ul",
          { class: "review-list" },
          behindNames.map((name) => {
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
                " to move the pinned Revision, then review what changed before adopting or updating.",
              ]),
            ]);
          })
        )
      );
    }

    if (flagged.length) {
      app.appendChild(el("h3", { class: "section-label" }, "Needs attention"));
      app.appendChild(
        el(
          "ul",
          { class: "plain-list" },
          flagged.map((name) => {
            const st = statusSources[name] || {};
            return el("li", {}, [
              name,
              " ",
              statusBadge(st.status || "unknown"),
              st.error ? el("span", { class: "hint" }, ` — ${st.error}`) : null,
            ]);
          })
        )
      );
    }

    app.appendChild(
      el("p", { class: "hint" }, `${upToDate.length} of ${names.length} tracked Sources up to date.`)
    );
  } else {
    app.appendChild(
      el("div", { class: "empty-state" }, [
        el("p", {}, statusData.message || "Run skima check to see which Sources are behind."),
        el("p", { class: "hint" }, "Use “Run check” above, or run ./cli/skima check in a terminal."),
      ])
    );
  }

  // Library copies whose provenance Revision is older than the Source's pin.
  // This does not need a check to have run: both Revisions are already on disk.
  const drifted = ((explore && explore.sources) || []).flatMap((source) =>
    (source.capabilities || [])
      .filter((cap) => cap.adopted && cap.adopted.behind_source)
      .map((cap) => ({ source: source.name, cap }))
  );

  app.appendChild(el("h3", { class: "section-label" }, "Library copies behind their Source"));
  if (!drifted.length) {
    app.appendChild(
      el("div", { class: "empty-state" }, el("p", {}, "Every adopted Library copy matches the Revision its Source is pinned at."))
    );
  } else {
    app.appendChild(
      el(
        "ul",
        { class: "drift-list" },
        drifted.map(({ source, cap }) =>
          el("li", {}, [
            el("strong", {}, `${cap.adopted.bucket}/${cap.adopted.id}`),
            el("span", { class: "hint" }, `from ${source}`),
            el("span", { class: "mono hint" }, `${shortSha(cap.adopted.revision)} → ${shortSha((exploreSourceRevision(explore, source)))}`),
          ])
        )
      )
    );
  }
}

function exploreSourceRevision(explore, name) {
  const record = ((explore && explore.sources) || []).find((s) => s.name === name);
  return record ? record.revision : null;
}

// ---------------------------------------------------------------------------
// Router
// ---------------------------------------------------------------------------

const routes = {
  sources: renderSources,
  explore: renderExplore,
  library: renderLibrary,
  review: renderChangeReview,
};
// "updates" was the old name for Change review; keep old links working.
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
