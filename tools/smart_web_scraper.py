from typing import Type, Optional
import re
import urllib.parse
from crewai.tools import BaseTool
from pydantic import BaseModel, Field
from bs4 import BeautifulSoup
import requests

class SmartWebScraperInput(BaseModel):
    """Input schema for SmartWebScraper."""
    url: str = Field(..., description="The URL of the webpage or PDF to scrape.")
    topic: Optional[str] = Field(None, description="The topic to search for or extract relevant information about from the page content.")

class SmartWebScraper(BaseTool):
    name: str = "Smart Web Scraper"
    description: str = (
        "Scrapes a webpage or PDF URL and extracts clean, readable text content, "
        "removing HTML boilerplate such as navigation menus, footers, headers, sidebars, and ads. "
        "If a topic is provided, it filters the text to return only sections relevant to the topic to save tokens."
    )
    args_schema: Type[BaseModel] = SmartWebScraperInput

    def _run(self, url: str, topic: Optional[str] = None) -> str:
        url = url.strip()
        if not (url.startswith("http://") or url.startswith("https://")):
            # Try to fix simple missing scheme
            url = "https://" + url

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }

        try:
            # Check headers first or download with timeout
            response = requests.get(url, headers=headers, timeout=15)
            response.raise_for_status()
        except Exception as e:
            return f"Error: Failed to fetch the URL {url}. Reason: {str(e)}"

        # Detect PDF content
        content_type = response.headers.get("Content-Type", "").lower()
        is_pdf = "application/pdf" in content_type or url.lower().endswith(".pdf")

        extracted_text = ""
        if is_pdf:
            extracted_text = self._extract_pdf(response.content, url)
        else:
            extracted_text = self._extract_html(response.content)

        if not extracted_text.strip():
            return f"Error: No text content could be extracted from {url}."

        # Apply relevance filtering if topic is provided
        filtered_text = extracted_text
        was_filtered = False
        
        if topic and topic.strip():
            filtered_text, was_filtered = self._filter_by_relevance(extracted_text, topic)

        # Apply hard truncation to protect context window (limit to 4500 chars, ~1000 tokens)
        max_chars = 4500
        was_truncated = False
        if len(filtered_text) > max_chars:
            filtered_text = filtered_text[:max_chars]
            was_truncated = True

        # Construct final output
        output = [f"=== Scraped Content from: {url} ==="]
        if was_filtered:
            output.append(f"[Relevance Filter: Showing sections matching topic '{topic}']")
        if was_truncated:
            output.append("[Truncation Notice: Content truncated to protect context window limits]")
        output.append("=========================================\n")
        output.append(filtered_text)
        if was_truncated:
            output.append("\n... [CONTENT TRUNCATED. Relevant sections shown above.]")

        return "\n".join(output)

    def _extract_pdf(self, content: bytes, url: str) -> str:
        """Helper to extract text from PDF content using PyMuPDF or pdfplumber."""
        # Try PyMuPDF (fitz)
        try:
            import fitz
            doc = fitz.open(stream=content, filetype="pdf")
            text_parts = []
            for i, page in enumerate(doc):
                page_text = page.get_text()
                if page_text.strip():
                    text_parts.append(f"--- PDF Page {i+1} ---\n{page_text}")
            return "\n\n".join(text_parts)
        except Exception as e_fitz:
            # Fallback to pdfplumber
            try:
                import pdfplumber
                import io
                text_parts = []
                with pdfplumber.open(io.BytesIO(content)) as pdf:
                    for i, page in enumerate(pdf.pages):
                        page_text = page.extract_text()
                        if page_text and page_text.strip():
                            text_parts.append(f"--- PDF Page {i+1} ---\n{page_text}")
                return "\n\n".join(text_parts)
            except Exception as e_pdfplumber:
                return f"Error extracting PDF text: PyMuPDF error: {str(e_fitz)}, pdfplumber error: {str(e_pdfplumber)}"

    def _extract_html(self, content: bytes) -> str:
        """Helper to clean HTML and extract high-density readable text blocks."""
        soup = BeautifulSoup(content, "html.parser")

        # 1. Decompose completely irrelevant layout/interactive tags
        irrelevant_tags = [
            "script", "style", "nav", "footer", "header", "aside", 
            "form", "iframe", "noscript", "svg", "button", "select", 
            "textarea", "dialog", "canvas"
        ]
        for tag in soup(irrelevant_tags):
            tag.decompose()

        # 2. Decompose elements that match typical boilerplate patterns in class or id
        boilerplate_pattern = re.compile(
            r'footer|header|sidebar|nav|menu|cookie|banner|promo|ads|sharing|social|popup|widget|modal', 
            re.I
        )
        for elem in soup.find_all(attrs={"class": boilerplate_pattern}):
            # Let's verify we don't accidentally remove core content if class is "main-header"
            class_name = " ".join(elem.get("class", []))
            if not re.search(r'main|content|article|body', class_name, re.I):
                elem.decompose()
        for elem in soup.find_all(attrs={"id": boilerplate_pattern}):
            elem_id = elem.get("id", "")
            if not re.search(r'main|content|article|body', elem_id, re.I):
                elem.decompose()

        # 3. Extract text sequentially preserving structure
        content_blocks = []
        for elem in soup.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p', 'li', 'pre', 'code']):
            # Ensure the element has not been decomposed (parent is not None)
            if not elem.parent:
                continue
                
            text = elem.get_text(strip=True)
            if not text:
                continue
            
            # Simple heuristic: ignore extremely short single-word paragraphs or menu leftovers
            if elem.name == 'p' and len(text.split()) < 3 and not text.endswith(('.', '?', '!')):
                continue

            if elem.name.startswith('h'):
                try:
                    level = int(elem.name[1])
                except ValueError:
                    level = 2
                content_blocks.append(f"\n{'#' * level} {text}\n")
            elif elem.name == 'li':
                content_blocks.append(f"- {text}")
            elif elem.name in ['pre', 'code']:
                # Wrap pre/code blocks in backticks
                content_blocks.append(f"\n```\n{text}\n```\n")
            else:
                content_blocks.append(text)

        return "\n".join(content_blocks)

    def _filter_by_relevance(self, text: str, topic: str) -> tuple[str, bool]:
        """Helper to extract sections of the text that match keywords in the topic."""
        # 1. Parse topic into unique keywords
        stop_words = {
            'the', 'a', 'an', 'and', 'or', 'but', 'is', 'are', 'was', 'were', 'in', 'on', 'at', 
            'to', 'for', 'of', 'with', 'by', 'about', 'as', 'into', 'through', 'during', 'including', 
            'until', 'against', 'among', 'throughout', 'despite', 'towards', 'upon', 'concerning', 
            'from', 'this', 'that', 'these', 'those', 'it', 'its', 'they', 'them', 'their', 'how', 
            'what', 'why', 'who', 'where', 'when', 'which'
        }
        
        # Clean topic: remove punctuation and lower case
        clean_topic = re.sub(r'[^\w\s]', ' ', topic.lower())
        keywords = [word for word in clean_topic.split() if word not in stop_words and len(word) > 2]
        
        if not keywords:
            return text, False  # No valid keywords, return raw text

        # 2. Split text into paragraphs/sections
        paragraphs = [p.strip() for p in text.split('\n\n') if p.strip()]
        
        # If document is small (e.g. less than 10 paragraphs or 3000 chars), don't filter to avoid loss of context
        if len(text) < 3000 or len(paragraphs) <= 10:
            return text, False

        # 3. Score paragraphs based on keyword frequency
        scored_paragraphs = []
        for idx, p in enumerate(paragraphs):
            score = 0
            p_lower = p.lower()
            for kw in keywords:
                # Add score weighted by matches
                score += p_lower.count(kw)
            scored_paragraphs.append((score, idx, p))

        # 4. Filter and select top-N scoring paragraphs
        # Sort by score descending
        sorted_by_score = sorted(scored_paragraphs, key=lambda x: x[0], reverse=True)
        
        # Filter paragraphs that have score > 0
        matching_paragraphs = [item for item in sorted_by_score if item[0] > 0]
        
        if not matching_paragraphs:
            # No exact matches, fallback to returning the first 8 paragraphs (which usually contain the intro/abstract)
            return "\n\n".join(paragraphs[:8]), True

        # Keep only the top 6 highest-scoring paragraphs
        top_matching = matching_paragraphs[:6]
        selected_indices = set(item[1] for item in top_matching)
        
        # Include adjacent headings preceding any selected paragraphs to maintain structure
        for idx in list(selected_indices):
            if idx > 0 and paragraphs[idx - 1].startswith('#'):
                selected_indices.add(idx - 1)

        # Preserve original document order of selected paragraphs
        selected_paragraphs = [paragraphs[i] for i in sorted(selected_indices)]
        
        # If the filtering didn't reduce the content much (e.g. kept > 90% of paragraphs), report as unfiltered
        if len(selected_paragraphs) >= len(paragraphs) * 0.9:
            return text, False

        return "\n\n".join(selected_paragraphs), True
