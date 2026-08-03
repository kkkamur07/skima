const BOARD_URL = "/issues/board.json";

async function loadBoard() {
  const res = await fetch(BOARD_URL);
  if (!res.ok) {
    throw new Error(`Could not load ${BOARD_URL} (${res.status}). Run kanban-board regenerate first.`);
  }
  return res.json();
}

function renderLimits(board, el) {
  const { limits, counts } = board;
  const parts = [
    `In progress: ${counts.in_progress} / ${limits.in_progress_max}`,
    `AFK in progress: ${counts.in_progress_afk} / ${limits.in_progress_afk}`,
    `Review: ${counts.review} / ${limits.review_max}`,
  ];
  el.textContent = parts.join(" · ");
  const over =
    counts.in_progress > limits.in_progress_max ||
    counts.in_progress_afk > limits.in_progress_afk ||
    counts.review > limits.review_max;
  el.classList.toggle("warn", over);
}

function renderKanban(board, root) {
  root.innerHTML = "";
  for (const col of board.kanban.columns) {
    const colEl = document.createElement("div");
    colEl.className = "column";
    if (col.over_limit) colEl.classList.add("over-limit");

    const title = document.createElement("h3");
    title.textContent = `${col.name} (${col.issues.length})`;
    colEl.appendChild(title);

    for (const issue of col.issues) {
      const a = document.createElement("a");
      a.className = "card";
      a.href = `/issues/${issue.file}`;
      a.target = "_blank";
      const badge = document.createElement("span");
      badge.className = `badge ${issue.type.toLowerCase()}`;
      badge.textContent = issue.type;
      a.appendChild(badge);
      a.append(document.createTextNode(issue.title));
      colEl.appendChild(a);
    }
    root.appendChild(colEl);
  }
}

async function renderGraph(board, root) {
  if (!window.mermaid || !board.dag.mermaid) {
    root.textContent = "No Mermaid graph in board.json";
    return;
  }
  const { svg } = await window.mermaid.render("dag-graph", board.dag.mermaid);
  root.innerHTML = svg;
}

function renderLanes(board) {
  let el = document.getElementById("lanes");
  if (!el) {
    el = document.createElement("section");
    el.id = "lanes";
    el.className = "lanes panel";
    el.innerHTML = "<h2>Parallel lanes</h2><ul></ul>";
    document.querySelector("main.layout")?.after(el);
  }
  const ul = el.querySelector("ul");
  ul.innerHTML = "";
  for (const lane of board.dag.parallel_lanes) {
    const li = document.createElement("li");
    li.textContent = lane.join(", ");
    ul.appendChild(li);
  }
}

async function main() {
  const meta = document.getElementById("meta");
  const limitsEl = document.getElementById("limits");
  const boardRoot = document.getElementById("board");
  const graphRoot = document.getElementById("graph");

  try {
    const board = await loadBoard();
    meta.textContent = `Updated ${board.generated_at} · ${board.stats.total} issues`;
    renderLimits(board, limitsEl);
    renderKanban(board, boardRoot);
    await renderGraph(board, graphRoot);
    renderLanes(board);
  } catch (err) {
    meta.textContent = err.message;
    limitsEl.textContent =
      "Serve the repo root: python -m http.server 8080 then open http://localhost:8080/tools/issue-board/";
  }
}

main();
