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
import hashlib
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

        # ── Grid snapping ────────────────────────────────────────────
        # Snap each note to the nearest 8th-note (Medium) or quarter-note (Easy)
        # grid so generated notes always land on musical beat positions that
        # match the audio, even when the Expert chart contains syncopated or
        # 16th-note-offset notes.
        if difficulty == "Medium":
            step = resolution // 2
            tick = round(tick / step) * step
        elif difficulty == "Easy":
            step = resolution
            tick = round(tick / step) * step

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

    # Medium/Easy can generate lane-collisions after fret remaps (e.g. 4 -> 3)
    # where a sustain overlaps the next note on the same lane. Trim those tails
    # so the chart remains playable.
    if difficulty in {"Medium", "Easy"}:
        lane_events = {}
        for idx, line in enumerate(new_lines):
            m = re.match(r"^\s*(\d+)\s*=\s*N\s+(\d+)\s+(\d+)", line)
            if not m:
                continue
            tick = int(m.group(1))
            lane = int(m.group(2))
            length = int(m.group(3))
            # Only trim playable lanes/open notes; modifiers are already stripped.
            if lane <= 4 or lane == 7:
                lane_events.setdefault(lane, []).append([idx, tick, length])

        for lane, events in lane_events.items():
            events.sort(key=lambda e: e[1])
            for i in range(len(events) - 1):
                idx, tick, length = events[i]
                next_tick = events[i + 1][1]
                max_len = max(0, next_tick - tick)
                if length > max_len:
                    events[i][2] = max_len
                    new_lines[idx] = f"  {tick} = N {lane} {max_len}"

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
#  PART 3A — Duplicate detection & community-chart preference
# ═══════════════════════════════════════════════════════════════════


_AUDIO_EXTENSIONS = {".mp3", ".ogg", ".opus", ".wav", ".flac", ".m4a"}
_SONG_INI_PREFERENCE_KEYS = {
    "album",
    "charter",
    "genre",
    "icon",
    "playlist_track",
    "preview_start_time",
    "tags",
    "unlock_id",
    "year",
}
_BADSONGS_DUPLICATE_HEADER = (
    "ERROR: These folders contain charts that another song has (duplicate charts)!"
)
_CHART_INSTRUMENT_SECTION_MARKERS = (
    "[Single]",
    "[DoubleGuitar]",
    "[DoubleBass]",
    "[DoubleRhythm]",
    "[Keyboard]",
)
_MIDI_REQUIRED_TRACK_PATTERNS = (
    re.compile(r"\bPART GUITAR\b"),
    re.compile(r"\bPART BASS\b"),
    re.compile(r"\bPART RHYTHM\b"),
    re.compile(r"\bPART KEYS\b"),
    re.compile(r"\bT1 GEMS\b"),
)


def _count_notes_in_chart(chart_path: str) -> int:
    """Count total playable notes in a chart file (all difficulties)."""
    try:
        with open(chart_path, encoding="utf-8-sig", errors="ignore") as f:
            content = f.read()
        # Count all N (note) lines
        return len(re.findall(r"^\s*\d+\s*=\s*N\s+\d+\s+\d+", content, re.MULTILINE))
    except Exception:
        return 0


def _hash_file(path: str) -> str | None:
    """Return the SHA-1 hash for a file, or None if unreadable."""
    try:
        digest = hashlib.sha1()
        with open(path, "rb") as f:
            while True:
                chunk = f.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None


def _count_notes_in_midi(midi_path: str) -> int:
    """Count note-on events in a MIDI file as a simple complexity proxy."""
    try:
        import mido

        mid = mido.MidiFile(midi_path, clip=True, charset="utf-8")
    except Exception:
        return 0

    note_count = 0
    for track in mid.tracks:
        for msg in track:
            if (
                getattr(msg, "type", None) == "note_on"
                and getattr(msg, "velocity", 0) > 0
            ):
                note_count += 1
    return note_count


def _count_chart_complexity(chart_path: str) -> int:
    """Count chart complexity for either .chart or MIDI chart sources."""
    lower = chart_path.lower()
    if lower.endswith(".chart"):
        return _count_notes_in_chart(chart_path)
    if lower.endswith((".mid", ".midi")):
        return _count_notes_in_midi(chart_path)
    return 0


