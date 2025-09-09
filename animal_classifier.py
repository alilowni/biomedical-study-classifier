"""
ANIMAL CLASSIFIER: Detect animal studies in biomedical papers
- Question 2: Were animals used in testing?
- Question 3: Were in vivo experiments conducted?
- Question 5: Which animal species were used?
- Uses MeSH terms from PubMed to classify papers
"""

from typing import List, Dict, Optional, Tuple, Set
import requests
import xml.etree.ElementTree as ET
import time
import logging
from utils import normalize_doi, create_http_session, make_api_request
import config

class AnimalClassifier:
    """Classifier for animal studies using MeSH terms"""
    
    def __init__(self, email: str, ncbi_api_key: Optional[str] = None,
                 include_animals: bool = True, include_humans: bool = False):
        """Initialize with NCBI API access"""
        self.email = email
        self.ncbi_api_key = ncbi_api_key
        self.include_animals = include_animals
        self.include_humans = include_humans
        
        # NCBI API configuration
        self.ncbi_base_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
        self.ncbi_tool_name = "research_classifier"
        self.rate_limit = 3 if not ncbi_api_key else 10  # Requests per second
        
        # Create HTTP session for API calls
        self.session = create_http_session(
            user_agent=f"{self.ncbi_tool_name}/1.0 ({email})",
            rate_limit=1.0 / self.rate_limit  # Convert to seconds between requests
        )
        
        # In-memory MeSH species mapping (loaded on first use)
        self._species_cache: Optional[Dict[str, str]] = None
        
        # Classification counters
        self.stats = {
            "processed": 0,
            "animals_found": 0,
            "in_vivo_found": 0,
            "species_found": 0,
            "api_errors": 0,
            "pmid_not_found": 0,
            "mesh_not_found": 0
        }
        
        # Setup logging
        self.logger = logging.getLogger(__name__)
    
    def _doi_to_pmid(self, doi: str) -> Optional[str]:
        """Convert DOI to PubMed ID (PMID)"""
        
        # Method 1: NCBI ID Converter (faster)
        try:
            url = "https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/"
            params = {
                "ids": doi,
                "format": "json"
            }
            
            response = make_api_request(self.session, url, params)
            if response and "records" in response:
                records = response["records"]
                if records and "pmid" in records[0]:
                    pmid = records[0]["pmid"]
                    return pmid
                    
        except Exception as e:
            self.logger.warning(f"ID Converter failed for {doi}: {str(e)[:100]}")

        # Method 2: NCBI ESearch fallback
        try:
            url = f"{self.ncbi_base_url}/esearch.fcgi"
            params = {
                "db": "pubmed",
                "term": f'"{doi}"[DOI]',
                "retmode": "json",
                "tool": self.ncbi_tool_name,
                "email": self.email
            }

            if self.ncbi_api_key:
                params["api_key"] = self.ncbi_api_key

            response = make_api_request(self.session, url, params)
            if response and "esearchresult" in response:
                id_list = response["esearchresult"].get("idlist", [])
                if id_list:
                    pmid = id_list[0]
                    return pmid

        except Exception as e:
            self.logger.warning(f"ESearch failed for {doi}: {str(e)[:100]}")

        self.logger.error(f"CRITICAL: Could not find PMID for DOI: {doi}")
        return None
    
    def _pmid_to_mesh(self, pmid: str) -> Tuple[List[Dict], Dict]:
        """Extract MeSH terms from PubMed article"""
        
        # Fetch PubMed XML
        try:
            url = f"{self.ncbi_base_url}/efetch.fcgi"
            params = {
                "db": "pubmed",
                "id": pmid,
                "retmode": "xml",
                "tool": self.ncbi_tool_name,
                "email": self.email
            }
            
            if self.ncbi_api_key:
                params["api_key"] = self.ncbi_api_key
            
            response = self.session.get(url, params=params, timeout=30)
            response.raise_for_status()
            
            # Parse XML to extract MeSH terms
            root = ET.fromstring(response.text)
            
            # Find MedlineCitation element
            medline_citation = root.find(".//PubmedArticle/MedlineCitation")
            if medline_citation is None:
                self.logger.warning(f"No MedlineCitation found for PMID {pmid}")
                return [], {}
            
            # Extract MeSH headings
            mesh_terms = []
            mesh_headings = medline_citation.findall(".//MeshHeadingList/MeshHeading")
            
            for heading in mesh_headings:
                descriptor = heading.find("DescriptorName")
                if descriptor is not None:
                    mesh_term = {
                        "ui": descriptor.get("UI", ""),
                        "name": descriptor.text or "",
                        "major_topic": descriptor.get("MajorTopicYN", "N") == "Y"
                    }
                    
                    # Extract qualifiers if present
                    qualifiers = []
                    for qualifier in heading.findall("QualifierName"):
                        qualifiers.append({
                            "ui": qualifier.get("UI", ""),
                            "name": qualifier.text or "",
                            "major_topic": qualifier.get("MajorTopicYN", "N") == "Y"
                        })
                    
                    mesh_term["qualifiers"] = qualifiers
                    mesh_terms.append(mesh_term)
            
            # Extract basic metadata
            title_elem = medline_citation.find(".//ArticleTitle")
            abstract_elem = medline_citation.find(".//AbstractText")
            
            metadata = {
                "pmid": pmid,
                "title": title_elem.text if title_elem is not None else "",
                "abstract": abstract_elem.text if abstract_elem is not None else "",
                "mesh_count": len(mesh_terms)
            }
            
            return mesh_terms, metadata

        except Exception as e:
            self.logger.error(f"MeSH extraction failed for PMID {pmid}: {str(e)[:100]}")
            return [], {}
    
    def _classify_animals_used(self, mesh_terms: List[Dict]) -> Tuple[bool, str, List[str]]:
        """Question 2: Check if animals were used in testing"""
        
        # Key MeSH UIs for animal detection
        animal_mesh_uis = {
            "D000818": "Animals",
            "D023421": "Models, Animal", 
            "D004195": "Disease Models, Animal",
            "D032761": "Animal Experimentation"
        }
        
        # Human-only indicator
        human_mesh_ui = "D006801"
        
        # In vitro indicators
        in_vitro_uis = {
            "D066298": "In Vitro Techniques",
            "D002478": "Cells, Cultured",
            "D018929": "Cell Culture Techniques"
        }
        
        found_animal_terms = []
        found_human_terms = []
        found_in_vitro_terms = []
        
        # Check each MeSH term
        for term in mesh_terms:
            ui = term.get("ui", "")
            name = term.get("name", "")
            
            if ui in animal_mesh_uis:
                found_animal_terms.append(f"{name} ({ui})")
            elif ui == human_mesh_ui:
                found_human_terms.append(f"{name} ({ui})")
            elif ui in in_vitro_uis:
                found_in_vitro_terms.append(f"{name} ({ui})")
        
        # Classification logic based on configuration
        animals_used = False
        confidence = "low"
        evidence_terms = []
        
        if self.include_animals and found_animal_terms:
            animals_used = True
            evidence_terms.extend(found_animal_terms)
            confidence = "high" if len(found_animal_terms) > 1 else "medium"
        
        elif self.include_humans and found_human_terms and not found_animal_terms:
            # Human-only studies (if configured to include humans)
            animals_used = True  # Note: treating humans as "subjects" for consistency
            evidence_terms.extend(found_human_terms)
            confidence = "medium"
        
        # Reduce confidence if strong in vitro indicators present
        if found_in_vitro_terms and confidence in ["high", "medium"]:
            confidence = "low"
            self.logger.debug(f"Reduced confidence due to in vitro terms: {found_in_vitro_terms}")
        
        return animals_used, confidence, evidence_terms
    
    def _classify_in_vivo(self, mesh_terms: List[Dict], animals_used: bool,
                         animals_confidence: str) -> Tuple[bool, str, List[str]]:
        """Question 3: Check if in vivo experiments were conducted"""
        
        if not animals_used:
            return False, "NOT FOUND", ["No animals/subjects detected"]
        
        # Strong in vitro indicators
        in_vitro_uis = {
            "D066298": "In Vitro Techniques",
            "D002478": "Cells, Cultured", 
            "D018929": "Cell Culture Techniques",
            "D046508": "Cell Culture",
            "D019149": "Bioreactors"
        }
        
        # In vivo supporting terms
        in_vivo_supporting_uis = {
            "D032761": "Animal Experimentation",
            "D023421": "Models, Animal",
            "D004195": "Disease Models, Animal",
            "D001522": "Behavioral Phenomena",
        }
        
        found_in_vitro_terms = []
        found_in_vivo_terms = []
        
        for term in mesh_terms:
            ui = term.get("ui", "")
            name = term.get("name", "")
            
            if ui in in_vitro_uis:
                found_in_vitro_terms.append(f"{name} ({ui})")
            elif ui in in_vivo_supporting_uis:
                found_in_vivo_terms.append(f"{name} ({ui})")
        
        # Classification logic
        if found_in_vitro_terms and not found_in_vivo_terms:
            # Strong in vitro indicators, no in vivo support
            in_vivo = False
            confidence = "medium"
            evidence_terms = found_in_vitro_terms
        
        elif found_in_vivo_terms:
            # Strong in vivo support
            in_vivo = True
            confidence = "high"
            evidence_terms = found_in_vivo_terms
        
        else:
            # Default assumption: if animals used, likely in vivo
            in_vivo = True
            confidence = "low" if animals_confidence == "low" else "medium"
            evidence_terms = ["Assumption: animals present without strong in vitro indicators"]
        
        return in_vivo, confidence, evidence_terms
    
    def _extract_species(self, mesh_terms: List[Dict]) -> Tuple[List[str], List[str]]:
        """Question 5: Extract animal species used in study"""
        
        # Common species mapping (simplified for now)
        species_mapping = {
            "D051379": "Mice",
            "D051381": "Rats", 
            "D011817": "Rabbits",

        }
        
        found_species = []
        evidence_terms = []
        
        for term in mesh_terms:
            ui = term.get("ui", "")
            name = term.get("name", "")
            
            if ui in species_mapping:
                species_name = species_mapping[ui]
                if species_name not in found_species:
                    found_species.append(species_name)
                    evidence_terms.append(f"{species_name} ({ui})")
        
        return found_species, evidence_terms
    
    def classify_single_paper(self, doi: str) -> Dict:
        """Classify single paper for animal studies"""
        results = self.classify_animal_studies([doi])
        return results[0] if results else {
            "doi": doi,
            "pmid": None,
            "animals_used": False,
            "animals_confidence": "NOT FOUND",
            "in_vivo": False,
            "in_vivo_confidence": "NOT FOUND",
            "species": [],
            "error": "No result returned"
        }

    def classify_animal_studies(self, dois: List[str]) -> List[Dict]:
        """Main function to classify multiple DOIs for animal studies"""

        results = []

        from tqdm import tqdm

        # Disable progress bar for single paper classification to avoid interfering with main progress
        disable_progress = len(dois) == 1
        with tqdm(total=len(dois), desc="Animal classification", unit="paper", ncols=80, disable=disable_progress) as pbar:
            for doi in enumerate(dois):
                doi = doi[1] if isinstance(doi, tuple) else doi  # Handle enumerate
                try:
                    # Normalize DOI
                    clean_doi = normalize_doi(doi)
                    if not clean_doi:
                        self.logger.warning(f"Invalid DOI: {doi}")
                        results.append({"doi": doi, "error": "Invalid DOI format", "animals_used": False, "animals_confidence": "NOT FOUND", "in_vivo": False, "in_vivo_confidence": "NOT FOUND", "species": []})
                        pbar.update(1)
                        continue

                    # Step 1: DOI → PMID
                    pmid = self._doi_to_pmid(clean_doi)
                    if not pmid:
                        self.stats["pmid_not_found"] += 1
                        results.append({
                            "doi": clean_doi,
                            "pmid": None,
                            "animals_used": False,
                            "animals_confidence": "NOT FOUND",
                            "in_vivo": False,
                            "in_vivo_confidence": "NOT FOUND",
                            "species": [],
                            "error": "PMID not found"
                        })
                        pbar.update(1)
                        continue

                    # Step 2: PMID → MeSH terms
                    mesh_terms, metadata = self._pmid_to_mesh(pmid)
                    if not mesh_terms:
                        self.stats["mesh_not_found"] += 1
                        results.append({
                            "doi": clean_doi,
                            "pmid": pmid,
                            "animals_used": False,
                            "animals_confidence": "NOT FOUND",
                            "in_vivo": False,
                            "in_vivo_confidence": "NOT FOUND",
                            "species": [],
                            "error": "No MeSH terms found"
                        })
                        pbar.update(1)
                        continue

                    # Step 3: Classify animals used (Question 2)
                    animals_used, animals_conf, animal_evidence = self._classify_animals_used(mesh_terms)

                    # Step 4: Classify in vivo (Question 3)
                    in_vivo, in_vivo_conf, in_vivo_evidence = self._classify_in_vivo(
                        mesh_terms, animals_used, animals_conf
                    )

                    # Step 5: Extract species (Question 5)
                    species, species_evidence = self._extract_species(mesh_terms)

                    # Compile result
                    result = {
                        "doi": clean_doi,
                        "pmid": pmid,
                        "title": metadata.get("title", ""),
                        "mesh_count": metadata.get("mesh_count", 0),

                        # Question 2: Animal testing
                        "animals_used": animals_used,
                        "animals_confidence": animals_conf,
                        "animal_evidence": animal_evidence,

                        # Question 3: In vivo
                        "in_vivo": in_vivo,
                        "in_vivo_confidence": in_vivo_conf,
                        "in_vivo_evidence": in_vivo_evidence,

                        # Question 5: Species
                        "species": species,
                        "species_evidence": species_evidence,

                        # Debug info (minimal)
                        "mesh_terms_debug": [f"{t['name']} ({t['ui']})" for t in mesh_terms[:3]]  # First 3 only
                    }

                    results.append(result)

                    # Update statistics
                    self.stats["processed"] += 1
                    if animals_used:
                        self.stats["animals_found"] += 1
                    if in_vivo:
                        self.stats["in_vivo_found"] += 1
                    if species:
                        self.stats["species_found"] += 1

                    # Rate limiting
                    time.sleep(1.0 / self.rate_limit)

                except Exception as e:
                    self.logger.error(f"ERROR processing {doi}: {str(e)[:150]}")
                    self.stats["api_errors"] += 1
                    results.append({
                        "doi": clean_doi if 'clean_doi' in locals() else doi,
                        "pmid": None,
                        "animals_used": False,
                        "animals_confidence": "NOT FOUND",
                        "in_vivo": False,
                        "in_vivo_confidence": "NOT FOUND",
                        "species": [],
                        "error": str(e)[:200]
                    })

                pbar.update(1)

        return results

def process_questions_2_3_5_animal_classification(included_papers: List[Dict], email: str) -> List[Dict]:
    """Process Questions 2, 3, 5 for multiple papers"""
    # Extract DOIs from included papers
    dois = [paper["doi"] for paper in included_papers]

    # Initialize animal classifier (animals only, no humans)
    animal_classifier = AnimalClassifier(
        email=email,
        include_animals=True,
        include_humans=False
    )

    # Classify animal studies
    animal_results = animal_classifier.classify_animal_studies(dois)

    return animal_results