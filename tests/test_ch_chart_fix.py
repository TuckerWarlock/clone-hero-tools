"""
Smoke tests for ch-chart-fix.py

Tests cover the two pure-Python functions that do the actual work:
  - add_difficulties()  — generates Hard/Medium/Easy from Expert
  - convert_midi_to_chart()  — MIDI → .chart conversion (import-only smoke test)

No real audio files required; we synthesise minimal .chart content in-memory.
"""

import importlib.util
import os
import re
import textwrap  # noqa: F401 — kept for any future use in helpers

# ── Import the script as a module ───────────────────────────────────────────
# ch-chart-fix.py uses a hyphen so we load it by path rather than import name.
_SCRIPT = os.path.join(os.path.dirname(__file__), "..", "ch-chart-fix.py")
spec = importlib.util.spec_from_file_location("ch_chart_fix", _SCRIPT)
ch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ch)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _minimal_chart(expert_notes: str, resolution: int = 192) -> str:
    """Return a minimal valid .chart string with a single ExpertSingle block."""
    # Build the chart line-by-line to avoid textwrap.dedent breaking when
    # multi-line expert_notes strings have different leading indentation.
    lines = [
        "[Song]",
        "{",
        f"  Resolution = {resolution}",
        "}",
        "[SyncTrack]",
        "{",
        "  0 = TS 4",
        "  0 = B 120000",
        "}",
        "[Events]",
        "{",
        "}",
        "[ExpertSingle]",
        "{",
        expert_notes,
        "}",
        "",
    ]
    return "\n".join(lines)


def _sections(chart_text: str) -> set:
    """Return the set of section names found in a chart string."""
    return set(re.findall(r"^\[([A-Za-z]+)\]", chart_text, re.MULTILINE))


def _notes_in_section(chart_text: str, section: str) -> list[tuple[int, int]]:
    """Return list of (tick, fret) tuples for note lines inside *section*."""
    pattern = rf"\[{section}\]\s*\{{\s*([\s\S]*?)\s*\}}"
    m = re.search(pattern, chart_text)
    if not m:
        return []
    body = m.group(1)
    return [
        (int(t), int(c))
        for t, c in re.findall(r"(\d+)\s*=\s*N\s+(\d+)\s+\d+", body)
        if int(c) <= 4  # skip modifier flags (5, 6)
    ]


# ─────────────────────────────────────────────────────────────────────────────
# Tests — add_difficulties()
# ─────────────────────────────────────────────────────────────────────────────


class TestAddDifficulties:
    def test_all_four_sections_created(self, tmp_path):
        """A chart with only ExpertSingle gains Hard/Medium/EasySingle."""
        chart = _minimal_chart("  0 = N 0 0\n  192 = N 1 0")
        path = tmp_path / "notes.chart"
        path.write_text(chart, encoding="utf-8")

        result = ch.add_difficulties(str(path))

        assert result is True
        content = path.read_text(encoding="utf-8")
        secs = _sections(content)
        assert {"ExpertSingle", "HardSingle", "MediumSingle", "EasySingle"} <= secs

    def test_no_expert_returns_false(self, tmp_path):
        """A chart with no Expert section should return False without touching the file."""
        chart = textwrap.dedent("""\
            [Song]
            {
              Resolution = 192
            }
            [SyncTrack]
            {
              0 = B 120000
            }
            [Events]
            {
            }
            """)
        path = tmp_path / "notes.chart"
        path.write_text(chart, encoding="utf-8")

        result = ch.add_difficulties(str(path))
        assert result is False

    def test_force_replace_regenerates_lower_difficulties(self, tmp_path):
        """Existing Hard/Medium/Easy blocks are stripped and regenerated."""
        chart = _minimal_chart("  0 = N 0 0")
        path = tmp_path / "notes.chart"
        path.write_text(chart, encoding="utf-8")
        # First pass
        ch.add_difficulties(str(path), force_replace=True)
        first = path.read_text(encoding="utf-8")
        # Second pass should produce identical output
        ch.add_difficulties(str(path), force_replace=True)
        second = path.read_text(encoding="utf-8")

        assert first == second


