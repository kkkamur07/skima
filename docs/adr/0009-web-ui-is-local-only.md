# The Web UI is local-only

**Change review** and browsing the Library want a real interface — diffs and trees are miserable in a terminal. That makes a web surface the obvious shape, and a web surface invites hosting it.

We deferred hosting for v1. A hosted Web UI needs accounts, authorization, and a way to reach a Library that lives on one laptop; none of that serves a personal, single-user control plane. The whole product is a git-backed directory on the user's machine, and the UI is a lens onto it.

We chose: `web/` binds `127.0.0.1` only and is served on demand. There is no multi-user model and no auth, because there is exactly one user and the loopback bind is the boundary.

That boundary needs defending properly rather than assumed. A loopback bind stops remote hosts, but it does not stop the *user's own browser* from being turned against the server by any page they happen to have open — a cross-site POST still originates from 127.0.0.1, so checking the client address proves nothing. Nor does it stop an attacker domain rebinding DNS to 127.0.0.1 to become same-origin and read the API. So state-changing requests validate `Origin`, all requests validate `Host` against an expected localhost value, and file serving stays confined to the repo by resolved-path containment. These are load-bearing for the local-only decision, not extras.

The server also stays dependency-free Python stdlib with no build step, so it runs from a fresh clone with nothing installed.

Consequence: nothing about the UI may assume a trusted browser context. If hosting is ever revisited it is a new decision with a real authorization model, not a change of bind address.
