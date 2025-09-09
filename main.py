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


def run_pipeline(dois_to_process, mode_name, log_suffix):
    """Run the classification pipeline for given DOIs"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    input_dir = Path(config.INPUT_DOI_FILE).parent
    input_filename = Path(config.INPUT_DOI_FILE).stem

    # Create logs directory
    logs_dir = Path("logs")
    logs_dir.mkdir(exist_ok=True)

    log_file = logs_dir / f"{input_filename}_{log_suffix}_{timestamp}.log"
    setup_logging("INFO", str(log_file))

    try:
        # Process DOIs row-by-row (Questions 1, 2, 3, 5)
        included_results, excluded_results = process_all_dois_row_by_row(dois_to_process, config.EMAIL, mode_name)

        # Save results
        combined_file = input_dir / f"{input_filename}_{log_suffix}_combined_{timestamp}.xlsx"
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

def test_mode():
    """Test mode: Process exactly 20 DOIs"""
    all_dois = read_doi_list(config.INPUT_DOI_FILE, config.DOI_COLUMN_NAME)
    test_dois = all_dois[:20]  # Exactly 20 DOIs
    print("Biomedical Research Classifier - Test Mode (20 DOIs)")
    run_pipeline(test_dois, "Test Mode (20 DOIs)", "test")

def full_mode():
    """Full mode: Process ALL DOIs"""
    all_dois = read_doi_list(config.INPUT_DOI_FILE, config.DOI_COLUMN_NAME)
    print("Biomedical Research Classifier - Full Processing")
    run_pipeline(all_dois, "Full Processing", "full")

if __name__ == "__main__":
    # Choose what to run:

    # Option 1: Test with exactly 20 DOIs
    test_mode()

    # Option 2: Run full processing (ALL DOIs)
    # full_mode()
