"""XMPP message formatting with XEP-0393 styling and ASCII table rendering."""

import unicodedata
from dataclasses import dataclass, field
from typing import List, Optional

MAX_FENCE_LENGTH = 10


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
