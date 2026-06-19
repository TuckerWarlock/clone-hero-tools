#!/usr/bin/env python3
"""
ch-chart-fix — Clone Hero chart fixer for macOS/Linux.

Converts an Expert-only song into a fully playable chart with all four
difficulties (Expert / Hard / Medium / Easy).

Usage:
    python ch-chart-fix.py <song_folder_or_zip>
    python ch-chart-fix.py --batch <songs_root_dir>

The input can be:
  - A folder containing notes.chart  → difficulty generation only
  - A folder containing *.mid/midi   → MIDI conversion, then difficulties
  - A .zip file                      → extracted first, then processed

For zip files the extracted folder is written next to the zip.
Two layouts are handled automatically:
  Wrapped: song.zip → Artist - Song/notes.chart   (folder inside zip)
  Flat:    song.zip → notes.chart                 (files at zip root)

Dependencies:
    pip install mido
"""

import argparse
import os
import re
import sys
import zipfile
from collections import defaultdict

# ─────────────────────────────────────────────
# ANSI colours (safe on macOS/Linux terminals)
# ─────────────────────────────────────────────
C_CYAN = "\033[96m"
C_GREEN = "\033[92m"
C_YELLOW = "\033[93m"
C_RED = "\033[91m"
C_MAGENTA = "\033[95m"
C_GRAY = "\033[90m"
C_RESET = "\033[0m"


def info(msg):
    print(f"{C_CYAN}{msg}{C_RESET}")


def ok(msg):
    print(f"{C_GREEN}{msg}{C_RESET}")


def warn(msg):
    print(f"{C_YELLOW}⚠  {msg}{C_RESET}")


def err(msg):
    print(f"{C_RED}✗  {msg}{C_RESET}")


def section(msg):
    print(f"\n{C_MAGENTA}{'─'*50}\n{msg}\n{'─'*50}{C_RESET}")


# ═══════════════════════════════════════════════════════════════════
#  PART 1 — MIDI → .chart  (ported from CloneHeroMidi2Chart.py)
# ═══════════════════════════════════════════════════════════════════


def _get_note_lane(note):
    if 96 <= note <= 100:
        return ("Expert", note - 96)
    if note == 95:
        return ("Expert", 7)
    if 84 <= note <= 88:
        return ("Hard", note - 84)
    if note == 83:
        return ("Hard", 7)
    if 72 <= note <= 76:
        return ("Medium", note - 72)
    if note == 71:
        return ("Medium", 7)
    if 60 <= note <= 64:
        return ("Easy", note - 60)
    if note == 59:
        return ("Easy", 7)
    return (None, None)


def _get_modifier_zone(note):
    if note == 101:
        return ("Expert", "HOPO")
    if note == 102:
        return ("Expert", "STRUM")
    if note == 104:
        return ("Expert", "TAP")
    if note == 89:
        return ("Hard", "HOPO")
    if note == 90:
        return ("Hard", "STRUM")
    if note == 92:
        return ("Hard", "TAP")
    if note == 77:
        return ("Medium", "HOPO")
    if note == 78:
        return ("Medium", "STRUM")
    if note == 80:
        return ("Medium", "TAP")
    if note == 65:
        return ("Easy", "HOPO")
    if note == 66:
        return ("Easy", "STRUM")
    if note == 68:
        return ("Easy", "TAP")
    return (None, None)


def _is_structural_pitch(note):
    return note in {
        116,
        101,
        102,
        103,
        104,
        105,
        106,
        89,
        90,
        91,
        92,
        93,
        94,
        77,
        78,
        79,
        80,
        81,
        82,
        65,
        66,
        67,
        68,
        69,
        70,
    }


def _is_in_zone(note_start, z_start, z_end, fuzz=2):
    if z_start == z_end:
        return abs(note_start - z_start) <= fuzz
    return (z_start - fuzz) <= note_start <= (z_end + fuzz)


def _snap_and_quantize(notes, threshold=6):
    """Correct staggered chord onsets within a 6-tick window."""
    if not notes:
        return []
    notes.sort(key=lambda x: x[0])
    snapped = []
    chord_start = notes[0][0]
    for start, lane, length in notes:
        if abs(start - chord_start) <= threshold:
            snapped.append((chord_start, lane, length))
        else:
            chord_start = start
            snapped.append((chord_start, lane, length))
    return snapped


