"""HTML parsing utilities."""

import re
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin


class HTMLStripper(HTMLParser):
    """Parse HTML and extract text content and links."""

    def __init__(self, base_url: Optional[str] = None) -> None:
        super().__init__()
        self.reset()
        self.strict = False
        self.convert_charrefs = True
        self.text: List[str] = []
        self.links: List[Dict[str, str]] = []
        self.ignore = False
        self.current_href: Optional[str] = None
        self.base_url = base_url

    def handle_starttag(self, tag: str, attrs: List[Any]) -> None:
        if tag in ("script", "style"):
            self.ignore = True
        elif tag == "a":
            for k, v in attrs:
                if k == "href":
                    self.current_href = v
                    break

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style"):
            self.ignore = False
        elif tag == "a":
            self.current_href = None

    def handle_data(self, data: str) -> None:
        if not self.ignore:
            text = data.strip()
            if text:
                self.text.append(data)
                if self.current_href:
                    href = self.current_href
                    if self.base_url:
                        href = urljoin(self.base_url, href)
                    self.links.append({"text": text, "href": href})

    def get_data(self) -> str:
        return "".join(self.text).strip()

    def get_links(self) -> List[Dict[str, str]]:
        return self.links


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
