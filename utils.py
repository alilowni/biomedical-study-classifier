"""
UTILS: Core utilities for biomedical paper classification
- DOI processing and validation
- HTTP session management
- Excel/CSV file handling
- Progress tracking and logging
"""

import re
import time
import json
import logging
import pandas as pd
import requests
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from urllib.parse import unquote
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from tqdm import tqdm

DOI_REGEX = re.compile(r"^10\.\d{4,9}/[-._;()/:A-Z0-9]+$", re.IGNORECASE)
URL_DOI_REGEX = re.compile(r"https?://(dx\.)?doi\.org/(.+)", re.IGNORECASE)

# HTTP status codes
HTTP_SUCCESS = 200
HTTP_NOT_FOUND = 404
HTTP_RATE_LIMITED = 429
HTTP_SERVER_ERROR = 500

def normalize_doi(doi: str) -> str:
    """Clean and normalize DOI format"""
    if not doi or not isinstance(doi, str):
        return ""
    
    # Remove whitespace
    doi = doi.strip()
    
    # Extract DOI from URL if present
    url_match = URL_DOI_REGEX.match(doi)
    if url_match:
        doi = url_match.group(2)
    
    # URL decode if needed
    doi = unquote(doi)
    
    # Convert to lowercase
    doi = doi.lower()
    
    return doi
    
def validate_doi(doi: str) -> bool:
    """Check if DOI format is valid"""
    if not doi or not isinstance(doi, str):
        return False
    
    return bool(DOI_REGEX.match(doi))

def create_http_session(user_agent: str, rate_limit: float = 1.0) -> requests.Session:
    """Create HTTP session with retry and rate limiting"""
    session = requests.Session()
    
    # Configure retry strategy
    retry_strategy = Retry(
        total=3,
        backoff_factor=2,
        status_forcelist=[429, 500, 502, 503, 504],
    )
    
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    
    # Set default headers
    session.headers.update({
        'User-Agent': user_agent,
        'Accept': 'application/json',
    })
    
    # Add rate limiting attribute
    session._rate_limit = rate_limit
    session._last_request = 0
    
    return session

def make_api_request(session: requests.Session, url: str, params: Optional[Dict] = None, 
                    timeout: int = 30) -> Optional[Dict]:
    """Make API request with error handling and retries"""
    try:
        # Rate limiting
        if hasattr(session, '_rate_limit') and hasattr(session, '_last_request'):
            elapsed = time.time() - session._last_request
            if elapsed < session._rate_limit:
                time.sleep(session._rate_limit - elapsed)
        
        # Make request
        response = session.get(url, params=params, timeout=timeout)
        
        # Update rate limiting timestamp
        if hasattr(session, '_last_request'):
            session._last_request = time.time()
        
        # Check for rate limiting
        if response.status_code == HTTP_RATE_LIMITED:
            retry_after = int(response.headers.get('Retry-After', 60))
            logging.warning(f"Rate limited, waiting {retry_after} seconds")
            time.sleep(retry_after)
            return make_api_request(session, url, params, timeout)
        
        # Check for success
        if response.status_code == HTTP_SUCCESS:
            return response.json()
        elif response.status_code == HTTP_NOT_FOUND:
            return None
        else:
            logging.warning(f"API request failed: {response.status_code} for {url}")
            return None
            
    except requests.exceptions.RequestException as e:
        logging.error(f"Request exception for {url}: {e}")
        return None
    except json.JSONDecodeError as e:
        logging.error(f"JSON decode error for {url}: {e}")
        return None
    except Exception as e:
        logging.error(f"Unexpected error for {url}: {e}")
        return None

def read_doi_list(file_path: str, column_name: str = "DOI nummer") -> List[str]:
    """Read and validate DOIs from Excel/CSV file"""
    try:
        # Read file based on extension
        if file_path.endswith('.xlsx') or file_path.endswith('.xls'):
            df = pd.read_excel(file_path)
        elif file_path.endswith('.csv'):
            df = pd.read_csv(file_path)
        else:
            raise ValueError(f"Unsupported file format: {file_path}")
        
        # Check if column exists
        if column_name not in df.columns:
            raise ValueError(f"Column '{column_name}' not found in {file_path}")
        
        # Extract DOIs and clean
        dois = df[column_name].dropna().astype(str).tolist()
        
        # Normalize and validate DOIs
        clean_dois = []
        for doi in dois:
            normalized = normalize_doi(doi)
            if validate_doi(normalized):
                clean_dois.append(normalized)
            else:
                logging.warning(f"Invalid DOI format: {doi}")
        
        # Remove duplicates using set
        seen = set()
        unique_dois = []
        for doi in clean_dois:
            if doi not in seen:
                seen.add(doi)
                unique_dois.append(doi)
        
        return unique_dois
        
    except Exception as e:
        logging.error(f"Error reading DOI list from {file_path}: {e}")
        raise

