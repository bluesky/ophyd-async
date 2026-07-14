# ophyd-async — agent & contributor conventions

Scaffolded from the [DiamondLightSource python-copier-template](https://diamondlightsource.github.io/python-copier-template/main/how-to.html).
Single source of conventions for all agents (Claude, Copilot) and contributors — cross-link, don't duplicate.

## Repository layout

```
src/ophyd_async/      # library source
  core/               # base classes: Device, Signal, StandardDetector, ...
  epics/ fastcs/ tango/ sim/   # control-system backends + sim (no hardware)
  plan_stubs/         # bluesky plan stubs
  testing/            # test helpers + OneOfEverything reference devices
docs/                 # Sphinx docs (MyST + Diataxis)
tests/unit_tests/     # fast, mock-based, single-process (soft signals, connect(mock=True))
tests/system_tests/   # needs a live external process (e.g. epics/core → EPICS IOC, tango/core → Tango device server)
pyproject.toml        # all tool config: pytest, ruff, pyright, tox
```

## Build & validate

```
pytest tests/unit_tests/path/to/test_file.py   # single file, fast
tox -e tests            # full suite + coverage → cov.xml
tox -e type-checking    # pyright (standard mode)
tox -e pre-commit       # ruff format + lint (all files)
tox -e docs             # Sphinx build → build/html/
tox -p                  # all envs in parallel (CI equivalent)
```

- `ruff` runs on save in VS Code; `pytest` also runs doctests in `docs/` and `src/`.
- **pyright ad hoc** (not via tox): always `pyright src --pythonpath "$(which python)"`. A bare `pyright src` reports ~115 false positives here (stale numpy-stub resolution) — never trust its count.
- System tests need a live backend; scope runs to `tests/system_tests/epics` or `.../tango` and run 2–3× to catch flakiness.

## Testing conventions

- **No private-attribute access in tests** (`det._trigger_logic`, …) — call public methods and assert on output (e.g. `trigger()` then `describe()`), unless no public equivalent exists.
- **Parametrize normal + edge cases together** in one `@pytest.mark.parametrize`, not two functions.
- `set_mock_value(signal, value)` injects state; `init_devices(mock=True)` (async CM) builds devices; `assert_has_calls(device, [...])` from `ophyd_async.testing` checks PV writes in order.

## Docs & docstring conventions

- **ADRs (`docs/explanations/decisions/*.md`) and `README.md`: plain Markdown only** — no MyST, plain backticks. ADRs answer *why*, not *what*.
- **All other docs: MyST.** Cross-ref `[](#LABEL_NAME)` (define with `(LABEL_NAME)=` above the heading) — never bare URL fragments, never `[label](#path.to.Symbol)`. Admonitions: fenced ` ```{note} `, not RST `.. note::`.
- **Docstrings** are Markdown (sphinx-autodoc2 + MyST): `:param name:` lists right after the summary, before code blocks; no types (from annotations), no Google `Args:`/`Returns:`; single backticks; only link symbols in a module `__all__`.
- **Diataxis:** tutorials=learning, how-to=task, explanations=rationale (ADRs), reference=facts. One authoritative source per fact; cross-link.

## Code conventions

- **No `ABC` base needed** — `@abstractmethod` without `ABC`/`ABCMeta` is intentional; pyright enforces implementation statically.

## Working pattern (long, multi-session tasks)

- **STATE.md is local-only** (git-ignored via `.claude/plans/`) — a private scratchpad, **never committed**. The durable, shareable record is the git history + the GitHub issue, not this file.
- **Session start:** if `.claude/plans/<active-task>/STATE.md` exists, read it, verify against `git status` and `git log --oneline -10`, and flag discrepancies *before* doing work.
- **After each subtask:** update STATE.md (uncommitted) and make a small, focused commit of just the code change. Small, frequent commits; messages say *why*.
- **STATE.md schema:** Done (with SHAs) / In progress (with exact next command) / Decisions + rationale / Invariants / Open questions.
- **Settled design decisions** get mirrored to the relevant GitHub issue, not left only in the local STATE.md. Make an ADR as part of the PR for anything substantial.
- **One PR-sized slice per session.** Never rely on context surviving across sessions — files and git are the source of truth.
- **PR closes its issues:** a PR body must have a `Fixes #NNN` (or `Closes #NNN`) line for **every** issue it resolves, so GitHub auto-closes them on merge — one line per issue on a multi-issue PR. After editing a PR body, re-read it back (web-UI edits can trim it) and confirm each closing line is present.

## Updating this guide

Say **"Update CLAUDE.md with…"** to persist a convention (Copilot has no auto-memory — it must be written here). Claude also keeps private auto-memory under `~/.claude/projects/…/memory/`; durable, shareable rules belong here.