def _calculate_1to1_toggles(notes_list, resolution, f_strum, f_hopo, f_tap):
    """Convert raw note tuples to .chart line strings with HOPO/strum/tap flags."""
    ticks = defaultdict(list)
    lengths = {}
    for start, lane, length in notes_list:
        ticks[start].append(lane)
        if (start, lane) not in lengths or length > lengths[(start, lane)]:
            lengths[(start, lane)] = length

    sorted_ticks = sorted(ticks.keys())
    final_strings = set()
    prev_tick = -99999
    prev_lanes = []
    # Moonscraper-accurate HOPO threshold
    hopo_threshold = (resolution * 170) / 480.0

    for tick in sorted_ticks:
        current_lanes = ticks[tick]
        is_chord = len(current_lanes) > 1

        if is_chord:
            natural_state = "STRUM"
        elif not prev_lanes:
            natural_state = "STRUM"
        elif len(prev_lanes) == 1 and current_lanes[0] == prev_lanes[0]:
            natural_state = "STRUM"
        elif (tick - prev_tick) <= hopo_threshold:
            natural_state = "HOPO"
        else:
            natural_state = "STRUM"

        is_tap = any(_is_in_zone(tick, z_start, z_end) for z_start, z_end in f_tap)

        target_state = natural_state
        active_zone_start = -1

        if not is_tap:
            for z_start, z_end in f_hopo:
                if _is_in_zone(tick, z_start, z_end) and z_start > active_zone_start:
                    active_zone_start = z_start
                    target_state = "HOPO"
            for z_start, z_end in f_strum:
                if _is_in_zone(tick, z_start, z_end) and z_start > active_zone_start:
                    active_zone_start = z_start
                    target_state = "STRUM"

        for lane in current_lanes:
            length = lengths[(tick, lane)]
            if length <= (resolution / 3.0):
                length = 0
            final_strings.add((tick, f"  {tick} = N {lane} {length}"))
            if is_tap:
                final_strings.add((tick, f"  {tick} = N 6 0"))
            elif target_state != natural_state:
                final_strings.add((tick, f"  {tick} = N 5 0"))

        prev_tick = tick
        prev_lanes = current_lanes

    return final_strings


