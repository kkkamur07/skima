# Skima monorepo: app, Library, and Sources together

Skima needs one place to version the product, curated Library copies, and tracked upstream Sources. We considered a Library-only GitHub repo with a local Source cache, git submodules, and nested `.git` clones. We chose a single Monorepo with committed Source trees (no nested git) and a flat top-level layout (`sources/`, `library/`, `cli/`, `web/`) so sync, Change review, and install all share one history with the least ceremony.
