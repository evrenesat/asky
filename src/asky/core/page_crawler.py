"""Page Crawler tool implementation for deep dive mode."""

import logging
from typing import Any, Dict, List, Optional
from asky.tools import execute_get_url_details, execute_get_url_content
from asky import summarization
from asky.core.api_client import get_llm_msg, UsageTracker
from asky.config import SUMMARIZE_ANSWER_PROMPT_TEMPLATE, ANSWER_SUMMARY_MAX_CHARS

logger = logging.getLogger(__name__)


class PageCrawlerState:
    """Manages persistent URL-to-ID mapping for a conversation."""

    def __init__(self):
        self.url_mapping: Dict[int, str] = {}  # id -> full_url
        self._next_id: int = 1

    def add_links(self, links: List[Dict[str, str]]) -> List[Dict[str, Any]]:
        """Add links to the mapping and return simplified representation."""
        simplified_links = []
        for link in links:
            url = link.get("href")
            text = link.get("text")

            if not url or not text:
                continue

            # Check if URL already mapped to avoid duplicates
            existing_id = None
            for mid, murl in self.url_mapping.items():
                if murl == url:
                    existing_id = mid
                    break

            if existing_id:
                link_id = existing_id
            else:
                link_id = self._next_id
                self.url_mapping[link_id] = url
                self._next_id += 1

            simplified_links.append({"id": link_id, "text": text})

        return simplified_links

    def get_urls_by_ids(self, ids: List[int]) -> List[str]:
        """Resolve a list of IDs to their full URLs."""
        urls = []
        for link_id in ids:
            url = self.url_mapping.get(link_id)
            if url:
                urls.append(url)
            else:
                logger.warning(f"ID {link_id} not found in mapping.")
        return urls


def execute_page_crawler(
    args: Dict[str, Any],
    crawler_state: PageCrawlerState,
    summarize: bool = False,
    summarization_tracker: Optional[UsageTracker] = None,
) -> Dict[str, Any]:
    """Execute the page_crawler tool.

    Accepts either 'url' OR 'link_ids'.
    """
    url = args.get("url")
    link_ids_str = args.get("link_ids")

    # Mutual exclusion check
    if url and link_ids_str:
        return {
            "error": "Invalid arguments: Provide either 'url' OR 'link_ids', not both."
        }

    if not url and not link_ids_str:
        return {"error": "Invalid arguments: Provide either 'url' OR 'link_ids'."}

    # Case 1: Fetch initial page and build mapping
    if url:
        logger.info(f"PageCrawler: Fetching details for {url}")
        # Reuse existing logic to get content + raw links
        details = execute_get_url_details({"url": url})

        if "error" in details:
            return details

        # Update state with new links
        raw_links = details.get("links", [])
        simplified_links = crawler_state.add_links(raw_links)

        # Format links for the model
        # 1:about, 2:contact
        links_str = ", ".join([f"{l['id']}:{l['text']}" for l in simplified_links])

        return {
            "content": details.get("content"),
            "links": links_str,
            "system_note": "To read more pages, use page_crawler(link_ids='1,2,3...'). Do not use URLs directly.",
        }

    # Case 2: Follow existing links by ID
    if link_ids_str:
        try:
            # Parse IDs "1, 2, 3" -> [1, 2, 3]
            # Handle potential string or int input
            if isinstance(link_ids_str, int):
                ids = [link_ids_str]
            else:
                ids = [
                    int(x.strip())
                    for x in str(link_ids_str).split(",")
                    if x.strip().isdigit()
                ]

            if not ids:
                return {"error": "No valid integer IDs provided."}

            urls = crawler_state.get_urls_by_ids(ids)
            if not urls:
                return {"error": "No valid URLs found for the provided IDs."}

            logger.info(f"PageCrawler: Fetching content for IDs {ids} -> {urls}")

            # Reuse existing batched fetch
            results = execute_get_url_content({"urls": urls})

            # Apply summarization if requested
            if summarize:
                for r_url, content in results.items():
                    if not content.startswith("Error:"):
                        results[r_url] = (
                            f"Summary of {r_url}:\n"
                            + summarization._summarize_content(
                                content=content,
                                prompt_template=SUMMARIZE_ANSWER_PROMPT_TEMPLATE,
                                max_output_chars=ANSWER_SUMMARY_MAX_CHARS,
                                get_llm_msg_func=get_llm_msg,
                                usage_tracker=summarization_tracker,
                            )
                        )
            return results

        except Exception as e:
            return {"error": f"Failed to process link_ids: {str(e)}"}

    return {"error": "Unexpected error."}