def _find_primary_chart_source(folder: str) -> str | None:
    """Return the main chart source for a song folder."""
    chart_path = _find_chart(folder)
    if chart_path:
        return chart_path
    return _find_midi(folder)


def _song_ini_metadata_score(folder: str) -> int:
    """Score song.ini richness using a small set of high-signal keys."""
    ini_path = os.path.join(folder, "song.ini")
    if not os.path.isfile(ini_path):
        return 0

    score = 0
    try:
        with open(ini_path, encoding="utf-8-sig", errors="ignore") as f:
            for raw_line in f:
                line = raw_line.strip()
                if not line or line.startswith("[") or "=" not in line:
                    continue
                key, value = [part.strip().lower() for part in line.split("=", 1)]
                if key in _SONG_INI_PREFERENCE_KEYS and value:
                    score += 1
    except OSError:
        return 0
    return score


def _song_identity(folder: str) -> str | None:
    """Return a normalized song identity from song.ini when available."""
    ini_path = os.path.join(folder, "song.ini")
    if not os.path.isfile(ini_path):
        return None

    artist = None
    name = None
    try:
        with open(ini_path, encoding="utf-8-sig", errors="ignore") as f:
            for raw_line in f:
                line = raw_line.strip()
                if not line or line.startswith("[") or "=" not in line:
                    continue
                key, value = [part.strip() for part in line.split("=", 1)]
                key = key.lower()
                if key == "artist" and value:
                    artist = value.lower()
                elif key == "name" and value:
                    name = value.lower()
    except OSError:
        return None

    if artist and name:
        return f"{artist} - {name}"
    if name:
        return name
    return None


def _normalized_duplicate_name(name: str) -> str:
    """Normalize folder names while stripping trailing qualifier tags."""
    normalized = re.sub(r"\s+", " ", name.strip().lower())
    while True:
        stripped = re.sub(r"\s+\([^()]+\)$", "", normalized).strip()
        if stripped == normalized:
            return normalized
        normalized = stripped


def _duplicate_group_key(folder: str) -> str:
    """Return the key used to group likely duplicate song folders."""
    identity = _song_identity(folder)
    if identity:
        return re.sub(r"\s+", " ", identity).strip()
    return _normalized_duplicate_name(os.path.basename(folder))


def _song_asset_score(folder: str) -> tuple[int, int, int, int, int]:
    """Return a tuple that prefers more complete song packages."""
    preview_count = 0
    album_count = 0
    audio_stems = set()
    audio_bytes = 0

    try:
        names = os.listdir(folder)
    except OSError:
        return (0, 0, 0, 0, 0)

    for name in names:
        path = os.path.join(folder, name)
        if not os.path.isfile(path):
            continue

        lower = name.lower()
        stem, ext = os.path.splitext(lower)

        if stem == "preview" and ext in _AUDIO_EXTENSIONS:
            preview_count += 1
        if stem == "album" and ext in {".png", ".jpg", ".jpeg", ".webp"}:
            album_count += 1
        if ext in _AUDIO_EXTENSIONS:
            audio_stems.add(stem)
            try:
                audio_bytes += os.path.getsize(path)
            except OSError:
                pass

    metadata_score = _song_ini_metadata_score(folder)
    return (preview_count, len(audio_stems), metadata_score, album_count, audio_bytes)


