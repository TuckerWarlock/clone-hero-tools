# Clone Hero Tools — Agent Instructions

Three standalone Python scripts for managing a Clone Hero songs library.
Designed to run in sequence: **Midi2Chart → No Part Deleter → Difficulty Creator**

## Project Structure

```
Clone-Hero-Midi-2-Chart/        CloneHeroMidi2Chart.py
Clone-Hero-No-Part-Deleter/     CloneHeroNoPartDeleter.py
Clone-Hero-Difficulty-Creator/  CloneHeroDifficultyCreator.py
```

Each tool is self-contained — no shared modules, no `requirements.txt`.

## Running the Tools

```bash
pip install mido send2trash   # only deps needed across all three
python Clone-Hero-Midi-2-Chart/CloneHeroMidi2Chart.py
python Clone-Hero-No-Part-Deleter/CloneHeroNoPartDeleter.py
python Clone-Hero-Difficulty-Creator/CloneHeroDifficultyCreator.py
```

- No CLI arguments — all tools are interactive (Tkinter GUI for folder selection).
- On first run a folder picker dialog selects the Clone Hero songs directory.
- Path is persisted in `CH_Settings.txt` (plain text, `#`-commented, first non-comment line = path).
- Difficulty Creator shows a Listbox GUI to cherry-pick which songs to process.
- All scripts end with `input("Press Enter to exit...")` — intentional, keeps the terminal open after double-clicking the `.exe`.

## Distribution

All three tools are packaged with **PyInstaller** into a single Windows `.exe`.
Antivirus false positives (Windows Defender) are a known issue — not a bug.

## File Formats

| Format | Role |
|---|---|
| `.mid` / `.midi` | Input to Midi2Chart; also checked by No Part Deleter |
| `notes.chart` | Primary working format (plain text, sections like `[ExpertSingle]`) |
| `CH_Settings.txt` | Shared config file — same format/location across all three tools |
| `song.ini` | Used only as a song-folder marker, not parsed |

The `.chart` format uses `tick = type value [length]` lines inside named sections:
- `N` = note, `S 2` = Star Power, `B` = BPM, `TS` = time signature, `E` = event.

## Key Conventions

- **ANSI color output:** `Colors` class (or raw `\033[…m` codes) — cyan = info, green = success, red = error/deletion, yellow = warning.
- **UTF-8 with BOM tolerance:** All file reads use `utf-8-sig` encoding with `errors='ignore'`.
- **`send2trash` for deletion:** Both Midi2Chart and No Part Deleter use `send2trash` (recoverable Recycle Bin), not `os.remove`. Note: No Part Deleter README incorrectly says "permanent" — the code is safe.
- **No external parser for `.chart`:** Pure `re` regex throughout — no dedicated `.chart` library.
- **HOPO threshold:** Replicates Moonscraper's formula: `(resolution × 170) / 480`.
- **Windows-primary:** `ctypes.windll` for console title on Windows; ANSI escape fallback on Unix.

## Known Issues / Gotchas

- **Midi2Chart** `endswith('.mid')` check does not catch `.midi` — docs claim both are supported but code misses `.midi` in at least one path.
- **Difficulty Creator** has `FORCE_REPLACE = True` hardcoded — always regenerates Hard/Medium/Easy, even if they already exist. The README mentions `.bak` backups but **no backup logic exists in the code**.
- **No Part Deleter** `DRY_RUN = False` is hardcoded — edit source to enable safe preview mode.
- **GHL parts excluded intentionally:** No Part Deleter's regex uses a negative lookahead for ` GHL`, so songs with only Guitar Hero Live 6-fret parts are treated as "no instrument" and deleted.
- **Difficulty Creator only works on `.chart`** — must run Midi2Chart first if source is MIDI.

## Instrument/Track Mapping (Midi2Chart)

| MIDI Track Name | `.chart` Section Key |
|---|---|
| PART GUITAR, T1 GEMS | `Single` |
| PART BASS | `DoubleBass` |
| PART RHYTHM | `DoubleRhythm` |
| PART KEYS | `Keyboard` |
| PART DRUMS | `Drums` |

MIDI note → lane mapping per difficulty (Expert: 96–100, Hard: 84–88, Medium: 72–76, Easy: 60–64). Open notes use 95/83/71/59.
