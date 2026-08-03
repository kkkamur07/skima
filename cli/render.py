#!/usr/bin/env python3
"""Terminal renderer for the Skima CLI — the optional pretty half of `cli/skima`.

`cli/skima` builds FS-separated rows (see the FS comment in that script for why
the separator is \\x1f) and pipes them here. This script turns them into rich
tables, rules and summaries. It is strictly a presentation layer: it reads rows
on stdin, writes text on stdout, and knows nothing about the Library, Sources or
any file format.

It is OPTIONAL by design. Skima's promise is that it runs from a fresh clone
with nothing installed, so if `rich` is not importable — or anything at all goes
wrong here — this script exits with FALLBACK (97) having written nothing to
stdout, and `cli/skima` prints its own plain output instead. It never prints an
import error, never installs anything, and never decides an exit code for the
command that invoked it.

Output is only ever styled when `cli/skima` says stdout is a real terminal
(SKIMA_COLOR=1, which is exactly its supports_color() signal: a TTY, NO_COLOR
unset, TERM not "dumb"). Otherwise the Console is pinned to no colour system, no
box drawing and a fixed width, because `web/server.py` captures this output with
subprocess.run() and shows it verbatim in a browser <pre>, where escapes and
borders would be garbage. Rich's own terminal auto-detection is not consulted:
the Console writes into a StringIO buffer, so it could not detect anything
useful anyway, and the decision has already been made by the caller.

Buffering into that StringIO is also what makes the fallback safe — stdout is
written exactly once, at the very end, only if the whole render succeeded.

Exit codes:
  0   rendered; stdout holds the finished output
  97  rich unavailable, or the render failed; caller should print plain output
"""

import io
import json
import os
import shutil
import sys

# Same separator convention as cli/skima: \x1f (ASCII Unit Separator) survives
# empty fields, which a tab-based split in bash would silently collapse.
FS = "\x1f"

FALLBACK = 97

STATUS_STYLE = {"up-to-date": "green", "behind": "yellow", "unreachable": "red"}
STATUS_GLYPH = {"up-to-date": "✔", "behind": "↑", "unreachable": "✖"}

RESULT_STYLE = {
    "symlinked": "green",
    "copied": "cyan",
    "up-to-date": "dim",
    "failed": "red",
}


# ---------------------------------------------------------------------------
# Console
# ---------------------------------------------------------------------------


def build_console():
    """Returns (console, buffer, color). Never auto-detects: the caller decided."""
    from rich.console import Console

    color = os.environ.get("SKIMA_COLOR") == "1"
    buf = io.StringIO()
    if color:
        width = shutil.get_terminal_size(fallback=(100, 24)).columns
        width = max(60, min(width, 110))
        console = Console(
            file=buf,
            force_terminal=True,
            force_interactive=False,
            width=width,
            markup=False,
            emoji=False,
            highlight=False,
        )
    else:
        # Pinned hard: no colour system means rich emits no escape sequence at
        # all (not even bold), and a fixed width keeps captured output stable.
        console = Console(
            file=buf,
            force_terminal=False,
            force_interactive=False,
            color_system=None,
            no_color=True,
            width=100,
            markup=False,
            emoji=False,
            highlight=False,
        )
    return console, buf, color


def read_rows():
    """Parses FS-separated rows from stdin. Empty when stdin is a terminal."""
    if sys.stdin is None or sys.stdin.isatty():
        return []
    rows = []
    for line in sys.stdin.read().split("\n"):
        if line:
            rows.append(line.split(FS))
    return rows


def field(row, index, default=""):
    return row[index] if len(row) > index else default


# ---------------------------------------------------------------------------
# Shared pieces
# ---------------------------------------------------------------------------


def section(console, color, title, subtitle=""):
    """A section heading. A rule when styled; a bare line when plain."""
    from rich.rule import Rule
    from rich.text import Text

    if color:
        text = Text(title, style="bold")
        if subtitle:
            text.append("  " + subtitle, style="dim")
        console.print(Rule(text, align="left", style="dim", characters="─"))
        console.print()
    else:
        console.print(title if not subtitle else "%s — %s" % (title, subtitle))
        console.print()


def new_table(color, **kwargs):
    from rich import box
    from rich.table import Table

    return Table(
        box=box.SIMPLE_HEAD if color else None,
        show_edge=False,
        pad_edge=False,
        expand=False,
        header_style="bold" if color else "none",
        border_style="dim" if color else "none",
        **kwargs
    )