def convert_midi_to_chart(midi_path, chart_path):
    """
    Convert a .mid file to notes.chart.
    Returns True on success, False on failure.
    """
    try:
        import mido
    except ImportError:
        err("mido is not installed. Run: pip install mido")
        return False

    try:
        mid = mido.MidiFile(midi_path, clip=True, charset="utf-8")
    except Exception as exc:
        err(f"Failed to read MIDI: {exc}")
        return False

    resolution = mid.ticks_per_beat
    sync_track = []
    events = []
    global_notes = {}

    for idx, track in enumerate(mid.tracks):
        track_name = ""
        for msg in track:
            if msg.type == "track_name":
                track_name = str(msg.name).upper().strip()
                break
        if not track_name:
            track_name = f"TRACK_{idx}"

        # Skip non-instrument tracks
        if any(kw in track_name for kw in ("ANIM", "REAL", "VOCAL", "HARM")):
            continue

        # Map track name → instrument key
        instrument = None
        if "BASS" in track_name or "T2 GEMS" in track_name:
            instrument = "DoubleBass"
        elif "DRUM" in track_name or "T4 GEMS" in track_name:
            instrument = "Drums"
        elif "KEY" in track_name or "T5 GEMS" in track_name:
            instrument = "Keyboard"
        elif "RHYTHM" in track_name or "T3 GEMS" in track_name:
            instrument = "DoubleRhythm"
        elif "GUITAR" in track_name or "T1 GEMS" in track_name:
            instrument = "Single"

        raw_pitches = set()
        abs_time = 0
        for msg in track:
            abs_time += msg.time
            if msg.type == "time_signature":
                sync_track.append((abs_time, f"  {abs_time} = TS {msg.numerator}"))
            elif msg.type == "set_tempo":
                chart_bpm = int((60_000_000 / msg.tempo) * 1000)
                sync_track.append((abs_time, f"  {abs_time} = B {chart_bpm}"))
            elif msg.type in ("lyrics", "text"):
                text = str(msg.text).strip()
                if text:
                    events.append((abs_time, f'  {abs_time} = E "{text}"'))
            elif msg.type == "note_on" and msg.velocity > 0:
                raw_pitches.add(msg.note)

        # Fallback: assign un-named tracks by index
        if not instrument and track_name.startswith("TRACK_") and raw_pitches:
            instrument = {
                1: "Single",
                2: "DoubleBass",
                3: "DoubleRhythm",
                4: "Drums",
            }.get(idx, f"Unknown_{idx}")

        if not instrument:
            continue

        track_notes = {d: [] for d in ("Expert", "Hard", "Medium", "Easy")}
        f_strum = {d: [] for d in ("Expert", "Hard", "Medium", "Easy")}
        f_hopo = {d: [] for d in ("Expert", "Hard", "Medium", "Easy")}
        f_tap = {d: [] for d in ("Expert", "Hard", "Medium", "Easy")}
        sp_zones = []
        active = {}

        abs_time = 0
        for msg in track:
            abs_time += msg.time
            if msg.type == "note_on" and msg.velocity > 0:
                active[msg.note] = abs_time
            elif msg.type == "note_off" or (
                msg.type == "note_on" and msg.velocity == 0
            ):
                if msg.note not in active:
                    continue
                start = active.pop(msg.note)
                length = abs_time - start

                if msg.note == 116:
                    sp_zones.append((start, start + length))
                    continue

                diff, lane = _get_note_lane(msg.note)
                if diff:
                    track_notes[diff].append((start, lane, length))
                    continue

                mod_diff, mod_type = _get_modifier_zone(msg.note)
                if mod_diff:
                    target = {"STRUM": f_strum, "HOPO": f_hopo, "TAP": f_tap}[mod_type]
                    target[mod_diff].append((start, start + length))

        # Rescue mode: if no notes mapped, assign by sorted pitch index → Expert
        total = sum(len(v) for v in track_notes.values())
        if total == 0 and raw_pitches:
            sorted_p = sorted(p for p in raw_pitches if not _is_structural_pitch(p))
            if sorted_p:
                active2 = {}
                abs_time = 0
                for msg in track:
                    abs_time += msg.time
                    if msg.type == "note_on" and msg.velocity > 0:
                        active2[msg.note] = abs_time
                    elif msg.type == "note_off" or (
                        msg.type == "note_on" and msg.velocity == 0
                    ):
                        if msg.note not in active2:
                            continue
                        start = active2.pop(msg.note)
                        length = abs_time - start
                        if not _is_structural_pitch(msg.note):
                            try:
                                lane = min(sorted_p.index(msg.note), 4)
                                track_notes["Expert"].append((start, lane, length))
                            except ValueError:
                                pass

        for diff, notes in track_notes.items():
            if not notes:
                continue
            section_key = f"{diff}{instrument}"
            if section_key not in global_notes:
                global_notes[section_key] = set()

            snapped = _snap_and_quantize(notes)
            strings = _calculate_1to1_toggles(
                snapped, resolution, f_strum[diff], f_hopo[diff], f_tap[diff]
            )
            global_notes[section_key].update(strings)

            for z_start, z_end in sp_zones:
                global_notes[section_key].add(
                    (z_start, f"  {z_start} = S 2 {z_end - z_start}")
                )

        extracted = sum(len(v) for v in track_notes.values())
        if extracted:
            print(
                f"    {C_GRAY}→ {extracted} notes extracted for [{instrument}]{C_RESET}"
            )

    if not any(global_notes.values()):
        err("No valid notes found in MIDI. Is this a guitar/bass/keys track?")
        return False

    # De-dup and sort sync + events
    unique_sync = sorted(
        {line: tick for tick, line in sync_track}.items(),
        key=lambda kv: (
            int(re.search(r"^\s*(\d+)", kv[0]).group(1)),
            0 if "TS" in kv[0] else 1,
        ),
    )
    unique_events = sorted(
        {line: tick for tick, line in events}.items(),
        key=lambda kv: int(re.search(r"^\s*(\d+)", kv[0]).group(1)),
    )

    with open(chart_path, "w", encoding="utf-8") as f:
        f.write(f"[Song]\n{{\n  Resolution = {resolution}\n}}\n")

        f.write("[SyncTrack]\n{\n")
        if not unique_sync:
            f.write("  0 = TS 4\n  0 = B 120000\n")
        else:
            for line, _ in unique_sync:
                f.write(line + "\n")
        f.write("}\n")

        f.write("[Events]\n{\n")
        for line, _ in unique_events:
            f.write(line + "\n")
        f.write("}\n")

        for sec_key, note_set in global_notes.items():
            sorted_notes = sorted(note_set, key=lambda x: (x[0], x[1]))
            if sorted_notes:
                f.write(f"[{sec_key}]\n{{\n")
                for _, line in sorted_notes:
                    f.write(line + "\n")
                f.write("}\n")

    return True


