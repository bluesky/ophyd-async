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
tests/container_tests/ # needs IOCs in containers; own pytest invocation, must not share a process with anything importing pyepics
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
- `tests/container_tests` must be a **separate** `pytest` invocation from `tests/system_tests` — never one session. They reach their IOC via the ca-gateway, which needs `EPICS_CA_NAME_SERVERS`, and EPICS reads that once at libca init; `epics/core` imports pyepics, which initialises libca during *collection*, so a shared session silently breaks them. Needs `EXAMPLE_SERVICES_PATH` (a host path).

## Testing conventions

- **No private-attribute access in tests** (`det._trigger_logic`, …) — call public methods and assert on output (e.g. `trigger()` then `describe()`), unless no public equivalent exists.
- **Happy path in one public-interface test; unhappy paths small.** For a multi-step lifecycle (e.g. `prepare` → `kickoff` → `complete`), write a *single* "happy path" test that drives the whole sequence through the public interface and asserts the observable end state — don't split one test per step. Then add small "unhappy path" tests (ordering errors, limit violations, injected failures); these stay majority-public-interface but may use mocks to shorten sequences or inject errors. The smell this avoids is a step-scoped test that has to call the *other* steps to set itself up (e.g. a `kickoff` test that also calls `prepare`+`complete`) — fold that into the happy path instead.
- **Parametrize normal + edge cases together** in one `@pytest.mark.parametrize`, not two functions.
- **Keep CI test stages to about a minute.** Each "Run tests" stage for unit tests and for system tests should take about a minute in CI. Take care to trim tests down in size, scale and sleeping to stay in that range.
- `set_mock_value(signal, value)` injects state; `init_devices(mock=True)` (async CM) builds devices; `assert_has_calls(device, [...])` from `ophyd_async.testing` checks PV writes in order.

## Docs & docstring conventions

- **ADRs (`docs/explanations/decisions/*.md`) and `README.md`: plain Markdown only** — no MyST, plain backticks. ADRs answer *why*, not *what*.
- **All other docs: MyST.** Cross-ref `[](#LABEL_NAME)` (define with `(LABEL_NAME)=` above the heading) — never bare URL fragments, never `[label](#path.to.Symbol)`. Admonitions: fenced ` ```{note} `, not RST `.. note::`.
- **Docstrings** are Markdown (sphinx-autodoc2 + MyST): `:param name:` lists right after the summary, before code blocks; no types (from annotations), no Google `Args:`/`Returns:`; single backticks; only link symbols in a module `__all__`.
- **Diataxis:** tutorials=learning, how-to=task, explanations=rationale (ADRs), reference=facts. One authoritative source per fact; cross-link.

## Code conventions

- **No `ABC` base needed** — `@abstractmethod` without `ABC`/`ABCMeta` is intentional; pyright enforces implementation statically.
- **A new `TypeVar` needs an entry in `docs/conf.py`.** Docs build with `nitpicky = True` and warnings-as-errors, and TypeVars never resolve as references, so every one is listed by qualified name (`ophyd_async.core._utils.T`, …) in the `nitpick_ignore` list near the end of `conf.py`. Miss it and `tox -e docs` fails on `reference target not found` while every other env stays green. Prefer declaring TypeVars in the `_utils.py` of their package, next to the existing ones, so the list stays in one place.

## Updating this guide

Say **"Update CLAUDE.md with…"** to persist a convention (Copilot has no auto-memory — it must be written here). Claude also keeps private auto-memory under `~/.claude/projects/…/memory/`; durable, shareable rules belong here.
