#!/usr/bin/env python3
"""Split DEVLOG markdown into weekly archives and prepend a lean summary intro."""

from __future__ import annotations

import argparse
import logging
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterable

logger = logging.getLogger(__name__)

DEFAULT_SOURCE_PATH = Path("devlog/DEVLOG.md")
ARCHIVE_OUTPUT_DIR = Path("devlog/archive")
SPLIT_THRESHOLD_BYTES = 75 * 1024
ARCHIVE_TARGET_MIN_LINES = 750
HEADING_PATTERN = re.compile(r"^##\s+(\d{4}-\d{2}-\d{2})(?:\b|\s*[:\-])")
INTRO_BLOCK_START = "<!-- devlog-weekly-intro:start -->"
INTRO_BLOCK_END = "<!-- devlog-weekly-intro:end -->"
ASKY_SUMMARY_PROMPT = (
    "Read the provided local corpus file and create a concise introduction for this "
    "week's devlog. Output exactly one block in this format and nothing else: "
    "<intro>...markdown content...</intro>. Keep it under 140 words with one short "
    "paragraph followed by 3-5 bullet points."
)
INTRO_CAPTURE_PATTERN = re.compile(r"<intro>\s*(.*?)\s*</intro>", re.DOTALL)


@dataclass(frozen=True)
class DevlogEntry:
    """One dated DEVLOG entry block."""

    entry_date: date
    heading: str
    block: str

    @property
    def line_count(self) -> int:
        return len(self.block.splitlines())

    @property
    def iso_week_key(self) -> tuple[int, int]:
        iso = self.entry_date.isocalendar()
        return (iso.year, iso.week)


@dataclass(frozen=True)
class ParsedDevlog:
    """Parsed markdown split into preamble and dated entry blocks."""

    preamble: str
    entries: list[DevlogEntry]


@dataclass(frozen=True)
class ArchiveBatch:
    """A merged contiguous range of older weekly entries."""

    entries: list[DevlogEntry]

    @property
    def line_count(self) -> int:
        return sum(entry.line_count for entry in self.entries)

    @property
    def oldest_date(self) -> date:
        return min(entry.entry_date for entry in self.entries)

    @property
    def newest_date(self) -> date:
        return max(entry.entry_date for entry in self.entries)


