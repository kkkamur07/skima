# Install prefers symlink, copy as fallback

Agents should see Library edits without a re-install when possible. Skima's Install therefore creates symlinks from each Install target into the Library copy by default, and falls back to copying files only when a symlink cannot be used for that Agent or Kind.