def summary(console, color, parts, style="dim", spaced=True):
    """A one-line summary: 'a · b · c' when styled, 'a   b   c' when plain."""
    parts = [p for p in parts if p]
    if not parts:
        return
    if spaced:
        console.print()
    sep = " · " if color else "   "
    console.print(sep.join(parts), style=style if color else "none")


def note(console, color, text, style="dim"):
    console.print(text, style=style if color else "none")


def status_cell(color, status):
    from rich.text import Text

    if not color:
        return Text(status)
    glyph = STATUS_GLYPH.get(status)
    label = "%s %s" % (glyph, status) if glyph else status
    return Text(label, style=STATUS_STYLE.get(status, ""))


def plural(n, one, many):
    return one if n == 1 else many


def kv_rows(console, color, pairs):
    """Aligned label/value lines for a small header block."""
    from rich.text import Text

    width = max(len(k) for k, _ in pairs)
    for key, value in pairs:
        line = Text("  ")
        line.append(("%-*s  " % (width, key)), style="dim" if color else "none")
        line.append(value)
        console.print(line)


def warnings_block(console, color, warnings):
    if not warnings:
        return
    section(
        console,
        color,
        "Library validation warnings",
        "the directory is authoritative",
    )
    for text in warnings:
        note(console, color, "  " + text, style="yellow")
    console.print()


# ---------------------------------------------------------------------------
# check — Source pins vs remote HEAD
#   rows: name FS url FS pinned FS remote FS status FS error
# ---------------------------------------------------------------------------


def render_check(console, color, rows, argv):
    from rich.text import Text

    title = argv[0] if argv else "Check"
    section(console, color, title, "pinned Revision vs remote HEAD")

    table = new_table(color)
    table.add_column("SOURCE", no_wrap=True, style="cyan" if color else "none")
    table.add_column("PINNED", no_wrap=True, style="dim" if color else "none")
    table.add_column("REMOTE", no_wrap=True)
    table.add_column("STATUS", no_wrap=True)

    counts = {}
    errors = []
    for row in rows:
        name = field(row, 0)
        pinned = field(row, 2)
        remote = field(row, 3)
        status = field(row, 4)
        error = field(row, 5)
        counts[status] = counts.get(status, 0) + 1
        if error:
            errors.append((name, error))

        remote_style = "yellow" if (color and status == "behind") else ("dim" if color else "none")
        table.add_row(
            name,
            pinned[:12] or "—",
            Text(remote[:12] or "—", style=remote_style),
            status_cell(color, status),
        )

    console.print(table)

    total = len(rows)
    parts = ["%d %s" % (total, plural(total, "Source", "Sources"))]
    for status in ("up-to-date", "behind", "unreachable"):
        if counts.get(status):
            parts.append("%d %s" % (counts[status], status))
    summary(console, color, parts)

    if errors:
        console.print()
        note(console, color, "Errors", style="red")
        for name, error in errors:
            note(console, color, "  %s: %s" % (name, error))
    return 0


# ---------------------------------------------------------------------------
# status — pretty-print .skima/status.json (no stdin; path in argv)
# ---------------------------------------------------------------------------


def render_status(console, color, argv):
    from rich.text import Text

    with open(argv[0], encoding="utf-8") as handle:
        data = json.load(handle)

    checked_at = data.get("checked_at") or "unknown"
    sources = data.get("sources", {}) or {}

    section(console, color, "Status", "as of the last Check")

    if not sources:
        note(console, color, "No sources recorded.", style="none")
        return 0

    table = new_table(color)
    table.add_column("SOURCE", no_wrap=True, style="cyan" if color else "none")
    table.add_column("PINNED", no_wrap=True, style="dim" if color else "none")
    table.add_column("REMOTE", no_wrap=True)
    table.add_column("STATUS", no_wrap=True)

    counts = {}
    errors = []
    for name in sorted(sources):
        entry = sources[name] or {}
        pinned = (entry.get("pinned") or "")[:12] or "—"
        remote = (entry.get("remote") or "")[:12] or "—"
        status = entry.get("status", "unknown")
        counts[status] = counts.get(status, 0) + 1
        if entry.get("error"):
            errors.append((name, entry["error"]))
        remote_style = "yellow" if (color and status == "behind") else ("dim" if color else "none")
        table.add_row(name, pinned, Text(remote, style=remote_style), status_cell(color, status))

    console.print(table)

    parts = ["checked %s" % checked_at]
    for status in sorted(counts):
        parts.append("%d %s" % (counts[status], status))
    summary(console, color, parts)

    if errors:
        console.print()
        note(console, color, "Errors", style="red")
        for name, error in errors:
            note(console, color, "  %s: %s" % (name, error))
    return 0