def save_results_csv(results: List[Dict], output_path: str):
    """Save results to CSV file"""
    try:
        # Create output directory if needed
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        
        # Convert to DataFrame and save
        df = pd.DataFrame(results)
        df.to_csv(output_path, index=False, encoding='utf-8')
        
    except Exception as e:
        logging.error(f"Error saving results to {output_path}: {e}")
        raise

def save_results_excel(results: List[Dict], output_path: str):
    """Save results to Excel with summary sheets"""
    try:
        # Create output directory if needed
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        # Convert to DataFrame
        df = pd.DataFrame(results)

        # Save to Excel with better formatting
        with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
            # Main results sheet
            df.to_excel(writer, sheet_name='Results', index=False)

            # Add summary sheet
            error_count = len([r for r in results if r.get('classification_source') == 'error'])

            # Count by paper type
            paper_types = {}
            for result in results:
                paper_type = result.get('paper_type', 'unknown')
                paper_types[paper_type] = paper_types.get(paper_type, 0) + 1

            summary_data = {
                'Metric': ['Total Papers', 'Errors', 'Success Rate'] + list(paper_types.keys()),
                'Count': [
                    len(results),
                    error_count,
                    f"{((len(results) - error_count) / len(results) * 100):.1f}%"
                ] + list(paper_types.values()),
                'Percentage': [
                    '100.0%',
                    f"{(error_count / len(results) * 100):.1f}%",
                    '-'
                ] + [f"{(count / len(results) * 100):.1f}%" for count in paper_types.values()]
            }
            summary_df = pd.DataFrame(summary_data)
            summary_df.to_excel(writer, sheet_name='Summary', index=False)

    except Exception as e:
        logging.error(f"Error saving results to {output_path}: {e}")
        raise

def save_combined_results_excel(included_results: List[Dict], excluded_results: List[Dict], output_path: str):
    """Save included and excluded results to single Excel file"""
    try:
        # Create output directory if needed
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        # Convert to DataFrames
        included_df = pd.DataFrame(included_results)
        excluded_df = pd.DataFrame(excluded_results)

        # Save to Excel with two main sheets
        with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
            # Included papers sheet
            included_df.to_excel(writer, sheet_name='Included', index=False)

            # Excluded papers sheet
            excluded_df.to_excel(writer, sheet_name='Excluded', index=False)

            # Add comprehensive summary sheet
            total_processed = len(included_results) + len(excluded_results)
            included_count = len(included_results)
            excluded_count = len(excluded_results)

            # Calculate animal study statistics (for included papers only)
            animals_used_count = sum(1 for r in included_results if r.get("animals_used", False))
            in_vivo_count = sum(1 for r in included_results if r.get("in_vivo", False))
            has_species_count = sum(1 for r in included_results if r.get("species", []))

            # Count by paper type for excluded papers
            excluded_paper_types = {}
            for result in excluded_results:
                paper_type = result.get('paper_type', 'unknown')
                excluded_paper_types[paper_type] = excluded_paper_types.get(paper_type, 0) + 1

            summary_data = {
                'Category': ['Total Papers Processed', 'Included (Original Research)', 'Excluded (Reviews/Other)',
                           'Animal Studies Found', 'In Vivo Experiments', 'Papers with Species'],
                'Count': [
                    total_processed,
                    included_count,
                    excluded_count,
                    animals_used_count,
                    in_vivo_count,
                    has_species_count
                ],
                'Percentage': [
                    '100.0%',
                    f"{(included_count/total_processed*100):.1f}%" if total_processed > 0 else '0.0%',
                    f"{(excluded_count/total_processed*100):.1f}%" if total_processed > 0 else '0.0%',
                    f"{(animals_used_count/included_count*100):.1f}%" if included_count > 0 else '0.0%',
                    f"{(in_vivo_count/included_count*100):.1f}%" if included_count > 0 else '0.0%',
                    f"{(has_species_count/included_count*100):.1f}%" if included_count > 0 else '0.0%'
                ]
            }

            # Add excluded paper type breakdown
            if excluded_paper_types:
                for paper_type, count in sorted(excluded_paper_types.items()):
                    summary_data['Category'].append(f"Excluded: {paper_type}")
                    summary_data['Count'].append(count)
                    summary_data['Percentage'].append(f"{(count/excluded_count*100):.1f}%" if excluded_count > 0 else '0.0%')

            summary_df = pd.DataFrame(summary_data)
            summary_df.to_excel(writer, sheet_name='Summary', index=False)

    except Exception as e:
        logging.error(f"Error saving combined results to {output_path}: {e}")
        raise

