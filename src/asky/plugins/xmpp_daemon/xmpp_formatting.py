"""XMPP message formatting with XEP-0393 styling and ASCII table rendering."""

import html
import re
import unicodedata
from dataclasses import dataclass, field
from typing import List, Optional

MAX_FENCE_LENGTH = 10
MIN_TABLE_COLUMN_COUNT = 2
MIN_SEPARATOR_DASH_COUNT = 1
CODE_FENCE_MARKERS = ("```", "~~~")
ATX_HEADER_PATTERN = re.compile(r"^\s*#{1,6}\s+(.+?)\s*$")
SETEXT_UNDERLINE_PATTERN = re.compile(r"^\s*(=+|-+)\s*$")
BOLD_MARKDOWN_PATTERN = re.compile(r"\*\*(.+?)\*\*")
ITALIC_MARKDOWN_PATTERN = re.compile(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)")
CODE_SPAN_PATTERN = re.compile(r"`([^`]+)`")
BULLET_LINE_PATTERN = re.compile(r"^(\s*)[*-]\s+(.*)$")


@dataclass
class TableStructure:
    """Structured table data for ASCII rendering."""
    headers: List[str]
    rows: List[List[str]]


@dataclass
class MessageModel:
    """Internal message representation before XEP-0393 formatting."""
    plain_body: str
    tables: List[TableStructure] = field(default_factory=list)


class ASCIITableRenderer:
    """Renders structured tables as ASCII text in code blocks."""

    def __init__(
        self,
        max_rows: Optional[int] = None,
        max_columns: Optional[int] = None,
        max_width: Optional[int] = None,
        size_limit_policy: str = "truncate"
    ):
        """Initialize with optional size thresholds."""
        self.max_rows = max_rows
        self.max_columns = max_columns
        self.max_width = max_width
        self.size_limit_policy = size_limit_policy

    def _display_width(self, text: str) -> int:
        """Calculate display width accounting for wide Unicode characters."""
        width = 0
        for char in text:
            if unicodedata.east_asian_width(char) in ('F', 'W'):
                width += 2
            else:
                width += 1
        return width

    def _calculate_column_widths(self, table: TableStructure) -> List[int]:
        """Calculate display width for each column."""
        if not table.headers:
            return []
        
        widths = []
        for col_idx in range(len(table.headers)):
            max_width = self._display_width(table.headers[col_idx])
            
            for row in table.rows:
                if col_idx < len(row):
                    cell_width = self._display_width(row[col_idx])
                    max_width = max(max_width, cell_width)
            
            widths.append(max_width)
        
        return widths

    def _format_row(
        self,
        cells: List[str],
        widths: List[int],
        separator: str = " | "
    ) -> str:
        """Format a single row with proper padding."""
        formatted_cells = []
        for idx, cell in enumerate(cells):
            if idx < len(widths):
                display_width = self._display_width(cell)
                padding = widths[idx] - display_width
                formatted_cells.append(cell + (' ' * padding))
            else:
                formatted_cells.append(cell)
        return separator.join(formatted_cells)

    def _format_separator(self, widths: List[int]) -> str:
        """Generate separator row with dashes."""
        separators = ['-' * width for width in widths]
        return ' | '.join(separators)

    def _determine_fence_length(self, content: str) -> int:
        """Find minimum fence length that doesn't appear in content."""
        fence_length = 3
        
        while fence_length <= MAX_FENCE_LENGTH:
            fence = '`' * fence_length
            if fence not in content:
                return fence_length
            fence_length += 1
        
        return 3

    def render_table(self, table: TableStructure) -> str:
        """Render table as ASCII text wrapped in fenced code block."""
        if not table.headers:
            return ""
        
        widths = self._calculate_column_widths(table)
        
        lines = []
        lines.append(self._format_row(table.headers, widths))
        lines.append(self._format_separator(widths))
        
        for row in table.rows:
            lines.append(self._format_row(row, widths))
        
        table_content = '\n'.join(lines)
        fence_length = self._determine_fence_length(table_content)
        fence = '`' * fence_length
        
        return f"{fence}\n{table_content}\n{fence}"