# ---------------------------------------------------------------------------
# list — active Capabilities
#   rows: warn FS text | cap FS bucket FS id | dep FS count
# ---------------------------------------------------------------------------


def render_list(console, color, rows):
    from rich.text import Text

    warnings = [field(r, 1) for r in rows if field(r, 0) == "warn"]
    caps = [(field(r, 1), field(r, 2)) for r in rows if field(r, 0) == "cap"]
    deprecated = 0
    for row in rows:
        if field(row, 0) == "dep":
            try:
                deprecated = int(field(row, 1) or 0)
            except ValueError:
                deprecated = 0

    warnings_block(console, color, warnings)
    section(console, color, "Library", "active Capabilities")

    table = new_table(color)
    table.add_column("BUCKET", no_wrap=True, style="magenta" if color else "none")
    table.add_column("ID", no_wrap=True)

    previous = None
    for bucket, cap_id in caps:
        shown = "" if bucket == previous else bucket
        previous = bucket
        table.add_row(shown, Text(cap_id, style="cyan" if color else "none"))
    console.print(table)

    buckets = len(set(b for b, _ in caps))
    parts = [
        "%d active %s" % (len(caps), plural(len(caps), "Capability", "Capabilities")),
        "%d %s" % (buckets, plural(buckets, "Bucket", "Buckets")),
    ]
    if deprecated:
        parts.append("%d deprecated (never installed)" % deprecated)
    summary(console, color, parts)
    return 0


# ---------------------------------------------------------------------------
# targets — detected Agents
#   rows: target FS label FS skills-path FS detect-path FS state
#         state: detected | detected-new | skipped
# ---------------------------------------------------------------------------


def render_targets(console, color, rows):
    from rich.text import Text

    section(console, color, "Install targets", "Agents detected on this machine")

    table = new_table(color)
    table.add_column("AGENT", no_wrap=True)
    table.add_column("INSTALLS INTO", no_wrap=True, style="cyan" if color else "none")
    table.add_column("DETECTION", overflow="fold")

    detected = 0
    for row in rows:
        label = field(row, 1)
        skills = field(row, 2)
        detect = field(row, 3)
        state = field(row, 4)
        if state == "skipped":
            cell = Text("✖ skipped" if color else "skipped", style="dim" if color else "none")
            cell.append(
                " (%s not found — Agent not installed)" % detect,
                style="dim" if color else "none",
            )
            agent = Text(label, style="dim" if color else "none")
            path = Text(skills, style="dim" if color else "none")
        else:
            detected += 1
            cell = Text("✔ detected" if color else "detected", style="green" if color else "none")
            if state == "detected-new":
                tail = " (%s exists; skills dir created on first install)" % detect
            else:
                tail = " (%s exists)" % detect
            cell.append(tail, style="dim" if color else "none")
            agent = Text(label)
            path = Text(skills)
        table.add_row(agent, path, cell)

    console.print(table)

    if detected == 0:
        note(
            console,
            color,
            "No Agents detected. Skima will not create directories for Agents that are not installed.",
            style="yellow",
        )
    else:
        summary(
            console,
            color,
            [
                "%d install %s detected" % (detected, plural(detected, "target", "targets")),
                "skipped Agents are never written to",
            ],
        )
    return 0


# ---------------------------------------------------------------------------
# install
#   rows: head FS root FS library FS active-count
#         warn FS text
#         skipped FS label FS detect-path
#         notargets
#         targetfail FS label FS path
#         target FS label FS path FS linked FS copied FS uptodate FS failed FS stale
#         fail FS label FS text
#         foreign FS label FS text
# ---------------------------------------------------------------------------