class TestDownchartNotes:
    """Unit tests for _downchart_notes() in isolation."""

    RES = 192

    def _run(self, notes_str: str, difficulty: str) -> list[tuple[int, int]]:
        result = ch._downchart_notes(notes_str, difficulty, self.RES)
        return [
            (int(t), int(c))
            for t, c in re.findall(r"(\d+)\s*=\s*N\s+(\d+)\s+\d+", result)
            if int(c) <= 4
        ]

    # ── Color mapping ────────────────────────────────────────────────────────

    def test_medium_remaps_orange_to_purple(self):
        """Fret 4 (orange) → fret 3 (purple) on Medium."""
        notes = "  0 = N 4 0"
        result = self._run(notes, "Medium")
        assert result == [(0, 3)]

    def test_easy_remaps_high_frets_to_yellow(self):
        """Frets 3 and 4 → fret 2 (yellow) on Easy."""
        notes = "  0 = N 3 0\n  384 = N 4 0"
        result = self._run(notes, "Easy")
        assert all(fret == 2 for _, fret in result)

    def test_easy_leaves_open_note_unchanged(self):
        """Open note (fret 7) is never remapped on Easy."""
        notes = "  0 = N 7 0"
        result = ch._downchart_notes(notes, "Easy", self.RES)
        assert "N 7" in result

    # ── Speed thinning ───────────────────────────────────────────────────────

    def test_easy_drops_sub_quarter_note_notes(self):
        """Notes closer than 1 full quarter note are thinned on Easy."""
        # 4 notes at 8th-note intervals — only every other one should survive
        notes = "\n".join(f"  {i * 96} = N 0 0" for i in range(4))
        result = self._run(notes, "Easy")
        ticks = [t for t, _ in result]
        # No two surviving ticks should be closer than RES (192)
        for a, b in zip(ticks, ticks[1:]):
            assert b - a >= self.RES

    def test_medium_allows_eighth_note_density(self):
        """Medium allows notes as close as 1 eighth note (RES / 2 = 96 ticks)."""
        notes = "  0 = N 0 0\n  96 = N 1 0"
        result = self._run(notes, "Medium")
        assert len(result) == 2

    # ── Chord limits ─────────────────────────────────────────────────────────

    def test_easy_enforces_single_note_per_tick(self):
        """Easy allows only 1 note per tick."""
        notes = "  0 = N 0 0\n  0 = N 1 0"
        result = self._run(notes, "Easy")
        assert len(result) == 1

    def test_medium_allows_two_note_chords(self):
        """Medium allows up to 2-note chords."""
        notes = "  0 = N 0 0\n  0 = N 1 0\n  0 = N 2 0"
        result = self._run(notes, "Medium")
        same_tick = [fret for tick, fret in result if tick == 0]
        assert len(same_tick) == 2

    def test_medium_trims_overlap_after_orange_to_purple_remap(self):
        """Orange sustain remapped to lane 3 must not overlap the next lane-3 note."""
        # Tick 0 has lane-4 sustain (orange) plus another lane in chord.
        # On Medium, lane 4 -> lane 3. Next lane-3 note appears at tick 96,
        # so sustain must be trimmed to <= 96.
        notes = "  0 = N 4 192\n  0 = N 1 0\n  96 = N 3 0"
        result_raw = ch._downchart_notes(notes, "Medium", self.RES)
        m = re.search(r"^\s*0\s*=\s*N\s+3\s+(\d+)", result_raw, re.MULTILINE)
        assert m is not None
        assert int(m.group(1)) <= 96

    def test_hard_passes_through_all_notes(self):
        """Hard applies no speed thinning or chord limits."""
        notes = "  0 = N 0 0\n  0 = N 1 0\n  0 = N 2 0\n  48 = N 3 0"
        result = self._run(notes, "Hard")
        assert len(result) == 4

    # ── Force modifier handling ───────────────────────────────────────────────

    def test_hard_keeps_force_modifiers(self):
        """Hard preserves N 5 / N 6 (force HOPO/strum)."""
        notes = "  0 = N 0 0\n  0 = N 5 0"
        result_raw = ch._downchart_notes(notes, "Hard", self.RES)
        assert "N 5" in result_raw

    def test_easy_strips_force_modifiers(self):
        """Easy drops N 5 / N 6 force modifiers."""
        notes = "  0 = N 0 0\n  0 = N 5 0"
        result_raw = ch._downchart_notes(notes, "Easy", self.RES)
        assert "N 5" not in result_raw

    # ── Star Power passthrough ───────────────────────────────────────────────

    def test_star_power_passes_through(self):
        """S 2 (Star Power) lines are kept intact in all difficulties."""
        notes = "  0 = N 0 0\n  0 = S 2 768"
        for diff in ("Hard", "Medium", "Easy"):
            result_raw = ch._downchart_notes(notes, diff, self.RES)
            assert "S 2 768" in result_raw, f"Star Power missing from {diff}"