class MessageFormatter:
    """Converts internal message representation to XEP-0393 formatted text."""

    def __init__(
        self,
        table_renderer: ASCIITableRenderer,
        disco_cache: Optional[object] = None
    ):
        """Initialize formatter with table renderer and optional capability cache."""
        self.table_renderer = table_renderer
        self.disco_cache = disco_cache

    def _apply_text_styling(self, text: str) -> str:
        """Apply XEP-0393 styling markers (bold, italic, code)."""
        import re
        
        result = text
        
        result = re.sub(r'\*\*(.+?)\*\*', r'*\1*', result)
        
        result = re.sub(r'(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)', r'*\1*', result)
        
        result = re.sub(r'_(.+?)_', r'_\1_', result)
        
        result = re.sub(r'`([^`]+)`', r'`\1`', result)
        
        result = re.sub(r'^(#{1,6})\s+(.+)$', lambda m: f"\n{m.group(2)}\n{'=' * len(m.group(2))}", result, flags=re.MULTILINE)
        
        return result

    def _escape_code_content(self, code: str) -> str:
        """Escape code content and wrap in fenced code block."""
        fence_length = self.table_renderer._determine_fence_length(code)
        fence = '`' * fence_length
        return f"{fence}\n{code}\n{fence}"

    def format_message(
        self,
        model: MessageModel,
        recipient_jid: Optional[str] = None
    ) -> str:
        """Convert MessageModel to XEP-0393 formatted text."""
        styled_text = self._apply_text_styling(model.plain_body)
        
        parts = [styled_text]
        
        for table in model.tables:
            rendered_table = self.table_renderer.render_table(table)
            if rendered_table:
                parts.append(rendered_table)

        return '\n\n'.join(parts)

    def format_xhtml_body(self, model: MessageModel) -> Optional[str]:
        """Return XHTML-IM body fragment for header-aware rendering."""
        lines = str(model.plain_body or "").splitlines()
        if not lines:
            return None
        html_parts: list[str] = []
        has_header = False
        index = 0
        while index < len(lines):
            line = lines[index]
            stripped = line.strip()
            if not stripped:
                index += 1
                continue
            if (
                index + 1 < len(lines)
                and _is_setext_underline(lines[index + 1])
            ):
                html_parts.append(
                    f"<p><strong>{_inline_markdown_to_xhtml(stripped)}</strong></p>"
                )
                has_header = True
                index += 2
                continue
            atx_match = ATX_HEADER_PATTERN.match(line)
            if atx_match is not None:
                html_parts.append(
                    f"<p><strong>{_inline_markdown_to_xhtml(atx_match.group(1).strip())}</strong></p>"
                )
                has_header = True
                index += 1
                continue
            html_parts.append(f"<p>{_inline_markdown_to_xhtml(line)}</p>")
            index += 1
        if not has_header or not html_parts:
            return None
        return "".join(html_parts)

    def format_plain_body_for_xhtml_fallback(self, model: MessageModel) -> str:
        """Normalize markdown to plain text when XHTML payload is attached."""
        lines = str(model.plain_body or "").splitlines()
        normalized_lines: list[str] = []
        index = 0
        while index < len(lines):
            line = lines[index]
            stripped = line.strip()
            if (
                stripped
                and index + 1 < len(lines)
                and _is_setext_underline(lines[index + 1])
            ):
                normalized_lines.append(_inline_markdown_to_plain(stripped))
                index += 2
                continue
            atx_match = ATX_HEADER_PATTERN.match(line)
            if atx_match is not None:
                normalized_lines.append(_inline_markdown_to_plain(atx_match.group(1).strip()))
                index += 1
                continue
            bullet_match = BULLET_LINE_PATTERN.match(line)
            if bullet_match is not None:
                indent, content = bullet_match.groups()
                plain_bullet = _inline_markdown_to_plain(content)
                normalized_lines.append(f"{indent}- {plain_bullet}")
                index += 1
                continue
            normalized_lines.append(_inline_markdown_to_plain(line))
            index += 1
        plain_text = "\n".join(normalized_lines).strip()
        parts = [plain_text] if plain_text else []
        for table in model.tables:
            rendered_table = self.table_renderer.render_table(table)
            if rendered_table:
                parts.append(rendered_table)
        return "\n\n".join(parts)


