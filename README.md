# Biomedical Research Classifier

Classifies biomedical papers to answer key research questions using AI and API integration.

## Overview

This system automatically analyzes biomedical research papers to determine:
- **Q1**: Is this original research or a review?
- **Q2**: Were animals used in the study?
- **Q3**: Were in vivo experiments conducted?
- **Q5**: Which animal species were used?

## Modules

### `main.py`
Entry point for running the classification pipeline.

### `review_filter.py`
**Question 1**: Detects original research vs reviews/editorials.
- Uses OpenAlex API (primary) and Crossref API (fallback)
- Filters out non-research papers automatically

### `animal_classifier.py`
**Questions 2, 3, 5**: Analyzes animal studies.
- Extracts MeSH terms from PubMed
- Identifies animal usage with confidence levels
- Detects in vivo vs in vitro experiments
- Extracts specific animal species used

### `utils.py`
Core utilities and data processing functions.
- DOI validation and normalization
- HTTP session management with rate limiting
- Excel/CSV file handling
- Progress tracking and logging

## Usage

```bash
python main.py
```

## Output

- Combined Excel file with included/excluded papers
- Summary statistics and analysis
- Minimal terminal output, detailed logs

## Requirements

See `requirements.txt` for dependencies.
