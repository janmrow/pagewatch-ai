# Agent instructions

- Keep the implementation simple and within the current task. Do not add speculative abstractions or code for later milestones.
- Use uv for the Python environment and dependencies, Ruff for lint and formatting, and pytest for behavior tests.
- Run `./scripts/verify.sh` after changes and report what passed or failed.
- A task is done when its acceptance criteria are met, behavior has sensible tests, Ruff and pytest pass, dependencies are necessary, the diff is understandable, and public documentation reflects public behavior changes.
- Complete each milestone as a working system with green verify before starting the next one.
- Keep changes unstaged and uncommitted unless the user explicitly asks otherwise.