def process_doi_row_by_row(doi: str, review_filter, animal_classifier) -> Dict:
    """Process single DOI through all classification steps"""
    try:
        # Question 1: Classify paper type (original research vs review/etc)
        paper_type, source, title = review_filter.classify_paper_type(doi)

        # Initialize result with Question 1 data
        result = {
            "doi": doi,
            "title": title,
            "paper_type": paper_type,
            "classification_source": source,

            # Initialize animal study fields (will be filled if original research)
            "pmid": None,
            "mesh_count": 0,
            "animals_used": False,
            "animals_confidence": "NOT FOUND",
            "animal_evidence": [],
            "in_vivo": False,
            "in_vivo_confidence": "NOT FOUND",
            "in_vivo_evidence": [],
            "species": [],
            "species_evidence": [],
            "mesh_terms_debug": []
        }

        # Check if this is original research (should proceed to animal classification)
        if paper_type not in review_filter.EXCLUDED_TYPES_COMPLETE:
            # Questions 2, 3, 5: Animal classification for original research papers
            try:
                animal_result = animal_classifier.classify_single_paper(doi)

                # Update result with animal classification data
                result.update({
                    "pmid": animal_result.get("pmid"),
                    "mesh_count": animal_result.get("mesh_count", 0),
                    "animals_used": animal_result.get("animals_used", False),
                    "animals_confidence": animal_result.get("animals_confidence", "NOT FOUND"),
                    "animal_evidence": animal_result.get("animal_evidence", []),
                    "in_vivo": animal_result.get("in_vivo", False),
                    "in_vivo_confidence": animal_result.get("in_vivo_confidence", "NOT FOUND"),
                    "in_vivo_evidence": animal_result.get("in_vivo_evidence", []),
                    "species": animal_result.get("species", []),
                    "species_evidence": animal_result.get("species_evidence", []),
                    "mesh_terms_debug": animal_result.get("mesh_terms_debug", [])
                })

                # Add any errors from animal classification
                if "error" in animal_result:
                    result["animal_classification_error"] = animal_result["error"]

            except Exception as e:
                logging.error(f"Error in animal classification for {doi}: {e}")
                result["animal_classification_error"] = str(e)

        return result

    except Exception as e:
        logging.error(f"Error processing {doi}: {e}")
        return {
            "doi": doi,
            "title": "",
            "paper_type": "NOT FOUND",  # Default when error
            "classification_source": "error",
            "pmid": None,
            "mesh_count": 0,
            "animals_used": False,
            "animals_confidence": "NOT FOUND",
            "animal_evidence": [],
            "in_vivo": False,
            "in_vivo_confidence": "NOT FOUND",
            "in_vivo_evidence": [],
            "species": [],
            "species_evidence": [],
            "mesh_terms_debug": [],
            "processing_error": str(e)
        }

def process_all_dois_row_by_row(dois: List[str], email: str, status_msg: str = "") -> tuple[List[Dict], List[Dict]]:
    """Process all DOIs with row-by-row classification"""
    # Import here to avoid circular imports
    from review_filter import ReviewFilter
    from animal_classifier import AnimalClassifier

    # Remove duplicates using set
    unique_dois = list(dict.fromkeys(dois))  # Preserves order while removing duplicates

    # Initialize classifiers (shared across all DOIs for efficiency)
    review_filter = ReviewFilter(email=email)
    animal_classifier = AnimalClassifier(
        email=email,
        include_animals=True,
        include_humans=False
    )

    # Process DOIs row-by-row with progress bar
    included_results = []
    excluded_results = []

    desc = f"Biomedical Research Classifier - {status_msg}"
    with tqdm(total=len(unique_dois), desc=desc, unit="paper", ncols=120, bar_format='{desc}: {percentage:3.0f}%|{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}]') as pbar:
        for doi in unique_dois:
            result = process_doi_row_by_row(doi, review_filter, animal_classifier)

            # Separate results based on paper type
            if result["paper_type"] in review_filter.EXCLUDED_TYPES_COMPLETE:
                excluded_results.append(result)
            else:
                included_results.append(result)

            pbar.update(1)

    return included_results, excluded_results