# ═══════════════════════════════════════════════════════════════════
#  PART 2 — Difficulty downcharting  (ported from CloneHeroDifficultyCreator.py)
# ═══════════════════════════════════════════════════════════════════


def _downchart_notes(notes_data: str, difficulty: str, resolution: int) -> str:
    """
    Generate a Hard / Medium / Easy section from Expert note data.

    Rules:
      Hard   – keeps force flags (N 5/6); no speed thinning; no chord limits
      Medium – strips force flags; max 8th-note density; max 2-note chords;
               orange (fret 4) → purple (fret 3)
      Easy   – strips force flags; max quarter-note density; single notes only;
               fret ≥ 3 (except open/7) → yellow (fret 2)
    """
    lines = notes_data.split("\n")
    new_lines = []
    last_tick = -99999
    accepted_ticks = {}  # tick → [colors already accepted]

    for line in lines:
        stripped = line.strip("\r")  # strip CR only; preserve leading spaces
        m = re.match(r"^\s*(\d+)\s*=\s*N\s+(\d+)\s+(\d+)", stripped)

        if not m:
            # Pass through Star Power, Events, braces, etc.
            if stripped.strip():
                new_lines.append(stripped)
            continue

        tick = int(m.group(1))
        color = int(m.group(2))
        length = int(m.group(3))

        # Force HOPO (5) / Force Strum (6) modifiers
        if color in (5, 6):
            if difficulty == "Hard":
                new_lines.append(f"  {tick} = N {color} {length}")
            # Medium and Easy drop force modifiers entirely
            continue

        # Normal frets (0-4) and open note (7)
        if not (color <= 4 or color == 7):
            # Odd note type — pass through untouched
            new_lines.append(f"  {tick} = N {color} {length}")
            continue

        # ── Color down-mapping ──────────────────────────────────────
        if difficulty == "Medium" and color == 4:
            color = 3
        if difficulty == "Easy" and color >= 3 and color != 7:
            color = 2

        # ── Speed thinning ──────────────────────────────────────────
        if tick not in accepted_ticks:
            gap = tick - last_tick
            too_fast = (difficulty == "Easy" and gap < resolution) or (
                difficulty == "Medium" and gap < resolution / 2
            )
            if too_fast:
                continue
            accepted_ticks[tick] = []
            last_tick = tick

        if tick not in accepted_ticks:
            continue  # was dropped above

        # ── Chord limits ────────────────────────────────────────────
        if color in accepted_ticks[tick]:
            continue  # duplicate fret at same tick
        if difficulty == "Easy" and len(accepted_ticks[tick]) >= 1:
            continue  # singles only
        if difficulty == "Medium" and len(accepted_ticks[tick]) >= 2:
            continue  # max 2-note chords

        accepted_ticks[tick].append(color)
        new_lines.append(f"  {tick} = N {color} {length}")

    return "\n".join(new_lines)


def add_difficulties(chart_path: str, force_replace: bool = True) -> bool:
    """
    Read an existing notes.chart, generate Hard/Medium/Easy from each Expert
    block, and write the result back to the same file.

    Returns True if at least one difficulty block was added.
    """
    with open(chart_path, encoding="utf-8-sig", errors="ignore") as f:
        content = f.read()

    if not re.search(r"\[Expert[A-Za-z]*\]", content):
        warn("No Expert sections found in chart — nothing to downchart.")
        return False

    # Parse resolution (default 192)
    res_m = re.search(r"(?m)^\s*Resolution\s*=\s*(\d+)", content)
    resolution = int(res_m.group(1)) if res_m else 192

    # Optionally wipe existing lower-difficulty blocks so we start clean
    if force_replace:
        content = re.sub(
            r"(?m)^\[(Hard|Medium|Easy)[A-Za-z]+\]\r?\n\{\r?\n[\s\S]*?\r?\n\}\r?\n?",
            "",
            content,
        )

    expert_blocks = list(
        re.finditer(r"(?m)^\[Expert([A-Za-z]+)\]\r?\n\{\r?\n([\s\S]*?)\r?\n\}", content)
    )

    if not expert_blocks:
        warn("Expert section header found but could not parse its body.")
        return False

    new_blocks = ""
    for m in expert_blocks:
        instrument = m.group(1)
        notes_data = m.group(2)
        for diff in ("Hard", "Medium", "Easy"):
            downcharted = _downchart_notes(notes_data, diff, resolution)
            new_blocks += f"\n[{diff}{instrument}]\n{{\n{downcharted}\n}}"

    final = content.rstrip() + "\n" + new_blocks + "\n"
    with open(chart_path, "w", encoding="utf-8") as f:
        f.write(final)

    return True


