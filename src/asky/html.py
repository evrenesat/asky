"""HTML parsing utilities."""

import re
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

_HEADING_TAGS = frozenset({"h1", "h2", "h3", "h4", "h5", "h6"})
_ZONE_TAGS = frozenset({"nav", "footer", "header", "aside"})
_ZONE_LABELS = {"nav": "Navigation", "footer": "Footer", "header": "Header", "aside": "Sidebar"}


class HTMLStripper(HTMLParser):
    """Parse HTML and extract text content and links."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        excluded_link_container_tags: Optional[set[str]] = None,
    ) -> None:
        super().__init__()
        self.reset()
        self.strict = False
        self.convert_charrefs = True
        self.text: List[str] = []
        self.links: List[Dict[str, str]] = []
        self.ignore_depth = 0
        self.current_href: Optional[str] = None
        self.base_url = base_url
        self.excluded_link_container_tags = {
            tag.lower() for tag in (excluded_link_container_tags or set())
        }
        self.excluded_link_depth = 0
        # Section tracking for get_links_with_sections()
        self._current_heading: str = ""
        self._in_heading: bool = False
        self._heading_buffer: List[str] = []
        self._zone_depths: Dict[str, int] = {"nav": 0, "footer": 0, "header": 0, "aside": 0}
        self._links_sectioned: List[Dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs: List[Any]) -> None:
        tag = tag.lower()
        if tag in ("script", "style"):
            self.ignore_depth += 1
            return
        if tag in _HEADING_TAGS:
            self._in_heading = True
            self._heading_buffer = []
            return
        # excluded_link_container_tags takes priority over zone tracking
        if tag in self.excluded_link_container_tags:
            self.excluded_link_depth += 1
            return
        if tag in _ZONE_TAGS:
            self._zone_depths[tag] += 1
            return
        if tag == "a":
            if self.excluded_link_depth > 0:
                self.current_href = None
                return
            for k, v in attrs:
                if k == "href":
                    self.current_href = v
                    break

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in ("script", "style"):
            if self.ignore_depth > 0:
                self.ignore_depth -= 1
        elif tag in _HEADING_TAGS:
            if self._in_heading:
                self._current_heading = " ".join(self._heading_buffer).strip()
                self._in_heading = False
        elif tag in self.excluded_link_container_tags:
            if self.excluded_link_depth > 0:
                self.excluded_link_depth -= 1
        elif tag in _ZONE_TAGS:
            if self._zone_depths.get(tag, 0) > 0:
                self._zone_depths[tag] -= 1
        elif tag == "a":
            self.current_href = None

    def handle_data(self, data: str) -> None:
        if self.ignore_depth == 0:
            text = data.strip()
            if text:
                self.text.append(data)
                if self._in_heading:
                    self._heading_buffer.append(text)
                if self.current_href and self.excluded_link_depth == 0:
                    href = self.current_href
                    if self.base_url:
                        href = urljoin(self.base_url, href)
                    self.links.append({"text": text, "href": href})
                    if not self._in_heading:
                        self._links_sectioned.append({
                            "text": text,
                            "href": href,
                            "section": self._current_section_label(),
                        })

    def _current_section_label(self) -> str:
        """Return the current structural zone name or heading text."""
        for zone in ("footer", "aside", "nav", "header"):
            if self._zone_depths.get(zone, 0) > 0:
                return _ZONE_LABELS[zone]
        return self._current_heading

    def get_data(self) -> str:
        return "".join(self.text).strip()

    def get_links(self) -> List[Dict[str, str]]:
        seen_urls = set()
        unique_links = []
        for link in self.links:
            href = link["href"]
            # Remove fragment
            if "#" in href:
                href = href.split("#")[0]

            # Skip empty URLs or duplicates
            if href and href not in seen_urls:
                seen_urls.add(href)
                unique_links.append({"text": link["text"], "href": href})

        return unique_links

    def get_links_with_sections(self) -> List[Dict[str, str]]:
        """Return deduplicated links with their section/zone labels.

        Each entry has keys: text, href, section. The section is either
        the last heading text seen before the link (outside zones), or
        the zone name (Navigation, Footer, Header, Sidebar), or empty
        string if no context was available.
        """
        seen_urls = set()
        unique_links = []
        for link in self._links_sectioned:
            href = link["href"]
            if "#" in href:
                href = href.split("#")[0]
            if href and href not in seen_urls:
                seen_urls.add(href)
                unique_links.append({"text": link["text"], "href": href, "section": link["section"]})
        return unique_links


def strip_tags(html: str) -> str:
    """Strip HTML tags from text and return plain text content."""
    s = HTMLStripper()
    s.feed(html)
    return s.get_data()


def strip_think_tags(text: str) -> str:
    """Remove <think>...</think> blocks from LLM output."""
    if not text:
        return ""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