def compare_duplicate_song_folders(folder_a: str, folder_b: str) -> dict[str, object]:
    """
    Compare two duplicate song folders and decide which one to keep.

    Resolution order:
      1. If chart hashes match, prefer the more complete asset package.
      2. Otherwise prefer the chart with higher complexity.
      3. If complexity ties, prefer the more complete asset package.
      4. If still tied, require manual review.
    """
    folder_a = os.path.realpath(folder_a)
    folder_b = os.path.realpath(folder_b)

    chart_a = _find_primary_chart_source(folder_a)
    chart_b = _find_primary_chart_source(folder_b)

    result = {
        "preferred": None,
        "other": None,
        "reason": "manual-review",
        "identical_chart": False,
    }

    if not chart_a or not chart_b:
        return result

    hash_a = _hash_file(chart_a)
    hash_b = _hash_file(chart_b)
    assets_a = _song_asset_score(folder_a)
    assets_b = _song_asset_score(folder_b)

    if hash_a and hash_b and hash_a == hash_b:
        result["identical_chart"] = True
        if assets_a > assets_b:
            result["preferred"] = folder_a
            result["other"] = folder_b
            result["reason"] = "identical-chart-better-assets"
        elif assets_b > assets_a:
            result["preferred"] = folder_b
            result["other"] = folder_a
            result["reason"] = "identical-chart-better-assets"
        return result

    complexity_a = _count_chart_complexity(chart_a)
    complexity_b = _count_chart_complexity(chart_b)
    if complexity_a > complexity_b:
        result["preferred"] = folder_a
        result["other"] = folder_b
        result["reason"] = "higher-chart-complexity"
        return result
    if complexity_b > complexity_a:
        result["preferred"] = folder_b
        result["other"] = folder_a
        result["reason"] = "higher-chart-complexity"
        return result

    if assets_a > assets_b:
        result["preferred"] = folder_a
        result["other"] = folder_b
        result["reason"] = "better-assets"
    elif assets_b > assets_a:
        result["preferred"] = folder_b
        result["other"] = folder_a
        result["reason"] = "better-assets"
    return result


def _normalize_input_path(path: str) -> str:
    """Normalize a user-supplied path without inventing a realpath for missing files."""
    normalized = os.path.expanduser(path.strip().strip('"'))
    if os.path.exists(normalized):
        return os.path.realpath(normalized)
    return normalized


def parse_badsongs_duplicate_pairs(badsongs_path: str) -> list[tuple[str, str]]:
    """Parse duplicate folder pairs from Clone Hero's badsongs.txt output."""
    pairs = []
    in_duplicate_section = False

    with open(badsongs_path, encoding="utf-8-sig", errors="ignore") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line:
                continue
            if line == _BADSONGS_DUPLICATE_HEADER:
                in_duplicate_section = True
                continue
            if not in_duplicate_section:
                continue
            if line.startswith(("ERROR:", "Warning:")):
                break

            match = re.match(
                r"^(?P<left>.+) \((?P<right>(?:[A-Za-z]:\\|/|~).+)\)$", line
            )
            if not match:
                continue
            left = _normalize_input_path(match.group("left"))
            right = _normalize_input_path(match.group("right"))
            pairs.append((left, right))

    return pairs


def find_duplicate_song_groups(root_dir: str) -> list[list[str]]:
    """Find duplicate song folders, assuming duplicates live in the same directory."""
    groups = defaultdict(list)
    root_dir = os.path.realpath(root_dir)

    for dirpath, dirnames, _filenames in os.walk(root_dir):
        if not _is_song_folder(dirpath):
            continue
        dirnames[:] = []
        folder = os.path.realpath(dirpath)
        parent = os.path.realpath(os.path.dirname(folder))
        groups[(parent, _duplicate_group_key(folder))].append(folder)

    return [sorted(group) for group in groups.values() if len(group) > 1]


def evaluate_duplicate_pairs(
    folder_pairs: list[tuple[str, str]],
) -> tuple[dict[str, str], int]:
    """Compare duplicate pairs and return loser->winner skip mapping plus unresolved count."""
    skip_map = {}
    unresolved = 0
    seen = set()

    for folder_a, folder_b in folder_pairs:
        pair_key = tuple(sorted((folder_a, folder_b)))
        if pair_key in seen:
            continue
        seen.add(pair_key)

        if not (os.path.isdir(folder_a) and os.path.isdir(folder_b)):
            warn(
                "  Duplicate pair references a missing folder; skipping comparison: "
                f"{folder_a} | {folder_b}"
            )
            unresolved += 1
            continue

        result = compare_duplicate_song_folders(folder_a, folder_b)
        if result["preferred"] and result["other"]:
            keep_path = os.path.realpath(result["preferred"])
            remove_path = os.path.realpath(result["other"])
            skip_map[remove_path] = keep_path
            ok(
                f"  Keep {os.path.basename(keep_path)}; skip {os.path.basename(remove_path)} "
                f"({result['reason']})"
            )
        else:
            unresolved += 1
            warn(
                "  Manual review required: "
                f"{os.path.basename(folder_a)} | {os.path.basename(folder_b)}"
            )

    return skip_map, unresolved