def extract_markdown_tables(markdown_text: str) -> MessageModel:
    """Parse pipe-markdown tables into structured tables and plain text."""
    lines = str(markdown_text or "").splitlines()
    plain_lines: list[str] = []
    tables: list[TableStructure] = []
    index = 0
    in_code_block = False

    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if _is_code_fence_line(stripped):
            in_code_block = not in_code_block
            plain_lines.append(line)
            index += 1
            continue

        if not in_code_block and index + 1 < len(lines):
            header_cells = _parse_markdown_table_row(lines[index])
            separator_cells = _parse_markdown_table_row(lines[index + 1])
            if _is_markdown_table_header(header_cells, separator_cells):
                row_index = index + 2
                rows: list[list[str]] = []
                while row_index < len(lines):
                    candidate_cells = _parse_markdown_table_row(lines[row_index])
                    if not _is_table_row_for_header(candidate_cells, len(header_cells)):
                        break
                    rows.append(candidate_cells)
                    row_index += 1
                tables.append(TableStructure(headers=header_cells, rows=rows))
                index = row_index
                continue

        plain_lines.append(line)
        index += 1

    plain_body = "\n".join(plain_lines).strip()
    return MessageModel(plain_body=plain_body, tables=tables)


def _is_code_fence_line(stripped_line: str) -> bool:
    for marker in CODE_FENCE_MARKERS:
        if stripped_line.startswith(marker):
            return True
    return False


def _parse_markdown_table_row(line: str) -> list[str]:
    candidate = str(line or "").strip()
    if "|" not in candidate:
        return []
    if candidate.startswith("|"):
        candidate = candidate[1:]
    if candidate.endswith("|"):
        candidate = candidate[:-1]
    cells = [cell.strip() for cell in candidate.split("|")]
    return cells


def _is_markdown_table_header(header_cells: list[str], separator_cells: list[str]) -> bool:
    if len(header_cells) < MIN_TABLE_COLUMN_COUNT:
        return False
    if len(separator_cells) != len(header_cells):
        return False
    if any(not cell for cell in header_cells):
        return False
    return all(_is_separator_cell(cell) for cell in separator_cells)


def _is_separator_cell(value: str) -> bool:
    candidate = value.strip()
    if not candidate:
        return False
    if candidate.startswith(":"):
        candidate = candidate[1:]
    if candidate.endswith(":"):
        candidate = candidate[:-1]
    if len(candidate) < MIN_SEPARATOR_DASH_COUNT:
        return False
    return bool(re.fullmatch(r"-+", candidate))


def _is_table_row_for_header(cells: list[str], header_length: int) -> bool:
    return bool(cells) and len(cells) == header_length


def _is_setext_underline(line: str) -> bool:
    return bool(SETEXT_UNDERLINE_PATTERN.fullmatch(str(line or "").strip()))


def _inline_markdown_to_xhtml(text: str) -> str:
    escaped = html.escape(str(text or ""))
    escaped = BOLD_MARKDOWN_PATTERN.sub(r"<strong>\1</strong>", escaped)
    escaped = ITALIC_MARKDOWN_PATTERN.sub(r"<em>\1</em>", escaped)
    escaped = CODE_SPAN_PATTERN.sub(r"<code>\1</code>", escaped)
    return escaped


def _inline_markdown_to_plain(text: str) -> str:
    plain = str(text or "")
    plain = BOLD_MARKDOWN_PATTERN.sub(r"\1", plain)
    plain = ITALIC_MARKDOWN_PATTERN.sub(r"\1", plain)
    plain = CODE_SPAN_PATTERN.sub(r"\1", plain)
    return plain