# ─────────────────────────────────────────────────────────────────────────────
# Tests — process_song_folder()
# ─────────────────────────────────────────────────────────────────────────────


class TestProcessSongFolder:
    def test_single_folder_end_to_end(self, tmp_path):
        """Full pipeline: Expert-only chart → all four difficulties written."""
        notes = "\n".join(f"  {i * 192} = N {i % 5} 0" for i in range(8))
        chart_text = _minimal_chart(notes)
        (tmp_path / "notes.chart").write_text(chart_text, encoding="utf-8")
        (tmp_path / "song.ini").write_text("[song]\nname = Test\n", encoding="utf-8")

        ok = ch.process_song_folder(str(tmp_path))
        assert ok is True

        content = (tmp_path / "notes.chart").read_text(encoding="utf-8")
        assert _sections(content) >= {
            "ExpertSingle",
            "HardSingle",
            "MediumSingle",
            "EasySingle",
        }

    def test_missing_expert_returns_false(self, tmp_path):
        """A chart with no Expert section should not be modified and return False."""
        chart_text = textwrap.dedent("""\
            [Song]
            {
              Resolution = 192
            }
            [SyncTrack]
            {
              0 = B 120000
            }
            [Events]
            {
            }
            """)
        (tmp_path / "notes.chart").write_text(chart_text, encoding="utf-8")
        (tmp_path / "song.ini").write_text("", encoding="utf-8")

        result = ch.process_song_folder(str(tmp_path))
        assert result is False

    def test_dry_run_does_not_write(self, tmp_path):
        """--dry-run must not modify the chart file."""
        notes = "  0 = N 0 0"
        chart_text = _minimal_chart(notes)
        path = tmp_path / "notes.chart"
        path.write_text(chart_text, encoding="utf-8")
        (tmp_path / "song.ini").write_text("", encoding="utf-8")
        original = path.read_text(encoding="utf-8")

        ch.process_song_folder(str(tmp_path), dry_run=True)

        assert path.read_text(encoding="utf-8") == original

    def test_nonexistent_folder_returns_false(self, tmp_path):
        result = ch.process_song_folder(str(tmp_path / "does_not_exist"))
        assert result is False


# ─────────────────────────────────────────────────────────────────────────────
# Tests — extract_zip()
# ─────────────────────────────────────────────────────────────────────────────


def _make_zip(zip_path, members: dict[str, str]) -> None:
    """Write a zip file where keys are member paths and values are file content."""
    import zipfile

    with zipfile.ZipFile(zip_path, "w") as zf:
        for name, content in members.items():
            zf.writestr(name, content)


