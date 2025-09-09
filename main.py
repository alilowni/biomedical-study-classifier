#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import time
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Dict
from tqdm import tqdm

# Import our modules
from utils import *
from review_filter import *
from animal_classifier import *
import config


def main():
    """Main pipeline execution - Full comprehensive analysis"""
    pipeline(sample_size=None)

def pipeline(sample_size: int = None):
    """
    pipeline processing all questions (1, 2, 3, 5) in a single row-by-row pass.
    This is more efficient as we only do animal classification on original research papers.

    Args:
        sample_size: If provided, process only first N DOIs for testing
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    input_dir = Path(config.INPUT_DOI_FILE).parent
    input_filename = Path(config.INPUT_DOI_FILE).stem

    # Create logs directory and save log there
    logs_dir = Path("logs")
    logs_dir.mkdir(exist_ok=True)

    if sample_size:
        log_file = logs_dir / f"{input_filename}_test_{timestamp}.log"
        status_msg = f"Test Mode ({sample_size} DOIs)"
    else:
        log_file = logs_dir / f"{input_filename}_full_{timestamp}.log"
        status_msg = "Full Processing"

    setup_logging("INFO", str(log_file))

    try:
        # Load DOIs
        all_dois = read_doi_list(config.INPUT_DOI_FILE, config.DOI_COLUMN_NAME)
        if sample_size:
            dois = all_dois[:sample_size]
        else:
            dois = all_dois

        # Process all DOIs row-by-row (Questions 1, 2, 3, 5)
        included_results, excluded_results = process_all_dois_row_by_row(dois, config.EMAIL, status_msg)

        # Save results
        if sample_size:
            combined_file = input_dir / f"{input_filename}_test_combined_{timestamp}.xlsx"
        else:
            combined_file = input_dir / f"{input_filename}_combined_{timestamp}.xlsx"

        save_combined_results_excel(included_results, excluded_results, str(combined_file))

        # Final output on same line
        final_msg = f"Complete: {len(included_results):,} included, {len(excluded_results):,} excluded - Results: {combined_file}"
        print(f"\r{final_msg}", flush=True)

        # Log detailed summary (no terminal output)
        print_comprehensive_summary(included_results, excluded_results)

    except Exception as e:
        logging.error(f"Pipeline failed: {e}")
        error_msg = f"Error: {e}"
        print(f"\r{error_msg}", flush=True)
        raise

def test_sample():
    """Test with a small sample of DOIs using pipeline"""
    pipeline(sample_size=20)

if __name__ == "__main__":
    # Choose what to run:
    
    # Option 1: Test with small sample first
    test_sample()
    
    # Option 2: Run full processing
    #main()
