import pytest
from asky.html import HTMLStripper, strip_tags, strip_think_tags


def test_html_stripper_basic():
    html = "<html><body><p>Hello world</p></body></html>"
    stripper = HTMLStripper()
    stripper.feed(html)
    assert stripper.get_data() == "Hello world"


def test_html_stripper_with_scripts_and_styles():
    html = """
    <html>
        <head>
            <style>body { color: red; }</style>
            <script>console.log('ignore me');</script>
        </head>
        <body>
            <p>Content</p>
        </body>
    </html>
    """
    stripper = HTMLStripper()
    stripper.feed(html)
    assert stripper.get_data() == "Content"


def test_html_stripper_links():
    html = '<p>Check out <a href="https://example.com">Example</a>.</p>'
    stripper = HTMLStripper()
    stripper.feed(html)
    data = stripper.get_data()
    links = stripper.get_links()

    assert "Check out Example." in data
    assert len(links) == 1
    assert links[0] == {"text": "Example", "href": "https://example.com"}


def test_strip_tags_function():
    assert strip_tags("<p>Test</p>") == "Test"
    assert strip_tags("No tags") == "No tags"
    assert strip_tags("<script>var x=1;</script>Visible") == "Visible"


def test_strip_think_tags():
    text = "Here is <think>inner thought</think> the answer."
    assert strip_think_tags(text) == "Here is  the answer."

    text_multiline = """Start
    <think>
    Thinking...
    </think>
    End"""
    assert (
        strip_think_tags(text_multiline).replace("\n", "").replace(" ", "")
        == "StartEnd"
    )


def test_strip_think_tags_no_tags():
    text = "Just plain text."
    assert strip_think_tags(text) == text


def test_html_stripper_links_with_hashes_and_duplicates():
    html = """
    <a href="http://example.com/page#section1">Link 1</a>
    <a href="http://example.com/page#section2">Link 1 Again</a>
    <a href="http://example.com/page">Link 1 Plain</a>
    <a href="#local">Local Anchor</a>
    """
    stripper = HTMLStripper(base_url="http://example.com")
    stripper.feed(html)
    links = stripper.get_links()

    # Should maximize unique URLs (stripping fragments)
    assert len(links) == 2
    assert links[0]["href"] == "http://example.com/page"
    assert links[0]["text"] == "Link 1"
    assert links[1]["href"] == "http://example.com"


def test_html_stripper_excluded_link_container_tags():
    html = """
    <header><a href="https://example.com/signin">Sign in</a></header>
    <main><a href="https://example.com/world">World</a></main>
    <footer><a href="https://example.com/privacy">Privacy</a></footer>
    """
    stripper = HTMLStripper(
        base_url="https://example.com",
        excluded_link_container_tags={"header", "footer"},
    )
    stripper.feed(html)
    links = stripper.get_links()

    assert len(links) == 1
    assert links[0]["href"] == "https://example.com/world"


def test_html_stripper_section_tracking_headings():
    html = """
    <h2>Top Stories</h2>
    <a href="https://example.com/1">Article One</a>
    <a href="https://example.com/2">Article Two</a>
    <h2>World News</h2>
    <a href="https://example.com/3">Article Three</a>
    """
    stripper = HTMLStripper(base_url="https://example.com")
    stripper.feed(html)
    links = stripper.get_links_with_sections()

    assert len(links) == 3
    assert links[0] == {"text": "Article One", "href": "https://example.com/1", "section": "Top Stories"}
    assert links[1] == {"text": "Article Two", "href": "https://example.com/2", "section": "Top Stories"}
    assert links[2] == {"text": "Article Three", "href": "https://example.com/3", "section": "World News"}


def test_html_stripper_section_tracking_zones():
    html = """
    <nav><a href="https://example.com/nav">Nav Link</a></nav>
    <h2>Main Content</h2>
    <a href="https://example.com/article">Article</a>
    <aside><a href="https://example.com/sidebar">Sidebar Link</a></aside>
    <footer><a href="https://example.com/footer">Footer Link</a></footer>
    """
    stripper = HTMLStripper(base_url="https://example.com")
    stripper.feed(html)
    links = stripper.get_links_with_sections()

    assert len(links) == 4
    assert links[0]["section"] == "Navigation"
    assert links[1]["section"] == "Main Content"
    assert links[2]["section"] == "Sidebar"
    assert links[3]["section"] == "Footer"


def test_html_stripper_section_tracking_no_context():
    html = """
    <a href="https://example.com/1">Early Link</a>
    <h2>After Heading</h2>
    <a href="https://example.com/2">Heading Link</a>
    """
    stripper = HTMLStripper(base_url="https://example.com")
    stripper.feed(html)
    links = stripper.get_links_with_sections()

    assert links[0]["section"] == ""
    assert links[1]["section"] == "After Heading"


def test_html_stripper_heading_links_excluded_from_sectioned():
    """Links inside heading tags should not appear in sectioned list."""
    html = """
    <h2><a href="https://example.com/nav-link">Section Header as Link</a></h2>
    <a href="https://example.com/content">Content Link</a>
    """
    stripper = HTMLStripper(base_url="https://example.com")
    stripper.feed(html)
    all_links = stripper.get_links()
    sectioned = stripper.get_links_with_sections()

    # get_links() includes heading links, get_links_with_sections() excludes them
    assert any(l["href"] == "https://example.com/nav-link" for l in all_links)
    assert not any(l["href"] == "https://example.com/nav-link" for l in sectioned)
    assert len(sectioned) == 1
    assert sectioned[0]["href"] == "https://example.com/content"