def scan_duplicate_song_folders(
    root_dir: str, badsongs_path: str | None = None
) -> tuple[dict[str, str], int]:
    """Scan duplicate song folders before any chart processing begins."""
    skip_map = {}
    unresolved = 0

    section("Duplicate scan")

    groups = find_duplicate_song_groups(root_dir)
    if groups:
        info(f"Scanning {len(groups)} same-directory duplicate group(s) …")
        pair_groups = []
        for group in groups:
            if len(group) == 2:
                pair_groups.append((group[0], group[1]))
            else:
                unresolved += 1
                warn(
                    "  Manual review required for multi-folder duplicate group: "
                    + ", ".join(os.path.basename(path) for path in group)
                )
        local_skip_map, local_unresolved = evaluate_duplicate_pairs(pair_groups)
        skip_map.update(local_skip_map)
        unresolved += local_unresolved
    else:
        info("No same-directory duplicate groups found.")

    if badsongs_path:
        info(f"Scanning badsongs duplicate pairs from {badsongs_path} …")
        badsongs_pairs = parse_badsongs_duplicate_pairs(badsongs_path)
        if not badsongs_pairs:
            warn("  No duplicate pairs found in badsongs.txt input.")
        badsongs_skip_map, badsongs_unresolved = evaluate_duplicate_pairs(
            badsongs_pairs
        )
        skip_map.update(badsongs_skip_map)
        unresolved += badsongs_unresolved

    info(
        f"Duplicate scan complete: {len(skip_map)} skip decision(s), "
        f"{unresolved} unresolved pair/group(s)."
    )
    return skip_map, unresolved


def _chart_has_required_instruments(chart_path: str) -> bool:
    """Return True when a .chart file contains at least one required instrument section."""
    try:
        with open(chart_path, encoding="utf-8-sig", errors="ignore") as f:
            content = f.read()
    except OSError:
        return False

    upper_content = content.upper()
    upper_markers = map(str.upper, _CHART_INSTRUMENT_SECTION_MARKERS)
    return any(marker in upper_content for marker in upper_markers)


def _midi_has_required_instruments(midi_path: str) -> bool:
    """Return True when a MIDI file contains at least one required instrument track."""
    try:
        import mido

        mid = mido.MidiFile(midi_path, clip=True, charset="utf-8")
    except Exception:
        return False

    for track in mid.tracks:
        track_name = ""
        for msg in track:
            if getattr(msg, "type", None) == "track_name":
                track_name = str(msg.name).upper().strip()
                break
        if not track_name:
            continue
        if any(kw in track_name for kw in ("GHL", "VOCAL", "HARM", "REAL")):
            continue
        if any(pattern.search(track_name) for pattern in _MIDI_REQUIRED_TRACK_PATTERNS):
            return True

    return False


def has_required_instruments(folder: str) -> bool:
    """Return True when a song folder has at least one playable required instrument."""
    chart_path = _find_chart(folder)
    if chart_path and _chart_has_required_instruments(chart_path):
        return True

    midi_path = _find_midi(folder)
    if midi_path and _midi_has_required_instruments(midi_path):
        return True

    return False


def scan_no_part_song_folders(root_dir: str) -> tuple[list[str], int]:
    """Scan song folders and report those with no playable required instruments."""
    root_dir = os.path.realpath(root_dir)
    if not os.path.isdir(root_dir):
        err(f"Directory not found: {root_dir}")
        sys.exit(1)

    section("No-part scan")

    matches = []
    scanned = 0
    for dirpath, dirnames, _filenames in os.walk(root_dir):
        if not _is_song_folder(dirpath):
            continue
        dirnames[:] = []
        scanned += 1

        if has_required_instruments(dirpath):
            continue

        matches.append(os.path.realpath(dirpath))
        warn(f"  No required instruments: {dirpath}")

    info(
        f"No-part scan complete: {len(matches)} folder(s) without required instruments, "
        f"{scanned} song folder(s) scanned."
    )
    return matches, scanned