class TestExtractZip:
    def _chart(self) -> str:
        return _minimal_chart("  0 = N 0 0\n  192 = N 1 0")

    def test_wrapped_layout_extracts_to_named_folder(self, tmp_path):
        """Zip with a single top-level folder is extracted preserving that name."""
        zip_path = tmp_path / "artist-song.zip"
        _make_zip(
            zip_path,
            {
                "Artist - Song/notes.chart": self._chart(),
                "Artist - Song/song.ini": "[song]\nname = Test\n",
            },
        )

        result = ch.extract_zip(str(zip_path))

        assert result is not None
        song_folder = tmp_path / "Artist - Song"
        assert song_folder.is_dir()
        assert (song_folder / "notes.chart").exists()

    def test_flat_layout_extracts_into_zip_stem_folder(self, tmp_path):
        """Zip with files at the root is extracted into a folder named after the zip."""
        zip_path = tmp_path / "my-song.zip"
        _make_zip(
            zip_path,
            {
                "notes.chart": self._chart(),
                "song.ini": "[song]\nname = Test\n",
            },
        )

        result = ch.extract_zip(str(zip_path))

        assert result is not None
        song_folder = tmp_path / "my-song"
        assert song_folder.is_dir()
        assert (song_folder / "notes.chart").exists()

    def test_invalid_zip_returns_none(self, tmp_path):
        """A non-zip file passed to extract_zip returns None without raising."""
        bad = tmp_path / "not-a-zip.zip"
        bad.write_bytes(b"this is not a zip")

        result = ch.extract_zip(str(bad))
        assert result is None

    def test_dry_run_does_not_extract(self, tmp_path):
        """Dry run returns the expected destination path but writes nothing."""
        zip_path = tmp_path / "song.zip"
        _make_zip(zip_path, {"Artist - Song/notes.chart": self._chart()})

        result = ch.extract_zip(str(zip_path), dry_run=True)

        assert result is not None
        # The folder must NOT have been created
        assert not (tmp_path / "Artist - Song").exists()

    def test_zip_to_chart_full_pipeline(self, tmp_path):
        """End-to-end: zip → extract → all 4 difficulties generated."""
        zip_path = tmp_path / "song.zip"
        _make_zip(
            zip_path,
            {
                "My Song/notes.chart": self._chart(),
                "My Song/song.ini": "[song]\nname = My Song\n",
            },
        )

        song_folder = ch.extract_zip(str(zip_path))
        assert song_folder is not None

        ok = ch.process_song_folder(song_folder)
        assert ok is True

        content = (tmp_path / "My Song" / "notes.chart").read_text(encoding="utf-8")
        for diff in ("Expert", "Hard", "Medium", "Easy"):
            assert f"[{diff}Single]" in content


# ─────────────────────────────────────────────────────────────────────────────
# Tests — Duplicate detection & community-chart preference
# ─────────────────────────────────────────────────────────────────────────────


def _make_song_folder(
    root,
    name: str,
    chart_text: str,
    *,
    preview: bool = False,
    album_ext: str = ".png",
    audio_ext: str = ".mp3",
    metadata_lines: list[str] | None = None,
    song_name: str = "Test Song",
    artist: str = "Test Artist",
):
    folder = root / name
    folder.mkdir()
    (folder / "notes.chart").write_text(chart_text, encoding="utf-8")

    ini_lines = ["[song]", f"name = {song_name}", f"artist = {artist}"]
    if metadata_lines:
        ini_lines.extend(metadata_lines)
    (folder / "song.ini").write_text("\n".join(ini_lines) + "\n", encoding="utf-8")

    (folder / f"song{audio_ext}").write_bytes(b"a" * 1024)
    (folder / f"guitar{audio_ext}").write_bytes(b"b" * 1024)
    if preview:
        (folder / f"preview{audio_ext}").write_bytes(b"c" * 512)
    (folder / f"album{album_ext}").write_bytes(b"cover")
    return folder


