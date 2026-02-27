"""Tests for XMPP message formatting with XEP-0393 styling and ASCII tables."""

import pytest
from hypothesis import given, strategies as st, settings

from asky.plugins.xmpp_daemon.xmpp_formatting import (
    MessageModel,
    TableStructure,
    ASCIITableRenderer,
    MessageFormatter,
    extract_markdown_tables,
)


@settings(max_examples=100)
@given(st.text())
def test_message_model_creation(text):
    """MessageModel can be created with any text."""
    model = MessageModel(plain_body=text)
    assert model.plain_body == text
    assert model.tables == []


@settings(max_examples=100)
@given(
    st.lists(st.text(), min_size=1, max_size=10),
    st.lists(st.lists(st.text(), min_size=1, max_size=10), min_size=0, max_size=20)
)
def test_table_structure_creation(headers, rows):
    """TableStructure can be created with headers and rows."""
    table = TableStructure(headers=headers, rows=rows)
    assert table.headers == headers
    assert table.rows == rows


# Feature: xmpp-formatting, Property 3: Column Width Calculation
@settings(max_examples=100)
@given(
    st.lists(st.text(min_size=0, max_size=50), min_size=1, max_size=10).flatmap(
        lambda headers: st.tuples(
            st.just(headers),
            st.lists(
                st.lists(st.text(min_size=0, max_size=50), min_size=len(headers), max_size=len(headers)),
                min_size=1,
                max_size=20
            )
        )
    )
)
def test_property_column_width_calculation(table_data):
    """For any table, column widths should equal max content width per column."""
    headers, rows = table_data
    table = TableStructure(headers=headers, rows=rows)
    renderer = ASCIITableRenderer()
    
    actual_widths = renderer._calculate_column_widths(table)
    
    for col_idx in range(len(headers)):
        expected_width = renderer._display_width(headers[col_idx])
        for row in rows:
            if col_idx < len(row):
                expected_width = max(expected_width, renderer._display_width(row[col_idx]))
        
        assert actual_widths[col_idx] == expected_width



# Feature: xmpp-formatting, Property 13: Fence Length Selection
@settings(max_examples=100)
@given(st.text(min_size=0, max_size=200))
def test_property_fence_length_selection(content):
    """For any code content, chosen fence length should not appear in content."""
    renderer = ASCIITableRenderer()
    fence_length = renderer._determine_fence_length(content)
    
    assert 3 <= fence_length <= 10
    
    if fence_length < 10:
        fence = '`' * fence_length
        assert fence not in content



# Feature: xmpp-formatting, Property 4: Table Structure Completeness
@settings(max_examples=100)
@given(
    st.lists(st.text(min_size=1, max_size=20).filter(lambda x: '\n' not in x and '\r' not in x and x.strip() != ''), min_size=1, max_size=5).flatmap(
        lambda headers: st.tuples(
            st.just(headers),
            st.lists(
                st.lists(st.text(min_size=0, max_size=20).filter(lambda x: '\n' not in x and '\r' not in x), min_size=len(headers), max_size=len(headers)),
                min_size=0,
                max_size=10
            )
        )
    )
)
def test_property_table_structure_completeness(table_data):
    """For any table, output should contain header row, separator, and data rows."""
    headers, rows = table_data
    table = TableStructure(headers=headers, rows=rows)
    renderer = ASCIITableRenderer()
    
    result = renderer.render_table(table)
    lines = [line for line in result.strip('`').strip().split('\n') if line]
    
    assert len(lines) >= 2
    
    for header in headers:
        if header.strip():
            assert header in result
    
    assert '-' in lines[1]



# Feature: xmpp-formatting, Property 5: Table Code Block Wrapping
@settings(max_examples=100)
@given(
    st.lists(st.text(min_size=1, max_size=20), min_size=1, max_size=5).flatmap(
        lambda headers: st.tuples(
            st.just(headers),
            st.lists(
                st.lists(st.text(min_size=0, max_size=20), min_size=len(headers), max_size=len(headers)),
                min_size=0,
                max_size=10
            )
        )
    )
)
def test_property_table_code_block_wrapping(table_data):
    """For any table, output should be wrapped in fenced code block."""
    headers, rows = table_data
    table = TableStructure(headers=headers, rows=rows)
    renderer = ASCIITableRenderer()
    
    result = renderer.render_table(table)
    
    assert result.startswith('```')
    assert result.endswith('```')
    
    lines = result.split('\n')
    assert lines[0].strip('`') == ''
    assert lines[-1].strip('`') == ''