# ═══════════════════════════════════════════════════════════════════
#  PART 3 — Song folder processing pipeline
# ═══════════════════════════════════════════════════════════════════


def _find_midi(folder: str):
    """Return the first .mid or .midi file found in folder, or None."""
    for name in os.listdir(folder):
        if name.lower().endswith((".mid", ".midi")):
            return os.path.join(folder, name)
    return None


def _find_chart(folder: str):
    """Return notes.chart path if it exists in folder, or None."""
    candidate = os.path.join(folder, "notes.chart")
    return candidate if os.path.isfile(candidate) else None


def _is_song_folder(folder: str) -> bool:
    """A folder qualifies as a song folder if it contains song.ini or notes.chart or a MIDI."""
    files_lower = {f.lower() for f in os.listdir(folder)}
    return bool(
        files_lower & {"song.ini", "notes.chart"}
        or any(f.endswith((".mid", ".midi")) for f in files_lower)
    )


def process_song_folder(folder: str, dry_run: bool = False) -> bool:
    """
    Full pipeline for a single song folder:
      1. If MIDI present and no notes.chart → convert MIDI → notes.chart
      2. If notes.chart present → add Hard/Medium/Easy from Expert

    Returns True if the chart ended up with all difficulties.
    """
    folder = os.path.realpath(folder)
    if not os.path.isdir(folder):
        err(f"Not a directory: {folder}")
        return False

    chart_path = _find_chart(folder)
    midi_path = _find_midi(folder)
    song_name = os.path.basename(folder)

    info(f"Processing: {song_name}")

    # Step 1 — MIDI conversion if needed
    if not chart_path:
        if not midi_path:
            err("No notes.chart or MIDI file found in this folder.")
            return False
        info("  Converting MIDI → notes.chart …")
        if dry_run:
            ok("  [DRY RUN] Would convert MIDI.")
            return True
        chart_path = os.path.join(folder, "notes.chart")
        success = convert_midi_to_chart(midi_path, chart_path)
        if not success:
            err("  MIDI conversion failed.")
            return False
        ok(f"  ✓ notes.chart created from {os.path.basename(midi_path)}")
    else:
        info("  Found existing notes.chart — skipping MIDI conversion.")

    # Step 2 — Check if Expert section actually exists
    with open(chart_path, encoding="utf-8-sig", errors="ignore") as f:
        content = f.read()

    has_expert = bool(re.search(r"\[Expert[A-Za-z]*\]", content))
    has_lower = bool(re.search(r"\[(Hard|Medium|Easy)[A-Za-z]*\]", content))

    if not has_expert:
        warn("  Chart has no Expert section. Cannot generate lower difficulties.")
        return False

    if has_lower:
        info("  Hard/Medium/Easy already exist — regenerating from Expert …")
    else:
        info("  Generating Hard / Medium / Easy from Expert …")

    if dry_run:
        ok("  [DRY RUN] Would write lower difficulties.")
        return True

    success = add_difficulties(chart_path, force_replace=True)
    if success:
        ok("  ✓ All difficulties written to notes.chart")
    else:
        err("  Failed to generate lower difficulties.")

    return success


# ═══════════════════════════════════════════════════════════════════
#  PART 4 — ZIP extraction
# ═══════════════════════════════════════════════════════════════════

_SONG_MARKERS = {"notes.chart", "notes.mid", "notes.midi", "song.ini"}