def render_install(console, color, rows):
    from rich.text import Text

    head = next((r for r in rows if field(r, 0) == "head"), None)
    warnings = [field(r, 1) for r in rows if field(r, 0) == "warn"]
    skipped = [(field(r, 1), field(r, 2)) for r in rows if field(r, 0) == "skipped"]
    fails = {}
    foreign = {}
    for row in rows:
        if field(row, 0) == "fail":
            fails.setdefault(field(row, 1), []).append(field(row, 2))
        elif field(row, 0) == "foreign":
            foreign.setdefault(field(row, 1), []).append(field(row, 2))

    warnings_block(console, color, warnings)
    section(console, color, "Install", "Library → detected Install targets")

    if head:
        kv_rows(
            console,
            color,
            [
                ("monorepo root", field(head, 1)),
                ("library", field(head, 2)),
                ("active Capabilities", field(head, 3)),
            ],
        )
        console.print()

    if skipped:
        note(console, color, "Skipped — Agent not detected, nothing created")
        for label, detect in skipped:
            note(console, color, "  %s  (%s not found)" % (label, detect))
        console.print()

    if any(field(r, 0) == "notargets" for r in rows):
        note(console, color, "No install targets detected — nothing to do.", style="yellow")
        return 0

    table = new_table(color)
    table.add_column("TARGET", no_wrap=True)
    table.add_column("SYMLINKED", justify="right", no_wrap=True)
    table.add_column("COPIED", justify="right", no_wrap=True)
    table.add_column("UP-TO-DATE", justify="right", no_wrap=True)
    table.add_column("FAILED", justify="right", no_wrap=True)
    table.add_column("PATH", overflow="fold", style="dim" if color else "none")

    totals = {"symlinked": 0, "copied": 0, "up-to-date": 0, "failed": 0}
    stale_total = 0
    any_target = False

    def count_cell(value, kind):
        if not color:
            return Text(str(value))
        if value == 0:
            return Text("0", style="dim")
        return Text(str(value), style=RESULT_STYLE[kind])

    for row in rows:
        kind = field(row, 0)
        if kind == "targetfail":
            any_target = True
            table.add_row(
                Text(field(row, 1), style="red" if color else "none"),
                Text("—"), Text("—"), Text("—"),
                Text("FAILED", style="red" if color else "none"),
                field(row, 2),
            )
            continue
        if kind != "target":
            continue
        any_target = True
        label = field(row, 1)
        linked = int(field(row, 3) or 0)
        copied = int(field(row, 4) or 0)
        uptodate = int(field(row, 5) or 0)
        failed = int(field(row, 6) or 0)
        stale = int(field(row, 7) or 0)
        totals["symlinked"] += linked
        totals["copied"] += copied
        totals["up-to-date"] += uptodate
        totals["failed"] += failed
        stale_total += stale
        table.add_row(
            Text(label, style="bold" if color else "none"),
            count_cell(linked, "symlinked"),
            count_cell(copied, "copied"),
            count_cell(uptodate, "up-to-date"),
            count_cell(failed, "failed"),
            field(row, 2),
        )

    if any_target:
        console.print(table)

    for label in sorted(fails):
        console.print()
        note(console, color, "%s — failed" % label, style="red")
        for text in fails[label]:
            note(console, color, "  " + text, style="red")

    for label in sorted(foreign):
        console.print()
        note(console, color, "%s — not managed by Skima (left untouched)" % label)
        for text in foreign[label]:
            note(console, color, "  " + text)

    parts = []
    for kind in ("symlinked", "copied", "up-to-date", "failed"):
        if totals[kind] or kind in ("symlinked", "up-to-date"):
            parts.append("%d %s" % (totals[kind], kind))
    if stale_total:
        parts.append(
            "%d stale %s removed" % (stale_total, plural(stale_total, "symlink", "symlinks"))
        )
    summary(console, color, parts, style="red" if (color and totals["failed"]) else "dim")
    return 0


# ---------------------------------------------------------------------------
# sync-summary
#   rows: ok FS name | fail FS name
# ---------------------------------------------------------------------------


def render_sync_summary(console, color, rows):
    synced = [field(r, 1) for r in rows if field(r, 0) == "ok"]
    failed = [field(r, 1) for r in rows if field(r, 0) == "fail"]

    section(console, color, "Sync summary")
    parts = ["%d synced" % len(synced)]
    if failed:
        parts.append("%d failed" % len(failed))
    summary(console, color, parts, style="red" if (color and failed) else "dim", spaced=False)
    if synced:
        note(console, color, "  synced: " + ", ".join(synced), style="green")
    if failed:
        note(console, color, "  failed: " + ", ".join(failed), style="red")
    return 0


# ---------------------------------------------------------------------------
# adopt
#   row: id FS kind FS bucket FS library-path FS source FS upstream FS revision
# ---------------------------------------------------------------------------


def render_adopt(console, color, rows):
    if not rows:
        return FALLBACK
    row = rows[0]
    cap_id = field(row, 0)
    revision = field(row, 6)

    section(console, color, "Adopted %s" % cap_id, "Source → Library copy")
    kv_rows(
        console,
        color,
        [
            ("kind", field(row, 1)),
            ("bucket", field(row, 2)),
            ("library", field(row, 3)),
            ("provenance", "%s %s @ %s" % (field(row, 4), field(row, 5), revision[:12] or "—")),
        ],
    )
    console.print()
    note(
        console,
        color,
        "Run 'skima install' to make it available on every detected Install target.",
    )
    return 0


# ---------------------------------------------------------------------------
# help
# ---------------------------------------------------------------------------