class TestDuplicateDetection:
    def test_count_notes_in_chart(self, tmp_path):
        """Count notes in a simple chart."""
        chart = _minimal_chart("  0 = N 0 0\n  192 = N 1 0\n  384 = N 2 0")
        path = tmp_path / "notes.chart"
        path.write_text(chart, encoding="utf-8")

        count = ch._count_notes_in_chart(str(path))
        assert count == 3

    def test_identical_chart_prefers_better_assets(self, tmp_path):
        """If chart hashes match, keep the folder with better assets/metadata."""
        chart_text = _minimal_chart("  0 = N 0 0\n  192 = N 1 0")
        plain = _make_song_folder(
            tmp_path,
            "Mastodon - Sleeping Giant",
            chart_text,
            preview=True,
            metadata_lines=[
                "album = Blood Mountain",
                "year = 2006",
                "genre = Metal",
                "charter = Neversoft",
                "icon = gh3dlc",
                "unlock_id = gh3_dlc07",
            ],
        )
        duplicate = _make_song_folder(
            tmp_path,
            "Mastodon - Sleeping Giant (Neversoft)",
            chart_text,
            preview=False,
            album_ext=".jpg",
            audio_ext=".opus",
            metadata_lines=["charter = Neversoft"],
        )

        result = ch.compare_duplicate_song_folders(str(plain), str(duplicate))

        assert result["preferred"] == str(plain)
        assert result["other"] == str(duplicate)
        assert result["reason"] == "identical-chart-better-assets"
        assert result["identical_chart"] is True

    def test_non_identical_chart_prefers_higher_complexity(self, tmp_path):
        """If charts differ, keep the more complex chart before asset tiebreaks."""
        simple = _make_song_folder(
            tmp_path,
            "simple",
            _minimal_chart("  0 = N 0 0"),
            preview=True,
        )
        complex_song = _make_song_folder(
            tmp_path,
            "complex",
            _minimal_chart("  0 = N 0 0\n  192 = N 1 0\n  384 = N 2 0\n  576 = N 3 0"),
            preview=False,
        )

        result = ch.compare_duplicate_song_folders(str(simple), str(complex_song))

        assert result["preferred"] == str(complex_song)
        assert result["other"] == str(simple)
        assert result["reason"] == "higher-chart-complexity"
        assert result["identical_chart"] is False

    def test_true_tie_requires_manual_review(self, tmp_path):
        """If charts and assets tie, the duplicate should stay unresolved."""
        chart_text = _minimal_chart("  0 = N 0 0\n  192 = N 1 0")
        folder_a = _make_song_folder(tmp_path, "a", chart_text)
        folder_b = _make_song_folder(tmp_path, "b", chart_text)

        result = ch.compare_duplicate_song_folders(str(folder_a), str(folder_b))

        assert result["preferred"] is None
        assert result["other"] is None
        assert result["reason"] == "manual-review"
        assert result["identical_chart"] is True

    def test_find_duplicate_song_groups_only_within_same_parent(self, tmp_path):
        """Sibling duplicates are grouped together, but not across parents."""
        chart_text = _minimal_chart("  0 = N 0 0")
        downloaded = tmp_path / "downloaded"
        downloaded.mkdir()
        pack = tmp_path / "pack"
        pack.mkdir()

        _make_song_folder(
            downloaded,
            "Mastodon - Sleeping Giant",
            chart_text,
            song_name="Sleeping Giant",
            artist="Mastodon",
        )
        _make_song_folder(
            downloaded,
            "Mastodon - Sleeping Giant (Neversoft)",
            chart_text,
            song_name="Sleeping Giant",
            artist="Mastodon",
        )
        _make_song_folder(
            pack,
            "Mastodon - Sleeping Giant",
            chart_text,
            song_name="Sleeping Giant",
            artist="Mastodon",
        )

        groups = ch.find_duplicate_song_groups(str(tmp_path))

        assert len(groups) == 1
        assert len(groups[0]) == 2
        assert all("downloaded" in path for path in groups[0])

    def test_parse_badsongs_duplicate_pairs(self, tmp_path):
        """The badsongs parser extracts duplicate pairs, including names with parentheses."""
        badsongs = tmp_path / "badsongs.txt"
        badsongs.write_text(
            "\n".join(
                [
                    "Warning: ignored section",
                    ch._BADSONGS_DUPLICATE_HEADER,
                    (
                        "/songs/Mastodon - Sleeping Giant "
                        "(/songs/Mastodon - Sleeping Giant (Neversoft))"
                    ),
                    (
                        "/songs/Sikth - Cracks of Light (feat. Spencer Sotelo) "
                        "(Chezy) (/songs/Sikth - Cracks of Light "
                        "(feat. Spencer Sotelo))"
                    ),
                ]
            ),
            encoding="utf-8",
        )

        pairs = ch.parse_badsongs_duplicate_pairs(str(badsongs))

        assert pairs == [
            (
                "/songs/Mastodon - Sleeping Giant",
                "/songs/Mastodon - Sleeping Giant (Neversoft)",
            ),
            (
                "/songs/Sikth - Cracks of Light (feat. Spencer Sotelo) (Chezy)",
                "/songs/Sikth - Cracks of Light (feat. Spencer Sotelo)",
            ),
        ]
