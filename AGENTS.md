# Clone Hero Tools — Agent Instructions

This repository is a single Python CLI tool focused on one workflow:
take Expert-only Clone Hero charts and generate Hard, Medium, and Easy.

## Scope

- Main entrypoint: `ch-chart-fix.py`
- Inputs: song folder, songs root (`--batch`), or `.zip`
- Core operations:
	- Zip extraction (wrapped + flat layouts)
	- MIDI-to-chart conversion when needed (`.mid` / `.midi`)
	- Difficulty generation from Expert to Hard/Medium/Easy

## Source Layout

```
ch-chart-fix.py
tests/
	test_ch_chart_fix.py
	test_cli_smoke.py
local_ci.sh
pyproject.toml
.flake8
```

## Environment & Commands

Use uv-managed Python and dependencies (Python 3.14):

```bash
uv venv --python 3.14
uv sync
uv sync --group dev
```

Primary runtime usage:

```bash
uv run ch-chart-fix.py /path/to/song-folder
uv run ch-chart-fix.py /path/to/song.zip
uv run ch-chart-fix.py --batch /path/to/songs-root
uv run ch-chart-fix.py --dry-run /path/to/input
```

Validation:

```bash
bash local_ci.sh
bash local_ci.sh --fix
```

Equivalent manual checks:

```bash
uv run black --check ch-chart-fix.py tests/
uv run ruff check ch-chart-fix.py tests/
uv run python -m flake8 ch-chart-fix.py tests/
uv run pytest -v
```

## Implementation Conventions

- Keep UTF-8 with BOM tolerance on reads for charts (`utf-8-sig`, `errors='ignore'`).
- Preserve `.chart` semantics:
	- `N` notes, `S 2` star power, `B` BPM, `TS` time signature, `E` events.
- Preserve downchart behavior:
	- Hard: pass-through notes, keep force modifiers.
	- Medium: 8th-note density cap, max 2-note chords, orange→purple remap.
	- Easy: quarter-note density cap, single-note chords, fret >= 3 remap to yellow.
- Avoid introducing GUI/stateful config flows (no Tkinter, no `CH_Settings.txt` in v0).
- Prefer small, test-backed changes; add or update tests when behavior changes.

## Known Agent Pitfalls

- Do not use bare `uv run flake8 ...` on zsh setups that autocorrect command names; use:
	- `uv run python -m flake8 ...`
- Keep zip extraction safe:
	- normalize paths
	- reject traversal entries (`..`)
	- keep wrapped vs flat extraction behavior intact
- Do not reintroduce legacy multi-script assumptions from the original repos.

## Credit Origins

This project ports and consolidates logic from:

- https://github.com/lililwavezlilil/Clone-Hero-Midi-2-Chart
- https://github.com/lililwavezlilil/Clone-Hero-No-Part-Deleter
- https://github.com/lililwavezlilil/Clone-Hero-Difficulty-Creator
