"""
REVIEW FILTER: Detect original research vs reviews
- Question 1: Classify paper type (original research vs review)
- Uses OpenAlex API (primary) and Crossref API (fallback)
- Filters out editorials, letters, meta-analyses, etc.
"""

import re
import logging
from typing import Dict, List, Optional, Tuple
from utils import create_http_session, make_api_request
from tqdm import tqdm

class ReviewFilter:
    """Filter for original research papers vs reviews/editorials"""
    
    def __init__(self, email: str):
        """Initialize with OpenAlex and Crossref API sessions"""
        self.email = email
        self.logger = logging.getLogger(__name__)
        
        # Create HTTP sessions for APIs
        user_agent = f"research_classifier/1.0 ({email})"
        self.openalex_session = create_http_session(user_agent, rate_limit=0.1)
        self.crossref_session = create_http_session(user_agent, rate_limit=0.02)  # 50 req/s
        
        # Excluded paper types
        self.EXCLUDED_TYPES = {
            "editorial", "erratum", "retraction", "paratext", "commentary", "letter"
        }

        self.EXCLUDED_CROSSREF_TYPES = {
            "book-chapter", "proceedings-article", "reference-entry", "component"
        }

        # Combined exclusion list
        self.EXCLUDED_TYPES_COMPLETE = self.EXCLUDED_TYPES | self.EXCLUDED_CROSSREF_TYPES | {"openalex_review", "crossref_review"}
        
        self.REVIEW_CONCEPTS = {
            "Meta-analysis", "Systematic review", "Literature review", "Review", 
            "Survey", "Commentary", "Editorial", "Scoping review", "Narrative review"
        }
        
        self.CONCEPT_THRESHOLD = 0.3

        # Review title patterns
        self.REVIEW_TITLE_PATTERNS = [
            r"\bsystematic\s+review\b",
            r"\bmeta-?analysis\b",
            r"\bliterature\s+review\b",
            r"\breview\s+of\s+the\b",
            r"\bscoping\s+review\b",
            r"\bnarrative\s+review\b",
            r"\bcritical\s+review\b",
            r"\bcomprehensive\s+review\b",
            r":\s*a\s+review\b",
            r"\breview\s*:\s*",
        ]
        
        self.review_regex = re.compile(
            "|".join(self.REVIEW_TITLE_PATTERNS), 
            re.IGNORECASE
        )
    
    def classify_paper_type(self, doi: str) -> Tuple[str, str, str]:
        """Classify paper type using APIs"""
        try:
            # Try OpenAlex first (primary method)
            paper_type, source, title = self._check_openalex(doi)
            if source != "none":
                return paper_type, source, title
            
            # Fallback to Crossref if OpenAlex fails
            paper_type, source, title = self._check_crossref(doi)
            if source != "none":
                return paper_type, source, title
            
            # Both failed - default to NOT FOUND
            self.logger.warning(f"No data found for {doi}, defaulting to NOT FOUND")
            return "NOT FOUND", "none", ""
            
        except Exception as e:
            self.logger.error(f"Classification failed for {doi}: {e}")
            return "NOT FOUND", "error", ""
    
    def _check_openalex(self, doi: str) -> Tuple[str, str, str]:
        """Check OpenAlex API for paper type"""
        try:
            url = f"https://api.openalex.org/works/doi:{doi}"
            data = make_api_request(self.openalex_session, url)
            
            if not data:
                return "NOT FOUND", "none", ""
            
            # Get title and paper type from API
            title = data.get("title", "")
            paper_type = self._classify_openalex(data, doi)
            
            return paper_type, "openalex", title
            
        except Exception as e:
            self.logger.error(f"OpenAlex API error for {doi}: {e}")
            return "NOT FOUND", "none", ""
    
    def _check_crossref(self, doi: str) -> Tuple[str, str, str]:
        """Check Crossref API for paper type (fallback)"""
        try:
            url = f"https://api.crossref.org/works/{doi}"
            data = make_api_request(self.crossref_session, url)
            
            if not data or "message" not in data:
                return "NOT FOUND", "none", ""
            
            work_data = data["message"]
            
            # Get title and paper type from API
            title = " ".join(work_data.get("title", []))
            paper_type = self._classify_crossref(work_data, doi)
            
            return paper_type, "crossref", title
            
        except Exception as e:
            self.logger.error(f"Crossref API error for {doi}: {e}")
            return "NOT FOUND", "none", ""
    
    def _classify_openalex(self, work_data: Dict, doi: str) -> str:
        """
        OpenAlex-specific classification logic.
        
        Args:
            work_data: OpenAlex work data
            doi: DOI being classified
            
        Returns:
            String classification: actual API paper type
        """
        title = work_data.get("title", "")
        work_type = work_data.get("type", "").lower()
        crossref_type = work_data.get("type_crossref", "").lower()
        
        # Clean title for logging (handle Unicode characters)
        clean_title = title.encode('ascii', 'replace').decode('ascii') if title else ""
        
        # Check excluded types - log but return actual type
        if work_type in self.EXCLUDED_TYPES:
            self.logger.info(f"Excluded {work_type}: {doi} - {clean_title}")
            return work_type
        
        # Check excluded Crossref types - log but return actual type
        if crossref_type in self.EXCLUDED_CROSSREF_TYPES:
            self.logger.info(f"Excluded {crossref_type}: {doi} - {clean_title}")
            return crossref_type
        
        # Check title patterns for reviews
        if title and self.review_regex.search(title):
            self.logger.info(f"Excluded review by title: {doi} - {clean_title}")
            return "openalex_review"
        
        # Return actual API type for included papers
        return work_type if work_type else "NOT FOUND"
    
    def _classify_crossref(self, work_data: Dict, doi: str) -> str:
        """
        Crossref-specific classification logic.
        
        Args:
            work_data: Crossref work data
            doi: DOI being classified
            
        Returns:
            String classification: actual API paper type
        """
        title = " ".join(work_data.get("title", []))
        work_type = work_data.get("type", "").lower()
        
        # Clean title for logging (handle Unicode characters)
        clean_title = title.encode('ascii', 'replace').decode('ascii') if title else ""
        
        # Check excluded types - log but return actual type
        if work_type in self.EXCLUDED_CROSSREF_TYPES or work_type in self.EXCLUDED_TYPES:
            self.logger.info(f"Excluded {work_type}: {doi} - {clean_title}")
            return work_type
        
        # Check title patterns for reviews
        titles = work_data.get("title", [])
        for title_text in titles:
            if self.review_regex.search(title_text):
                self.logger.info(f"Excluded review by title: {doi} - {clean_title}")
                return "crossref_review"
        
        # Return actual API type for included papers
        return work_type if work_type else "Not found"

def process_question_1_review_filter(dois: List[str], email: str) -> List[Dict]:
    """Process Question 1 for multiple DOIs"""
    # Remove duplicates using set
    unique_dois = list(dict.fromkeys(dois))  # Preserves order while removing duplicates

    # Initialize review filter
    review_filter = ReviewFilter(email=email)

    # Process DOIs with progress bar
    results = []

    with tqdm(total=len(unique_dois), desc="Classifying papers", unit="paper") as pbar:
        for doi in unique_dois:
            try:
                # Classify paper type
                paper_type, source, title = review_filter.classify_paper_type(doi)

                # Store result
                result = {
                    "doi": doi,
                    "title": title,
                    "paper_type": paper_type,
                    "classification_source": source
                }

                results.append(result)

            except Exception as e:
                logging.error(f"Error processing {doi}: {e}")
                results.append({
                    "doi": doi,
                    "title": "",
                    "paper_type": "NOT FOUND",  # Default when error
                    "classification_source": "error"
                })

            pbar.update(1)

    return results