# Feature: xmpp-formatting, Property 10: Table Row Consistency
@settings(max_examples=100)
@given(
    st.lists(st.text(min_size=1, max_size=20).filter(lambda x: '\n' not in x and '\r' not in x and '|' not in x and x.strip()), min_size=1, max_size=5).flatmap(
        lambda headers: st.tuples(
            st.just(headers),
            st.lists(
                st.lists(st.text(min_size=1, max_size=20).filter(lambda x: '\n' not in x and '\r' not in x and '|' not in x and x.strip()), min_size=len(headers), max_size=len(headers)),
                min_size=1,
                max_size=10
            )
        )
    )
)
def test_property_table_row_consistency(table_data):
    """For any table with N columns, all rows should have N cells with consistent widths."""
    headers, rows = table_data
    table = TableStructure(headers=headers, rows=rows)
    renderer = ASCIITableRenderer()
    
    result = renderer.render_table(table)
    lines = [line for line in result.strip('`').strip().split('\n') if line and '-' not in line]
    
    num_columns = len(headers)
    
    for line in lines:
        cells = line.split(' | ')
        assert len(cells) == num_columns



def test_empty_table_returns_empty_string():
    """Empty table (no headers) returns empty string."""
    table = TableStructure(headers=[], rows=[])
    renderer = ASCIITableRenderer()
    result = renderer.render_table(table)
    assert result == ""


def test_table_with_no_rows():
    """Table with headers but no rows renders header and separator only."""
    table = TableStructure(headers=["Name", "Age"], rows=[])
    renderer = ASCIITableRenderer()
    result = renderer.render_table(table)
    
    assert "Name" in result
    assert "Age" in result
    assert "---" in result
    assert result.startswith("```")
    assert result.endswith("```")


def test_single_cell_table():
    """Single cell table renders correctly."""
    table = TableStructure(headers=["Value"], rows=[["42"]])
    renderer = ASCIITableRenderer()
    result = renderer.render_table(table)
    
    assert "Value" in result
    assert "42" in result
    assert "---" in result


def test_table_with_unicode_cjk():
    """Table with CJK characters calculates width correctly."""
    table = TableStructure(headers=["日本語", "English"], rows=[["東京", "Tokyo"]])
    renderer = ASCIITableRenderer()
    result = renderer.render_table(table)
    
    assert "日本語" in result
    assert "東京" in result
    assert "Tokyo" in result


def test_table_with_backticks_in_cells():
    """Table with backticks in cells uses longer fence."""
    table = TableStructure(headers=["Code"], rows=[["`value`"], ["```block```"]])
    renderer = ASCIITableRenderer()
    result = renderer.render_table(table)
    
    assert "`value`" in result
    assert "```block```" in result
    assert result.startswith("````")



def test_markdown_to_xep0393_conversion():
    """Markdown formatting is converted to XEP-0393 styling."""
    renderer = ASCIITableRenderer()
    formatter = MessageFormatter(renderer)
    
    model = MessageModel(plain_body="This is **bold** and this is *italic* and `code`")
    result = formatter.format_message(model)
    
    assert "*bold*" in result
    assert "*italic*" in result
    assert "`code`" in result
    assert "**" not in result


def test_header_conversion():
    """Markdown headers are converted to underlined text."""
    renderer = ASCIITableRenderer()
    formatter = MessageFormatter(renderer)
    
    model = MessageModel(plain_body="# Header")
    result = formatter.format_message(model)
    
    assert "Header" in result
    assert "======" in result


def test_extract_markdown_tables_parses_pipe_table():
    model = extract_markdown_tables(
        "Server status:\n\n| Service | Status |\n| --- | --- |\n| XMPP | Online |\n| DB | Maintenance |\n"
    )
    assert model.plain_body == "Server status:"
    assert len(model.tables) == 1
    assert model.tables[0].headers == ["Service", "Status"]
    assert model.tables[0].rows == [["XMPP", "Online"], ["DB", "Maintenance"]]


def test_extract_markdown_tables_parses_short_alignment_separator_table():
    model = extract_markdown_tables(
        "| ID | Name | Value |\n"
        "| :-- | :------- | :-------- |\n"
        "| 1 | Alpha | 100 |\n"
        "| 2 | Beta | 200 |\n"
    )
    assert model.plain_body == ""
    assert len(model.tables) == 1
    assert model.tables[0].headers == ["ID", "Name", "Value"]
    assert model.tables[0].rows == [["1", "Alpha", "100"], ["2", "Beta", "200"]]
