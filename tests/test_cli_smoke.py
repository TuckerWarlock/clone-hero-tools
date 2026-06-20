import subprocess
import sys
import zipfile
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _script_path() -> Path:
    return _repo_root() / "ch-chart-fix.py"


def test_help_exits_zero() -> None:
    result = subprocess.run(
        [sys.executable, str(_script_path()), "--help"],
        cwd=_repo_root(),
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "Convert Expert-only Clone Hero charts" in result.stdout


def _make_expert_chart(path: Path) -> None:
    """Write a minimal Expert-only notes.chart at the given path."""
    notes = "\n".join(f"  {i * 192} = N {i % 5} 0" for i in range(8))
    chart = "\n".join(
        [
            "[Song]",
            "{",
            "  Resolution = 192",
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
            notes,
            "}",
            "",
        ]
    )
    path.write_text(chart, encoding="utf-8")


def _make_song_dir(
    root: Path,
    name: str,
    *,
    preview: bool = False,
    chart_path_name: str = "notes.chart",
) -> Path:
    song_dir = root / name
    song_dir.mkdir()
    _make_expert_chart(song_dir / chart_path_name)
    ini_lines = [
        "[song]",
        "name = Sleeping Giant",
        "artist = Mastodon",
        "charter = Neversoft",
    ]
    if preview:
        ini_lines.append("preview_start_time = 12345")
        (song_dir / "preview.mp3").write_bytes(b"preview")
    (song_dir / "song.ini").write_text("\n".join(ini_lines) + "\n", encoding="utf-8")
    (song_dir / "song.mp3").write_bytes(b"song")
    (song_dir / "guitar.mp3").write_bytes(b"guitar")
    return song_dir


def test_expert_chart_generates_lower_difficulties(tmp_path: Path) -> None:
    song_dir = tmp_path / "song"
    song_dir.mkdir()

    chart_path = song_dir / "notes.chart"
    _make_expert_chart(chart_path)

    result = subprocess.run(
        [sys.executable, str(_script_path()), str(song_dir)],
        cwd=_repo_root(),
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0

    content = chart_path.read_text(encoding="utf-8", errors="ignore")
    assert "[ExpertSingle]" in content
    assert "[HardSingle]" in content
    assert "[MediumSingle]" in content
    assert "[EasySingle]" in content


def test_zip_input_generates_lower_difficulties(tmp_path: Path) -> None:
    """Passing a .zip file via CLI extracts it and generates all difficulties."""
    # Build a wrapped-layout zip (Artist - Song/notes.chart)
    song_name = "Artist - Test Song"
    chart_content_lines = [
        "[Song]",
        "{",
        "  Resolution = 192",
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
        "  0 = N 0 0",
        "  192 = N 1 0",
        "}",
        "",
    ]
    chart_text = "\n".join(chart_content_lines)

    zip_path = tmp_path / "test-song.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr(f"{song_name}/notes.chart", chart_text)
        zf.writestr(f"{song_name}/song.ini", "[song]\nname = Test\n")

    result = subprocess.run(
        [sys.executable, str(_script_path()), str(zip_path)],
        cwd=_repo_root(),
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0

    extracted_chart = tmp_path / song_name / "notes.chart"
    assert extracted_chart.exists(), "Extracted notes.chart not found"
    content = extracted_chart.read_text(encoding="utf-8", errors="ignore")
    for diff in ("Expert", "Hard", "Medium", "Easy"):
        assert f"[{diff}Single]" in content


def test_batch_process_does_not_run_duplicate_scan_by_default(tmp_path: Path) -> None:
    duplicate_root = tmp_path / "downloaded"
    duplicate_root.mkdir()

    preferred = _make_song_dir(
        duplicate_root, "Mastodon - Sleeping Giant", preview=True
    )
    skipped = _make_song_dir(duplicate_root, "Mastodon - Sleeping Giant (Neversoft)")

    result = subprocess.run(
        [sys.executable, str(_script_path()), "--batch", str(duplicate_root)],
        cwd=_repo_root(),
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0

    preferred_content = (preferred / "notes.chart").read_text(
        encoding="utf-8", errors="ignore"
    )
    skipped_content = (skipped / "notes.chart").read_text(
        encoding="utf-8", errors="ignore"
    )

    assert "[HardSingle]" in preferred_content
    assert "[HardSingle]" in skipped_content


def test_scan_duplicates_batch_reports_without_processing(tmp_path: Path) -> None:
    duplicate_root = tmp_path / "downloaded"
    duplicate_root.mkdir()

    preferred = _make_song_dir(
        duplicate_root, "Mastodon - Sleeping Giant", preview=True
    )
    skipped = _make_song_dir(duplicate_root, "Mastodon - Sleeping Giant (Neversoft)")

    result = subprocess.run(
        [
            sys.executable,
            str(_script_path()),
            "--scan-duplicates",
            "--batch",
            str(duplicate_root),
        ],
        cwd=_repo_root(),
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "Duplicate scan" in result.stdout
    assert (
        "Keep Mastodon - Sleeping Giant; skip Mastodon - Sleeping Giant (Neversoft)"
        in result.stdout
    )

    preferred_content = (preferred / "notes.chart").read_text(
        encoding="utf-8", errors="ignore"
    )
    skipped_content = (skipped / "notes.chart").read_text(
        encoding="utf-8", errors="ignore"
    )

    assert "[HardSingle]" not in preferred_content
    assert "[HardSingle]" not in skipped_content


def test_scan_no_parts_batch_reports_without_processing(tmp_path: Path) -> None:
    root = tmp_path / "songs"
    root.mkdir()

    good = root / "good"
    good.mkdir()
    (good / "song.ini").write_text(
        "[song]\nname = Good\nartist = Test\n",
        encoding="utf-8",
    )
    (good / "notes.chart").write_text("[Single]\n{\n}\n", encoding="utf-8")

    bad = root / "bad"
    bad.mkdir()
    (bad / "song.ini").write_text(
        "[song]\nname = Bad\nartist = Test\n",
        encoding="utf-8",
    )
    (bad / "notes.chart").write_text("[Events]\n{\n}\n", encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(_script_path()),
            "--scan-no-parts",
            "--batch",
            str(root),
        ],
        cwd=_repo_root(),
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "No-part scan" in result.stdout
    assert "No required instruments:" in result.stdout
    assert "bad" in result.stdout
    assert "[HardSingle]" not in (bad / "notes.chart").read_text(encoding="utf-8")