def print_comprehensive_summary(all_results: List[Dict], excluded_results: List[Dict]):
    """Log detailed classification summary"""

    total_processed = len(all_results) + len(excluded_results)
    included_count = len(all_results)

    # Final summary - only log critical errors
    error_count = sum(1 for r in all_results + excluded_results if r.get("error"))
    if error_count > 0:
        logging.warning(f"Total errors: {error_count} papers had processing issues")

def merge_classification_results(question1_results: List[Dict], animal_results: List[Dict]) -> List[Dict]:
    """Merge Question 1 and animal classification results"""
    # Create DOI lookup for animal results
    animal_lookup = {result["doi"]: result for result in animal_results}

    # Merge results
    merged_results = []
    for q1_result in question1_results:
        doi = q1_result["doi"]

        # Start with Question 1 data
        merged = {
            "doi": doi,
            "title": q1_result.get("title", ""),
            "paper_type": q1_result["paper_type"],
            "classification_source": q1_result["classification_source"],

            # Initialize animal study fields
            "pmid": None,
            "mesh_count": 0,
            "animals_used": False,
            "animals_confidence": "NOT FOUND",
            "animal_evidence": [],
            "in_vivo": False,
            "in_vivo_confidence": "NOT FOUND",
            "in_vivo_evidence": [],
            "species": [],
            "species_evidence": [],
            "mesh_terms_debug": []
        }

        # Add animal classification data if available
        if doi in animal_lookup:
            animal_data = animal_lookup[doi]
            merged.update({
                "pmid": animal_data.get("pmid"),
                "mesh_count": animal_data.get("mesh_count", 0),
                "animals_used": animal_data.get("animals_used", False),
                "animals_confidence": animal_data.get("animals_confidence", "NOT FOUND"),
                "animal_evidence": animal_data.get("animal_evidence", []),
                "in_vivo": animal_data.get("in_vivo", False),
                "in_vivo_confidence": animal_data.get("in_vivo_confidence", "NOT FOUND"),
                "in_vivo_evidence": animal_data.get("in_vivo_evidence", []),
                "species": animal_data.get("species", []),
                "species_evidence": animal_data.get("species_evidence", []),
                "mesh_terms_debug": animal_data.get("mesh_terms_debug", [])
            })

            # Add any errors from animal classification
            if "error" in animal_data:
                merged["animal_classification_error"] = animal_data["error"]

        merged_results.append(merged)

    return merged_results

def track_progress(current: int, total: int, start_time: float):
    """Display progress with rate and ETA"""
    if current == 0:
        return
    
    elapsed = time.time() - start_time
    rate = current / elapsed if elapsed > 0 else 0
    
    if rate > 0:
        eta_seconds = (total - current) / rate
        eta_str = f"{eta_seconds/60:.1f}m" if eta_seconds > 60 else f"{eta_seconds:.0f}s"
    else:
        eta_str = "NOT FOUND"
    
    percent = (current / total) * 100
    
    print(f"\rProgress: {current:,}/{total:,} ({percent:.1f}%) | "
          f"Rate: {rate:.1f}/s | ETA: {eta_str}", end="", flush=True)
    
    if current == total:
        print()  # New line when complete

def setup_logging(log_level: str = "WARNING", log_file: Optional[str] = None):
    """Configure logging for file and console output - minimal verbosity"""
    # Create logs directory if needed
    if log_file:
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)

    # Configure logging - much more minimal
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.ERROR)  # Only show errors in terminal
    console_formatter = logging.Formatter('%(message)s')
    console_handler.setFormatter(console_formatter)

    handlers = [console_handler]

    # File handler - only show WARNING and above (ERROR, CRITICAL)
    if log_file:
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setLevel(logging.WARNING)  # Only warnings, errors, critical
        file_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        file_handler.setFormatter(file_formatter)
        handlers.append(file_handler)

    # Configure root logger
    logging.basicConfig(
        level=logging.WARNING,  # Set to WARNING to reduce noise
        handlers=handlers,
        force=True
    )

    # Reduce noise from all libraries
    logging.getLogger("urllib3").setLevel(logging.ERROR)
    logging.getLogger("requests").setLevel(logging.ERROR)
    logging.getLogger("animal_classifier").setLevel(logging.WARNING)
    logging.getLogger("review_filter").setLevel(logging.WARNING)