COMMANDS = [
    (
        "check",
        "Compare each Source's pinned Revision to its remote HEAD (git ls-remote, no clone). "
        "Prints a table and writes .skima/status.json. Exits 1 only when every Source is unreachable.",
    ),
    (
        "sync [name...]",
        "Refresh Source tree(s) from remote HEAD: shallow clone, rsync into sources/<name>/ "
        "(excluding .git), update the pinned Revision in sources.json, then re-check just those "
        "Sources and merge into .skima/status.json. With no names, refreshes every Source. "
        "Never touches library/ — Adoption stays a deliberate step.",
    ),
    (
        "adopt <source> [upstream-path]",
        "Adopt a Capability out of a Source tree into the Library as an editable Library copy, with "
        "provenance pinned to that Source's current Revision. Options: --bucket <bucket> (required), "
        "--kind <kind>, --id <id>. upstream-path is relative to sources/<source>/ and defaults to \".\" "
        "(the whole repository). The Id defaults to the upstream directory name; the Kind is inferred "
        "(plugin if the directory ships .claude-plugin/plugin.json, else skill). Refuses if the Id is "
        "already in the Library — updating a Library copy is a Change review decision, not a re-adopt. "
        "The Web UI's \"Add to Library\" runs this same command.",
    ),
    ("status", "Pretty-print .skima/status.json (run 'skima check' first if it does not exist yet)."),
    (
        "install",
        "Install every active Capability into each detected Install target (symlink first, copy "
        "fallback). Agents that are not detected are skipped; no directory is created for them.",
    ),
    ("list", "List active Capabilities with their Bucket, plus any Library validation warnings."),
    ("targets", "Show which Agents were detected and which were skipped."),
    ("root", "Print the monorepo root."),
    ("help", "Show this help."),
]

ENVIRONMENT = [
    ("NO_COLOR", "Disable colored output (also disabled when stdout is not a TTY)."),
    (
        "SKIMA_NETWORK_TIMEOUT",
        "Seconds to wait per network call before treating a Source as unreachable (default: 10).",
    ),
]

EXIT_CODES = [
    ("0", "success"),
    ("1", "operational failure"),
    ("2", "usage error"),
    ("3", "missing dependency"),
]


def render_help(console, color):
    from rich.text import Text

    header = Text("skima", style="bold cyan" if color else "none")
    header.append("  personal control plane for installing agent capabilities",
                  style="dim" if color else "none")
    console.print(header)
    console.print()

    section(console, color, "Usage")
    note(console, color, "  skima <command> [arguments]", style="none")
    console.print()

    section(console, color, "Commands")
    table = new_table(color, show_header=False, padding=(0, 2, 0, 0))
    table.add_column("COMMAND", no_wrap=True, style="cyan" if color else "none")
    table.add_column("WHAT IT DOES", overflow="fold", ratio=1)
    for name, description in COMMANDS:
        table.add_row("  " + name, description)
    console.print(table)
    console.print()

    section(console, color, "Environment")
    env_table = new_table(color, show_header=False, padding=(0, 2, 0, 0))
    env_table.add_column("VAR", no_wrap=True, style="magenta" if color else "none")
    env_table.add_column("EFFECT", overflow="fold", ratio=1)
    for name, description in ENVIRONMENT:
        env_table.add_row("  " + name, description)
    console.print(env_table)
    console.print()

    section(console, color, "Exit codes")
    sep = "  ·  " if color else "   "
    note(console, color, "  " + sep.join("%s %s" % (c, t) for c, t in EXIT_CODES))
    return 0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def dispatch(command, argv, console, color):
    if command == "check":
        return render_check(console, color, read_rows(), argv)
    if command == "status":
        if not argv:
            return FALLBACK
        return render_status(console, color, argv)
    if command == "list":
        return render_list(console, color, read_rows())
    if command == "targets":
        return render_targets(console, color, read_rows())
    if command == "install":
        return render_install(console, color, read_rows())
    if command == "sync-summary":
        return render_sync_summary(console, color, read_rows())
    if command == "adopt":
        return render_adopt(console, color, read_rows())
    if command == "help":
        return render_help(console, color)
    return FALLBACK


def main(argv):
    if not argv:
        return FALLBACK
    command = argv[0]

    try:
        import rich  # noqa: F401
    except Exception:
        return FALLBACK

    if command == "probe":
        return 0

    try:
        console, buf, color = build_console()
        code = dispatch(command, argv[1:], console, color)
        if code != 0:
            return code
        text = buf.getvalue()
    except Exception:
        # Presentation must never break a command. Say nothing, let the caller
        # print its own plain output.
        return FALLBACK

    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
