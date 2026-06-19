# Clone Hero Chart Fix

A single Python CLI tool that takes an Expert-only Clone Hero chart and
generates the missing **Hard**, **Medium**, and **Easy** difficulties from it.

Supports `.chart`, `.mid`/`.midi`, and `.zip` source inputs. Runs on **macOS / Linux /
Windows** — no pre-compiled executable required.

## Credits & Origins

This project is based on the work by
[lililwavezlilil](https://github.com/lililwavezlilil).

Original repositories:

- [Clone-Hero-Midi-2-Chart](https://github.com/lililwavezlilil/Clone-Hero-Midi-2-Chart)
- [Clone-Hero-No-Part-Deleter](https://github.com/lililwavezlilil/Clone-Hero-No-Part-Deleter)
- [Clone-Hero-Difficulty-Creator](https://github.com/lililwavezlilil/Clone-Hero-Difficulty-Creator)

---

## How it works

Most community-charted songs only ship an Expert track. This tool:

1. **Extracts zip files** (when you pass a `.zip` path)
2. **Converts MIDI → `.chart`** (if the folder contains a `.mid`/`.midi` file
  and no `notes.chart` yet)
3. **Downcharts Expert** into Hard / Medium / Easy using the same algorithm as
   Moonscraper's native difficulty generator:

| Difficulty | Speed limit | Chord limit | Fret remapping |
|------------|-------------|-------------|----------------|
| Hard       | none        | none        | none           |
| Medium     | 8th notes   | 2-note max  | orange (4) → purple (3) |
| Easy       | Quarter notes | single notes | fret ≥ 3 → yellow (2) |

---

## Requirements

- Python ≥ 3.14
- [uv](https://docs.astral.sh/uv/getting-started/installation/) (recommended)

---

## Installation

```bash
git clone <this-repo>
cd clone-hero-tools

# Create the virtual environment and install dependencies
uv venv --python 3.14
uv sync
```

---

## Usage

### Single song folder

```bash
uv run ch-chart-fix.py path/to/song-folder/
```

The folder should contain either a `notes.chart` or a `.mid` file.

### Zip file input

```bash
uv run ch-chart-fix.py ~/Downloads/song.zip
```

Zip extraction is automatic, then the normal conversion/downchart pipeline runs.

Supported zip layouts:
- Wrapped layout: `song.zip` contains `Artist - Song/notes.chart`
- Flat layout: `song.zip` contains `notes.chart` at zip root

For flat zips, a folder named after the zip file is created next to the zip.

### Batch — process an entire songs directory

```bash
uv run ch-chart-fix.py --batch ~/Music/CloneHero/songs/
```

Every sub-folder that looks like a song folder (contains `song.ini`,
`notes.chart`, or a `.mid`) will be processed.

### Dry run — preview without writing

```bash
uv run ch-chart-fix.py --dry-run path/to/song-folder/
uv run ch-chart-fix.py --batch --dry-run ~/Music/CloneHero/songs/
```

### All options

```
usage: ch-chart-fix [-h] [--batch] [--dry-run] path

positional arguments:
  path        Song folder, or root directory when --batch is set

options:
  --batch     Process all song folders found under <path>
  --dry-run   Show what would be done without writing any files
  -h, --help  Show this help message and exit
```

---

## File format notes

The `.chart` format is plain text with named sections:

```
[ExpertSingle]
{
  0 = N 0 0       ← tick = N fret length
  192 = N 1 0
  0 = S 2 768     ← Star Power
}
```

MIDI track names are mapped to `.chart` instrument keys:

| MIDI track name            | `.chart` section key |
|----------------------------|----------------------|
| PART GUITAR, T1 GEMS       | `Single`             |
| PART BASS                  | `DoubleBass`         |
| PART RHYTHM                | `DoubleRhythm`       |
| PART KEYS                  | `Keyboard`           |
| PART DRUMS                 | `Drums`              |

---

## Development

### Run the local CI pipeline

```bash
./local_ci.sh           # format check → lint → tests
./local_ci.sh --fix     # auto-fix formatting, then lint → tests
```

The pipeline runs:

| Step   | Tool    | What it checks |
|--------|---------|----------------|
| Format | Black   | Consistent code style (88-char lines) |
| Lint   | Ruff    | pyflakes, pycodestyle, isort, pyupgrade |
| Lint   | Flake8  | Belt-and-suspenders pass for anything Ruff misses |
| Tests  | Pytest  | 26 unit + smoke tests |

### Install dev dependencies

```bash
uv sync --group dev
```

### Run tests directly

```bash
uv run pytest -v
```

---

## Project structure

```
ch-chart-fix.py       Main script (MIDI conversion + difficulty generation)
tests/
  test_ch_chart_fix.py  Unit tests (downcharting logic, pipeline)
  test_cli_smoke.py     Smoke tests (CLI subprocess)
local_ci.sh           Local CI script
pyproject.toml        Project metadata, tool config (Black, Ruff, Pytest)
.flake8               Flake8 config
.python-version       Pins Python 3.14 for uv / pyenv
```