def _delete_song_folder(folder: str, dry_run: bool = False) -> bool:
    """Delete a song folder and report the action."""
    folder = os.path.realpath(folder)
    if not os.path.isdir(folder):
        warn(f"  Skipping missing folder: {folder}")
        return False

    if dry_run:
        warn(f"  [DRY RUN] Would delete: {folder}")
        return True

    try:
        import shutil

        shutil.rmtree(folder)
        ok(f"  Deleted: {folder}")
        return True
    except OSError as exc:
        err(f"  Failed to delete {folder}: {exc}")
        return False


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

    # Step 1 — MIDI conversion if needed (only if no chart yet)
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

    # Scan duplicate song folders only
    python ch-chart-fix.py --scan-duplicates --batch \
        ~/Music/CloneHero/songs/

    # Scan duplicate song folders and delete the lower-priority copies
    python ch-chart-fix.py --scan-duplicates --delete --batch \
        ~/Music/CloneHero/songs/

    # Scan duplicates using Clone Hero badsongs.txt pairs
    python ch-chart-fix.py --scan-duplicates --badsongs \
        ~/Documents/badsongs.txt ~/Music/CloneHero/songs/

    # Scan for song folders with no playable instruments
    python ch-chart-fix.py --scan-no-parts --batch ~/Music/CloneHero/songs/

    # Scan for no-part folders and delete them
    python ch-chart-fix.py --scan-no-parts --delete --batch ~/Music/CloneHero/songs/

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
        "--scan-duplicates",
        action="store_true",
        help="Scan duplicate song folders only; do not convert or downchart",
    )
    parser.add_argument(
        "--scan-no-parts",
        action="store_true",
        help="Scan song folders with no playable instruments; do not convert or downchart",
    )
    parser.add_argument(
        "--delete",
        action="store_true",
        help="Delete folders selected by a scan mode",
    )
    parser.add_argument(
        "--badsongs",
        help="Path to Clone Hero badsongs.txt for duplicate pair comparisons",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without writing files",
    )

    args = parser.parse_args()

    if args.dry_run:
        warn("DRY RUN — no files will be written.\n")

    if args.scan_duplicates and args.scan_no_parts:
        err("Use only one scan mode at a time.")
        sys.exit(1)

    if args.delete and not (args.scan_duplicates or args.scan_no_parts):
        err("--delete can only be used with --scan-duplicates or --scan-no-parts.")
        sys.exit(1)

    if args.badsongs and not args.scan_duplicates:
        err("--badsongs can only be used with --scan-duplicates.")
        sys.exit(1)

    path = args.path

    # Transparently handle .zip input
    if path.lower().endswith(".zip"):
        if args.batch or args.scan_duplicates or args.scan_no_parts:
            err("--batch cannot be used with a .zip file.")
            sys.exit(1)
        section(f"ZIP input: {path}")
        info("Extracting zip …")
        path = extract_zip(path, dry_run=args.dry_run)
        if path is None:
            sys.exit(1)

    if args.scan_duplicates:
        if args.batch:
            scan_root = path
        else:
            real_path = os.path.realpath(path)
            if os.path.isdir(real_path) and _is_song_folder(real_path):
                scan_root = os.path.dirname(real_path)
            else:
                scan_root = real_path
        skip_map, _unresolved = scan_duplicate_song_folders(
            scan_root, badsongs_path=args.badsongs
        )
        if args.delete:
            info("Deleting duplicate losers …")
            for loser_path in sorted(skip_map):
                _delete_song_folder(loser_path, dry_run=args.dry_run)
        sys.exit(0)

    if args.scan_no_parts:
        if args.batch:
            scan_root = path
        else:
            real_path = os.path.realpath(path)
            if os.path.isdir(real_path) and _is_song_folder(real_path):
                scan_root = os.path.dirname(real_path)
            else:
                scan_root = real_path
        no_part_folders, _scanned = scan_no_part_song_folders(scan_root)
        if args.delete:
            info("Deleting no-part folders …")
            for folder in no_part_folders:
                _delete_song_folder(folder, dry_run=args.dry_run)
        sys.exit(0)

    if args.batch:
        batch_process(path, dry_run=args.dry_run)
    else:
        section(f"Single folder: {path}")
        ok_result = process_song_folder(path, dry_run=args.dry_run)
        sys.exit(0 if ok_result else 1)


if __name__ == "__main__":
    main()
