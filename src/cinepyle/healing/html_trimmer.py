"""HTML trimmer for reducing page size before sending to LLM.

A typical Korean cinema site page is 200-500KB of rendered HTML.
The LLM only needs the structural elements to generate extraction
strategies. This module strips scripts, styles, and noise to get
the HTML down to ~30KB.
"""

import re

from bs4 import BeautifulSoup, Comment

# Tags that never contain useful visible content
REMOVE_TAGS = {"script", "style", "noscript", "svg", "path", "link", "meta"}

# CSS-module hash class pattern (e.g. css-1a2b3c, sc-dkzDqf, styled-abc123)
HASH_CLASS_RE = re.compile(r"^(css|sc|styled|emotion)-[a-zA-Z0-9]{4,}$")

MAX_CHARS = 30_000


def trim_html(raw_html: str) -> str:
    """Reduce page HTML to essential structure for LLM analysis.

    Removes scripts, styles, non-semantic attributes, and empty
    elements. Keeps semantic class names (like 'imax', 'title',
    'movie') that help the LLM understand the page structure.
    """
    soup = BeautifulSoup(raw_html, "lxml")

    # Remove HTML comments
    for comment in soup.find_all(string=lambda t: isinstance(t, Comment)):
        comment.extract()

    # Remove non-content tags entirely
    for tag_name in REMOVE_TAGS:
        for tag in soup.find_all(tag_name):
            tag.decompose()

    # Clean attributes on remaining tags
    for tag in soup.find_all(True):
        attrs_to_remove = []
        for attr in list(tag.attrs):
            if attr.startswith("data-") or attr == "style":
                attrs_to_remove.append(attr)
            elif attr == "class":
                # Keep semantic classes, remove hash-based ones
                classes = tag.get("class", [])
                semantic = [c for c in classes if not HASH_CLASS_RE.match(c)]
                if semantic:
                    tag["class"] = semantic
                else:
                    attrs_to_remove.append("class")
        for attr in attrs_to_remove:
            del tag[attr]

    # Remove empty elements (no text, no meaningful children)
    for tag in soup.find_all(True):
        if not tag.get_text(strip=True) and not tag.find_all(
            ["img", "input", "button", "a"]
        ):
            tag.decompose()

    result = str(soup)

    # Collapse whitespace
    result = re.sub(r"\s+", " ", result)

    # Truncate as last resort
    if len(result) > MAX_CHARS:
        result = result[:MAX_CHARS]

    return result