def configure_logging() -> None:
    """Initialize simple script logging."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


def _strip_intro_block(text: str) -> str:
    """Remove managed intro block if present."""
    start = text.find(INTRO_BLOCK_START)
    end = text.find(INTRO_BLOCK_END)
    if start == -1 or end == -1 or end < start:
        return text

    end_idx = end + len(INTRO_BLOCK_END)
    while end_idx < len(text) and text[end_idx] in "\r\n":
        end_idx += 1
    return text[:start] + text[end_idx:]


def parse_devlog_markdown(text: str) -> ParsedDevlog:
    """Parse preamble and dated markdown entries."""
    normalized = _strip_intro_block(text)
    lines = normalized.splitlines(keepends=True)

    heading_indices: list[tuple[int, date, str]] = []
    for index, line in enumerate(lines):
        match = HEADING_PATTERN.match(line.strip())
        if not match:
            continue
        entry_date = date.fromisoformat(match.group(1))
        heading_indices.append((index, entry_date, line))

    if not heading_indices:
        return ParsedDevlog(preamble=normalized, entries=[])

    preamble = "".join(lines[: heading_indices[0][0]])
    entries: list[DevlogEntry] = []
    for idx, (start, entry_date, heading) in enumerate(heading_indices):
        end = (
            heading_indices[idx + 1][0]
            if idx + 1 < len(heading_indices)
            else len(lines)
        )
        block = "".join(lines[start:end])
        entries.append(
            DevlogEntry(
                entry_date=entry_date, heading=heading.rstrip("\n"), block=block
            )
        )

    return ParsedDevlog(preamble=preamble, entries=entries)


def split_current_week_entries(
    entries: list[DevlogEntry],
    *,
    today: date,
) -> tuple[list[DevlogEntry], list[DevlogEntry]]:
    """Split entries into current ISO week and older entries."""
    current_key = (today.isocalendar().year, today.isocalendar().week)
    current_week: list[DevlogEntry] = []
    older: list[DevlogEntry] = []
    for entry in entries:
        if entry.iso_week_key == current_key:
            current_week.append(entry)
        else:
            older.append(entry)
    return current_week, older


def _contiguous_week_buckets(entries: Iterable[DevlogEntry]) -> list[list[DevlogEntry]]:
    """Group adjacent entries by ISO week while preserving file order."""
    buckets: list[list[DevlogEntry]] = []
    for entry in entries:
        if not buckets or buckets[-1][0].iso_week_key != entry.iso_week_key:
            buckets.append([entry])
            continue
        buckets[-1].append(entry)
    return buckets


def build_archive_batches(
    older_entries: list[DevlogEntry],
    *,
    min_lines: int = ARCHIVE_TARGET_MIN_LINES,
) -> list[ArchiveBatch]:
    """Merge contiguous weekly buckets until each batch reaches target lines."""
    if not older_entries:
        return []

    buckets = _contiguous_week_buckets(older_entries)
    batches: list[ArchiveBatch] = []
    working_entries: list[DevlogEntry] = []
    working_lines = 0

    for bucket in buckets:
        working_entries.extend(bucket)
        working_lines += sum(item.line_count for item in bucket)
        if working_lines >= min_lines:
            batches.append(ArchiveBatch(entries=list(working_entries)))
            working_entries = []
            working_lines = 0

    if working_entries:
        batches.append(ArchiveBatch(entries=list(working_entries)))

    return batches


def _next_archive_path(output_dir: Path, creation_date: date) -> Path:
    """Return next collision-safe archive filename for creation date."""
    stem = creation_date.strftime("%Y.%m.%d")
    candidate = output_dir / f"{stem}.md"
    if not candidate.exists():
        return candidate

    suffix = 2
    while True:
        candidate = output_dir / f"{stem}-{suffix:02d}.md"
        if not candidate.exists():
            return candidate
        suffix += 1


def _render_archive_body(
    batch: ArchiveBatch, source_name: str, creation_date: date
) -> str:
    """Render archive markdown file."""
    body = "".join(entry.block for entry in batch.entries).rstrip()
    return (
        f"# DEVLOG Archive ({batch.oldest_date.isoformat()} to {batch.newest_date.isoformat()})\n\n"
        f"Archived on {creation_date.isoformat()} from `{source_name}`.\n\n"
        "---\n\n"
        "# DEVLOG\n\n"
        f"{body}\n"
    )


def write_archive_batches(
    batches: list[ArchiveBatch],
    *,
    output_dir: Path,
    source_name: str,
    creation_date: date,
) -> list[Path]:
    """Write archive files and return created paths in write order."""
    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for batch in batches:
        path = _next_archive_path(output_dir, creation_date)
        path.write_text(
            _render_archive_body(
                batch=batch, source_name=source_name, creation_date=creation_date
            ),
            encoding="utf-8",
        )
        written.append(path)
    return written


def _normalize_summary_text(raw_output: str) -> str:
    """Extract managed summary markdown from asky output."""
    match = INTRO_CAPTURE_PATTERN.search(raw_output)
    if match:
        return match.group(1).strip()
    return raw_output.strip()


def generate_intro_summary(archive_path: Path) -> str:
    """Generate summary text using installed asky in lean mode."""
    try:
        completed = subprocess.run(
            [
                "asky",
                "-L",
                "-r",
                str(archive_path),
                ASKY_SUMMARY_PROMPT,
            ],
            capture_output=True,
            text=True,
            check=True,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("asky command not found in PATH") from exc
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()
        raise RuntimeError(
            f"asky summary command failed: {stderr or exc.returncode}"
        ) from exc

    summary = _normalize_summary_text(completed.stdout)
    if not summary:
        raise RuntimeError("asky summary command returned empty output")
    return summary


def _render_intro_block(
    summary_markdown: str, archive_path: Path, creation_date: date
) -> str:
    """Create managed intro markdown block."""
    return (
        f"{INTRO_BLOCK_START}\n"
        "## Weekly Summary\n\n"
        f"_Generated on {creation_date.isoformat()} from `{archive_path.name}` via `asky -L`._\n\n"
        f"{summary_markdown.strip()}\n"
        f"{INTRO_BLOCK_END}\n\n"
    )


def render_source_markdown(
    *,
    preamble: str,
    current_entries: list[DevlogEntry],
    intro_block: str,
) -> str:
    """Render rewritten source markdown with managed intro and current-week entries."""
    preamble_clean = preamble.rstrip()
    current_body = "".join(entry.block for entry in current_entries).rstrip()

    parts: list[str] = [intro_block.rstrip(), ""]
    if preamble_clean:
        parts.append(preamble_clean)
        parts.append("")
    if current_body:
        parts.append(current_body)
    output = "\n".join(parts).rstrip() + "\n"
    return output


def process_devlog(
    source_path: Path,
    *,
    today: date,
) -> int:
    """Execute one-pass devlog archive/summarize flow."""
    if not source_path.exists():
        logger.error("Source file does not exist: %s", source_path)
        return 1

    if source_path.stat().st_size <= SPLIT_THRESHOLD_BYTES:
        logger.info(
            "No action: %s is %d bytes (threshold is %d).",
            source_path,
            source_path.stat().st_size,
            SPLIT_THRESHOLD_BYTES,
        )
        return 0

    original_text = source_path.read_text(encoding="utf-8")
    parsed = parse_devlog_markdown(original_text)
    if not parsed.entries:
        logger.info("No action: no dated entries found in %s.", source_path)
        return 0

    current_entries, older_entries = split_current_week_entries(
        parsed.entries, today=today
    )
    if not older_entries:
        logger.info("No action: no older entries to archive in %s.", source_path)
        return 0

    batches = build_archive_batches(older_entries)
    archive_paths = write_archive_batches(
        batches,
        output_dir=ARCHIVE_OUTPUT_DIR,
        source_name=source_path.name,
        creation_date=today,
    )

    newest_archived_path = archive_paths[0]
    summary_text = generate_intro_summary(newest_archived_path)
    intro_block = _render_intro_block(summary_text, newest_archived_path, today)

    rewritten = render_source_markdown(
        preamble=parsed.preamble,
        current_entries=current_entries,
        intro_block=intro_block,
    )
    source_path.write_text(rewritten, encoding="utf-8")

    logger.info(
        "Archived %d entries into %d file(s). Updated %s.",
        len(older_entries),
        len(archive_paths),
        source_path,
    )
    for path in archive_paths:
        logger.info("Created archive: %s", path)
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Build CLI argument parser."""
    parser = argparse.ArgumentParser(
        description=(
            "Split DEVLOG markdown into archive files by ISO week and prepend a "
            "lean-mode summary intro."
        )
    )
    parser.add_argument(
        "main_file",
        nargs="?",
        default=str(DEFAULT_SOURCE_PATH),
        help=f"Source markdown file (default: {DEFAULT_SOURCE_PATH})",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint."""
    configure_logging()
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return process_devlog(Path(args.main_file), today=date.today())
    except RuntimeError as exc:
        logger.error("%s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
