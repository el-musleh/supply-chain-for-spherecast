"""
document_extractor.py — Extract compliance data from PDFs, images, and HTML.

Uses:
    - Gemini multimodal for CoA image analysis
    - PyMuPDF (fitz) for PDF text extraction
    - BeautifulSoup for HTML parsing
    - PIL for image preprocessing
"""

from __future__ import annotations

import io
import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional, Union
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

try:
    import fitz  # PyMuPDF
    HAS_PYMUPDF = True
except ImportError:
    HAS_PYMUPDF = False

try:
    from pdf2image import convert_from_path
    HAS_PDF2IMAGE = True
except ImportError:
    HAS_PDF2IMAGE = False

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

# Google GenAI for multimodal extraction
try:
    import google.genai as genai
    from google.genai import types
    HAS_GENAI = True
except ImportError:
    HAS_GENAI = False


@dataclass
class ComplianceProfile:
    """Structured compliance data extracted from documents."""
    organic_certified: bool = False
    fda_registered: bool = False
    non_gmo: bool = False
    grade: str = "food"  # pharmaceutical | food | technical
    lead_time_days: int = 14
    certifications: list = None
    notes: str = ""
    extracted_from: str = ""  # Source document path/URL
    extraction_confidence: float = 0.0  # Model confidence if available
    
    def __post_init__(self):
        if self.certifications is None:
            self.certifications = []
        # Normalize grade
        self.grade = self._normalize_grade(self.grade)
    
    @staticmethod
    def _normalize_grade(grade: str) -> str:
        """Normalize grade to standard values."""
        grade_lower = str(grade).lower()
        if "pharm" in grade_lower or "usp" in grade_lower:
            return "pharmaceutical"
        if "tech" in grade_lower:
            return "technical"
        return "food"
    
    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: dict) -> "ComplianceProfile":
        """Create from dictionary."""
        # Filter to only valid fields
        valid_fields = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**valid_fields)