def extract_zip(zip_path: str, dry_run: bool = False) -> str | None:
    """
    Extract a Clone Hero chart zip and return the path to the song folder.

    Handles two common layouts:
      Wrapped — the zip contains a single top-level folder:
                  Artist - Song/notes.chart  →  extracted as-is
      Flat    — chart files sit at the zip root:
                  notes.chart               →  placed in a folder named
                                               after the zip (minus .zip)

    The song folder is always extracted next to the zip file.
    Returns the path to the song folder, or None on failure.
    """
    zip_path = os.path.realpath(zip_path)
    if not zipfile.is_zipfile(zip_path):
        err(f"Not a valid zip file: {zip_path}")
        return None

    dest_dir = os.path.dirname(zip_path)
    zip_stem = os.path.splitext(os.path.basename(zip_path))[0]

    with zipfile.ZipFile(zip_path, "r") as zf:
        # Sanitise member names — strip absolute paths and any '..' traversal
        names = []
        for name in zf.namelist():
            safe = os.path.normpath(name.lstrip("/"))
            if safe.startswith(".."):
                warn(f"  Skipping unsafe zip entry: {name}")
                continue
            names.append((name, safe))

        # Detect layout: is there a single top-level folder wrapping everything?
        roots = {n.split("/")[0] for _, n in names}
        is_wrapped = len(roots) == 1 and list(roots)[0] not in {
            n for _, n in names if "/" not in n
        }

        if is_wrapped:
            # Wrapped layout — extract directly into dest_dir
            song_folder = os.path.join(dest_dir, list(roots)[0])
            info(f"  Wrapped zip — extracting to: {os.path.basename(song_folder)}/")
        else:
            # Flat layout — create a folder named after the zip stem
            song_folder = os.path.join(dest_dir, zip_stem)
            info(f"  Flat zip — extracting to: {zip_stem}/")

        if dry_run:
            ok(f"  [DRY RUN] Would extract {len(names)} entries to {song_folder}")
            return song_folder

        os.makedirs(song_folder, exist_ok=True)

        for orig_name, safe_name in names:
            if is_wrapped:
                # Strip the top-level folder prefix so files land in song_folder
                parts = safe_name.split(os.sep, 1)
                rel = parts[1] if len(parts) > 1 else ""
            else:
                rel = safe_name

            if not rel:  # was a directory entry
                continue

            out_path = os.path.join(song_folder, rel)
            os.makedirs(os.path.dirname(out_path), exist_ok=True)

            with zf.open(orig_name) as src, open(out_path, "wb") as dst:
                dst.write(src.read())

    ok(f"  ✓ Extracted to: {song_folder}")
    return song_folder


def batch_process(root_dir: str, dry_run: bool = False):
    """Walk root_dir and process every song folder found."""
    root_dir = os.path.realpath(root_dir)
    if not os.path.isdir(root_dir):
        err(f"Directory not found: {root_dir}")
        sys.exit(1)

    section(f"Batch processing: {root_dir}")

    processed = 0
    skipped = 0
    failed = 0

    for dirpath, dirnames, filenames in os.walk(root_dir):
        if not _is_song_folder(dirpath):
            continue
        # Don't descend into subdirectories of a song folder
        dirnames[:] = []

        print()
        result = process_song_folder(dirpath, dry_run=dry_run)
        if result:
            processed += 1
        else:
            failed += 1

    section(f"Done — {processed} processed, {failed} failed, {skipped} skipped")


# ═══════════════════════════════════════════════════════════════════
#  CLI entry point
# ═══════════════════════════════════════════════════════════════════


def main():
    parser = argparse.ArgumentParser(
        prog="ch-chart-fix",
        description="Convert Expert-only Clone Hero charts to full 4-difficulty charts.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Single song folder (has notes.chart or a .mid inside)
  python ch-chart-fix.py ~/Downloads/some-song/

  # Zip file — extracted next to the zip, then processed
  python ch-chart-fix.py ~/Downloads/some-song.zip

  # Batch — process every song under a root directory
  python ch-chart-fix.py --batch ~/Music/CloneHero/songs/

  # Dry run — show what would happen without writing any files
  python ch-chart-fix.py --dry-run ~/Downloads/some-song.zip
  python ch-chart-fix.py --batch --dry-run ~/Music/CloneHero/songs/
""",
    )
    parser.add_argument(
        "path", help="Song folder path, or root directory when --batch is set"
    )
    parser.add_argument(
        "--batch", action="store_true", help="Process all song folders under <path>"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without writing files",
    )

    args = parser.parse_args()

    if args.dry_run:
        warn("DRY RUN — no files will be written.\n")

    path = args.path

    # Transparently handle .zip input
    if path.lower().endswith(".zip"):
        if args.batch:
            err("--batch cannot be used with a .zip file.")
            sys.exit(1)
        section(f"ZIP input: {path}")
        info("Extracting zip …")
        path = extract_zip(path, dry_run=args.dry_run)
        if path is None:
            sys.exit(1)

    if args.batch:
        batch_process(path, dry_run=args.dry_run)
    else:
        section(f"Single folder: {path}")
        ok_result = process_song_folder(path, dry_run=args.dry_run)
        sys.exit(0 if ok_result else 1)


if __name__ == "__main__":
    main()
