---
name: python-dev
description: Python code conventions and the check workflow after code changes (ruff, pyrefly, pytest, import and module layout, error messages). Use whenever writing, modifying or refactoring Python code in a project that has opted in to this skill.
metadata:
  version: 2026-11-06
---

# Python development conventions

Run everything through `uv` (see `AGENTS.md`).

## Checks after changing Python code

Run in this order and fix problems before moving on:

1. `uv run ruff format`
2. `uv run ruff check --fix`
3. `uv run pyrefly check` (the scope, for example only `src/`, is configured in `pyproject.toml`)
4. `uv run pytest`

## Code structure and imports

- Put `from __future__ import annotations` as the very first import in every `.py` file.
- Order modules from high to low abstraction: public API functions and classes at the top, then progressively lower-level details, with private helpers at the bottom.
- In unit and integration tests, invert this: helpers, fixtures and setup first, then the test functions and classes.

## Style

- Do not add a magic trailing comma to force a multiline layout. Let `ruff format` decide, and keep the trailing commas it adds itself.

## Error messages

- Say exactly what went wrong and name the invalid value with `!r`.
- Follow with actionable guidance on how to fix it.
- Example: `f"Invalid mode {mode!r}. Must be one of 'read' or 'write'."`

## Docstrings and tests

- For docstrings, use the `python-docstrings` skill.
- For unit and integration tests, use the `python-unit-tests` skill.