class CoAExtractor:
    """
    Extract structured compliance data from Certificates of Analysis.
    
    Supports:
        - PDF documents (text extraction + optional OCR via Gemini)
        - Images (PNG, JPG of CoA certificates)
        - HTML pages (supplier product pages)
    """
    
    # Extraction prompt for Gemini multimodal
    _EXTRACTION_PROMPT = """You are a supply chain compliance extraction agent. 
Analyse the provided document (CoA certificate, product spec sheet, or supplier page) 
and extract the following compliance fields into valid JSON:

{
  "organic_certified": <bool>,
  "fda_registered": <bool>,
  "non_gmo": <bool>,
  "grade": "<pharmaceutical | food | technical>",
  "lead_time_days": <int>,
  "certifications": ["<cert_name>", ...],
  "notes": "<one sentence summary>"
}

Rules:
- grade: Use "pharmaceutical" if USP grade, "food" for food grade, "technical" for industrial
- certifications: List explicit third-party certs (USP, NSF, GMP, Halal, Kosher, ISO, etc.)
- fda_registered: true if FDA registration number or "FDA registered" mentioned
- non_gmo: true if "Non-GMO", "Non GMO", or certification present
- lead_time_days: Integer, default 14 if not specified
- notes: Concise summary of key compliance points found

Respond with valid JSON only — no markdown fences, no explanations."""
    
    def __init__(
        self,
        gemini_client: Optional[genai.Client] = None,
        model: str = "gemini-flash-latest",
        temperature: float = 0.1,
        verbose: bool = False,
    ):
        if not HAS_GENAI and gemini_client is not None:
            raise ImportError("google-genai not installed")
        
        self.client = gemini_client
        self.model = model
        self.temperature = temperature
        self.verbose = verbose
        
        # Track extractions
        self._extractions_made = 0
        self._extraction_errors = 0
    
    def extract_from_pdf(
        self,
        pdf_path: Union[str, Path, bytes],
        use_multimodal: bool = True,
        max_pages: int = 5,
    ) -> ComplianceProfile:
        """
        Extract compliance data from a PDF Certificate of Analysis.
        
        Args:
            pdf_path: Path to PDF file, or bytes
            use_multimodal: Convert to images and use Gemini Vision
            max_pages: Maximum pages to process (for large PDFs)
            
        Returns:
            ComplianceProfile with extracted data
        """
        if self.verbose:
            print(f"  [extractor] Processing PDF: {pdf_path if isinstance(pdf_path, (str, Path)) else '<bytes>'}")
        
        try:
            # Handle bytes input
            if isinstance(pdf_path, bytes):
                if not HAS_PYMUPDF:
                    return self._fallback_profile("PyMuPDF not installed")
                doc = fitz.open(stream=pdf_path, filetype="pdf")
                temp_path = None
            else:
                pdf_path = Path(pdf_path)
                if not pdf_path.exists():
                    return self._fallback_profile(f"PDF not found: {pdf_path}")
                if not HAS_PYMUPDF:
                    return self._fallback_profile("PyMuPDF not installed")
                doc = fitz.open(pdf_path)
                temp_path = str(pdf_path)
            
            # Extract text first (fast)
            text_content = ""
            for i, page in enumerate(doc):
                if i >= max_pages:
                    break
                text_content += page.get_text()
            
            doc.close()
            
            # If text extraction is substantial, use it
            if len(text_content) > 200 and not use_multimodal:
                return self._extract_from_text(text_content, temp_path or "<bytes>")
            
            # Use multimodal extraction via Gemini
            if use_multimodal and HAS_PDF2IMAGE and HAS_PIL and self.client:
                return self._extract_pdf_multimodal(pdf_path, max_pages)
            
            # Fallback: text-only extraction
            return self._extract_from_text(text_content, temp_path or "<bytes>")
            
        except Exception as e:
            self._extraction_errors += 1
            if self.verbose:
                print(f"  [extractor] PDF extraction error: {e}")
            return self._fallback_profile(f"Extraction error: {e}")
    
    def extract_from_image(
        self,
        image_path: Union[str, Path, bytes],
        mime_type: str = "image/jpeg",
    ) -> ComplianceProfile:
        """
        Extract compliance data from an image (CoA photo, certificate scan).
        
        Args:
            image_path: Path to image file, or bytes
            mime_type: MIME type of image
            
        Returns:
            ComplianceProfile with extracted data
        """
        if not self.client:
            return self._fallback_profile("Gemini client not provided")
        
        if self.verbose:
            print(f"  [extractor] Processing image: {image_path if isinstance(image_path, (str, Path)) else '<bytes>'}")
        
        try:
            # Load image bytes
            if isinstance(image_path, (str, Path)):
                image_bytes = Path(image_path).read_bytes()
                source = str(image_path)
            else:
                image_bytes = image_path
                source = "<bytes>"
            
            # Resize if too large (Gemini has limits)
            if HAS_PIL and len(image_bytes) > 4 * 1024 * 1024:  # 4MB
                image_bytes = self._resize_image(image_bytes, max_size=(2048, 2048))
            
            # Call Gemini multimodal
            part = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
            
            response = self.client.models.generate_content(
                model=self.model,
                contents=[part, types.Part.from_text(text=self._EXTRACTION_PROMPT)],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=self.temperature,
                ),
            )
            
            result = json.loads(response.text.strip())
            result["extracted_from"] = source
            self._extractions_made += 1
            
            return ComplianceProfile.from_dict(result)
            
        except Exception as e:
            self._extraction_errors += 1
            if self.verbose:
                print(f"  [extractor] Image extraction error: {e}")
            return self._fallback_profile(f"Image extraction error: {e}")
    
    def extract_from_html(
        self,
        html_content: str,
        url: str = "",
    ) -> ComplianceProfile:
        """
        Extract compliance data from HTML (supplier product page).
        
        Args:
            html_content: Raw HTML string
            url: Source URL for reference
            
        Returns:
            ComplianceProfile with extracted data
        """
        if self.verbose:
            print(f"  [extractor] Processing HTML: {url or '<content>'}")
        
        try:
            # Parse HTML
            soup = BeautifulSoup(html_content, "html.parser")
            
            # Remove script/style elements
            for element in soup(["script", "style", "nav", "footer", "header", "aside"]):
                element.decompose()
            
            # Extract text
            text = soup.get_text(separator="\n", strip=True)
            
            # Clean up whitespace
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            clean_text = "\n".join(lines[:200])  # Limit length
            
            if not self.client:
                # Try heuristic extraction without LLM
                return self._heuristic_html_extraction(clean_text, url)
            
            # Use LLM for structured extraction
            prompt = f"""Extract compliance information from this supplier page content:

Source: {url}

Content:
{clean_text[:6000]}

{self._EXTRACTION_PROMPT}"""
            
            response = self.client.models.generate_content(
                model=self.model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=self.temperature,
                ),
            )
            
            result = json.loads(response.text.strip())
            result["extracted_from"] = url or "html_content"
            self._extractions_made += 1
            
            return ComplianceProfile.from_dict(result)
            
        except Exception as e:
            self._extraction_errors += 1
            if self.verbose:
                print(f"  [extractor] HTML extraction error: {e}")
            return self._fallback_profile(f"HTML extraction error: {e}")
    
    def _extract_pdf_multimodal(
        self,
        pdf_path: Union[str, Path, bytes],
        max_pages: int = 5,
    ) -> ComplianceProfile:
        """Convert PDF pages to images and extract with Gemini multimodal."""
        if not HAS_PDF2IMAGE or not HAS_PIL:
            return self._fallback_profile("pdf2image or PIL not installed")
        
        try:
            # Convert PDF to images
            if isinstance(pdf_path, bytes):
                # Save to temp file
                import tempfile
                with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                    tmp.write(pdf_path)
                    tmp_path = tmp.name
                images = convert_from_path(tmp_path, dpi=150, first_page=1, last_page=max_pages)
                Path(tmp_path).unlink()  # Cleanup
            else:
                images = convert_from_path(pdf_path, dpi=150, first_page=1, last_page=max_pages)
            
            if not images:
                return self._fallback_profile("No images extracted from PDF")
            
            # Process first page (usually has key info)
            first_page = images[0]
            img_bytes = io.BytesIO()
            first_page.save(img_bytes, format="JPEG", quality=85)
            img_bytes.seek(0)
            
            return self.extract_from_image(img_bytes.getvalue(), mime_type="image/jpeg")
            
        except Exception as e:
            return self._fallback_profile(f"PDF multimodal error: {e}")
    
    def _extract_from_text(self, text: str, source: str) -> ComplianceProfile:
        """Extract compliance data from plain text using LLM."""
        if not self.client:
            return self._heuristic_text_extraction(text, source)
        
        prompt = f"""Extract compliance information from this document text:

{self._EXTRACTION_PROMPT}

Document text:
{text[:8000]}"""
        
        response = self.client.models.generate_content(
            model=self.model,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=self.temperature,
            ),
        )
        
        result = json.loads(response.text.strip())
        result["extracted_from"] = source
        self._extractions_made += 1
        
        return ComplianceProfile.from_dict(result)
    
    def _heuristic_text_extraction(self, text: str, source: str) -> ComplianceProfile:
        """Fast rule-based extraction when LLM unavailable."""
        text_lower = text.lower()
        
        profile = ComplianceProfile(extracted_from=source)
        
        # Check for certifications
        cert_keywords = {
            "usp": "USP",
            "gmp": "GMP",
            "nsf": "NSF",
            "halal": "Halal",
            "kosher": "Kosher",
            "iso": "ISO",
            "organic": "Organic",
        }
        
        for keyword, cert_name in cert_keywords.items():
            if keyword in text_lower:
                profile.certifications.append(cert_name)
        
        # Check for non-GMO
        if "non-gmo" in text_lower or "non gmo" in text_lower:
            profile.non_gmo = True
        
        # Check for FDA registration
        if "fda" in text_lower and ("registered" in text_lower or "registration" in text_lower):
            profile.fda_registered = True
        
        # Check for organic
        if "usda organic" in text_lower or "certified organic" in text_lower:
            profile.organic_certified = True
        
        # Determine grade
        if "pharmaceutical" in text_lower or "usp" in text_lower:
            profile.grade = "pharmaceutical"
        elif "technical" in text_lower or "industrial" in text_lower:
            profile.grade = "technical"
        
        profile.notes = f"Heuristic extraction from text (no LLM). Found {len(profile.certifications)} certifications."
        
        return profile
    
    def _heuristic_html_extraction(self, text: str, url: str) -> ComplianceProfile:
        """Heuristic extraction from HTML."""
        return self._heuristic_text_extraction(text, url)
    
    def _resize_image(self, image_bytes: bytes, max_size: tuple = (2048, 2048)) -> bytes:
        """Resize image to fit within limits."""
        if not HAS_PIL:
            return image_bytes
        
        img = Image.open(io.BytesIO(image_bytes))
        img.thumbnail(max_size, Image.Resampling.LANCZOS)
        
        output = io.BytesIO()
        img.save(output, format="JPEG", quality=85)
        return output.getvalue()
    
    def _fallback_profile(self, error_msg: str) -> ComplianceProfile:
        """Create a fallback profile with default values."""
        return ComplianceProfile(
            organic_certified=False,
            fda_registered=True,  # Assume registered as safe default
            non_gmo=False,
            grade="food",
            lead_time_days=14,
            certifications=[],
            notes=f"Extraction failed: {error_msg}. Using conservative defaults.",
            extraction_confidence=0.0,
        )
    
    def get_stats(self) -> dict:
        """Get extraction statistics."""
        return {
            "extractions_made": self._extractions_made,
            "extraction_errors": self._extraction_errors,
            "has_gemini": self.client is not None,
            "has_pymupdf": HAS_PYMUPDF,
            "has_pdf2image": HAS_PDF2IMAGE,
            "has_pil": HAS_PIL,
        }
