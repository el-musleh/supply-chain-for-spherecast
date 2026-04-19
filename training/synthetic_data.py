"""
synthetic_data.py — Teacher-Student LLM pipeline for training data generation.

When real supplier data is unavailable (CAPTCHA blocks, robots.txt denial,
or supplier not yet onboarded), use a "Teacher" model (large, capable)
to generate high-quality synthetic training examples for a "Student" model
(smaller, faster, fine-tuned on synthetic data).

This approach:
    1. Scales beyond available real data
    2. Maintains privacy (no real supplier data exposed)
    3. Provides edge case coverage (rare certifications, unusual grades)
    4. Enables rapid prototyping before production data access
"""

from __future__ import annotations

import json
import random
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

from scrapers.document_extractor import ComplianceProfile

try:
    import google.genai as genai
    from google.genai import types
    HAS_GENAI = True
except ImportError:
    HAS_GENAI = False


@dataclass
class SyntheticSupplierProfile:
    """A synthetic supplier profile with metadata."""
    supplier_name: str
    ingredient_name: str
    compliance: ComplianceProfile
    synthetic: bool = True
    generation_seed: Optional[int] = None
    teacher_model: str = "unknown"
    
    def to_dict(self) -> dict:
        return {
            "supplier_name": self.supplier_name,
            "ingredient_name": self.ingredient_name,
            "compliance": self.compliance.to_dict(),
            "synthetic": self.synthetic,
            "generation_seed": self.generation_seed,
            "teacher_model": self.teacher_model,
        }


class SyntheticDataGenerator:
    """
    Generate realistic synthetic supplier compliance data using a Teacher LLM.
    
    The Teacher model (e.g., Gemini Pro) generates high-quality examples
    based on domain knowledge of CPG supply chain compliance.
    """
    
    # Domain-specific templates for realistic generation
    COMMON_CERTIFICATIONS = [
        "USP", "NSF", "GMP", "cGMP", "ISO 9001", "ISO 22000",
        "Halal", "Kosher", "Non-GMO Project", "USDA Organic",
        "EU Organic", "BRC", "FSSC 22000", "HACCP"
    ]
    
    CERTIFICATIONS_BY_INGREDIENT_TYPE = {
        "vitamin": ["USP", "NSF", "GMP", "Halal", "Kosher", "Non-GMO Project"],
        "protein": ["GMP", "Non-GMO Project", "USDA Organic", "Halal", "Kosher"],
        "mineral": ["USP", "NSF", "GMP", "ISO 9001"],
        "botanical": ["USDA Organic", "Non-GMO Project", "GMP", "Halal", "Kosher"],
        "excipient": ["GMP", "USP", "Food Grade Certified"],
    }
    
    TYPICAL_LEAD_TIMES = {
        "domestic": (3, 14),
        "international": (14, 45),
        "bulk": (7, 21),
        "custom": (21, 60),
    }
    
    def __init__(
        self,
        gemini_client: Optional[genai.Client] = None,
        teacher_model: str = "gemini-flash-latest",
        temperature: float = 0.7,  # Higher for variety
        verbose: bool = False,
    ):
        if not HAS_GENAI and gemini_client is not None:
            raise ImportError("google-genai not installed")
        
        self.client = gemini_client
        self.teacher_model = teacher_model
        self.temperature = temperature
        self.verbose = verbose
        
        self._generated_count = 0
    
    def generate_supplier_profile(
        self,
        ingredient_name: str,
        supplier_type: str = "unknown",
        region: str = "domestic",
        seed: Optional[int] = None,
    ) -> SyntheticSupplierProfile:
        """
        Generate a realistic synthetic supplier profile.
        
        Args:
            ingredient_name: The ingredient (e.g., "vitamin-d3-cholecalciferol")
            supplier_type: Category hint (vitamin, protein, mineral, botanical, excipient)
            region: domestic or international (affects lead times)
            seed: Random seed for reproducibility
            
        Returns:
            SyntheticSupplierProfile with realistic compliance data
        """
        if seed is not None:
            random.seed(seed)
        
        # Determine supplier name
        supplier_name = self._generate_supplier_name(region)
        
        # Use LLM for high-quality generation if available
        if self.client:
            compliance = self._generate_with_llm(ingredient_name, supplier_type, region)
        else:
            compliance = self._generate_heuristic(ingredient_name, supplier_type, region)
        
        self._generated_count += 1
        
        return SyntheticSupplierProfile(
            supplier_name=supplier_name,
            ingredient_name=ingredient_name,
            compliance=compliance,
            synthetic=True,
            generation_seed=seed,
            teacher_model=self.teacher_model if self.client else "heuristic",
        )
    
    def _generate_with_llm(
        self,
        ingredient_name: str,
        supplier_type: str,
        region: str,
    ) -> ComplianceProfile:
        """Use Teacher LLM to generate realistic compliance data."""
        
        prompt = f"""You are an expert in CPG (Consumer Packaged Goods) supply chain compliance.

Generate a realistic supplier compliance profile for:
- Ingredient: {ingredient_name}
- Supplier type: {supplier_type}
- Region: {region}

The profile should be realistic and industry-typical:
- Certifications should match what this ingredient type commonly carries
- Pharmaceutical vitamins typically have USP, GMP, Halal, Kosher
- Botanicals often have Organic, Non-GMO
- Minerals often have USP, NSF
- Lead times vary: domestic 3-14 days, international 14-45 days
- Not all suppliers have all certifications — be realistic

Return valid JSON matching this schema:
{{
  "organic_certified": <bool>,
  "fda_registered": <bool>,
  "non_gmo": <bool>,
  "grade": "<pharmaceutical|food|technical>",
  "lead_time_days": <int>,
  "certifications": ["<cert>", ...],
  "notes": "<brief realistic description>"
}}"""
        
        try:
            response = self.client.models.generate_content(
                model=self.teacher_model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=self.temperature,
                ),
            )
            
            result = json.loads(response.text.strip())
            return ComplianceProfile.from_dict(result)
            
        except Exception as e:
            if self.verbose:
                print(f"  [synthetic] LLM generation failed: {e}, falling back to heuristic")
            return self._generate_heuristic(ingredient_name, supplier_type, region)
    
    def _generate_heuristic(
        self,
        ingredient_name: str,
        supplier_type: str,
        region: str,
    ) -> ComplianceProfile:
        """Heuristic generation when LLM unavailable."""
        
        # Determine ingredient category
        category = self._categorize_ingredient(ingredient_name, supplier_type)
        
        # Base probabilities
        is_pharma = "vitamin" in category or "mineral" in category
        is_botanical = "botanical" in category
        
        # Generate certifications based on category
        possible_certs = self.CERTIFICATIONS_BY_INGREDIENT_TYPE.get(
            category, self.COMMON_CERTIFICATIONS
        )
        
        # Realistic: not all certs, subset based on "quality" of supplier
        supplier_quality = random.choice(["premium", "standard", "budget"])
        
        if supplier_quality == "premium":
            num_certs = min(len(possible_certs), random.randint(4, 6))
        elif supplier_quality == "standard":
            num_certs = min(len(possible_certs), random.randint(2, 4))
        else:
            num_certs = min(len(possible_certs), random.randint(1, 2))
        
        certifications = random.sample(possible_certs, num_certs)
        
        # Grade determination
        if is_pharma and "USP" in certifications:
            grade = "pharmaceutical"
        elif is_botanical and "USDA Organic" in certifications:
            grade = "food"  # Organic food grade
        else:
            grade = random.choice(["pharmaceutical", "food", "food"])  # Bias toward food
        
        # Lead time
        if region == "domestic":
            lead_time = random.randint(3, 14)
        else:
            lead_time = random.randint(14, 45)
        
        # Other flags
        fda_registered = random.random() > 0.15  # 85% are registered
        non_gmo = "Non-GMO Project" in certifications or random.random() > 0.6
        organic = "USDA Organic" in certifications or "EU Organic" in certifications
        
        notes = (
            f"Synthetic profile ({supplier_quality} tier). "
            f"Generated for {category} ingredient in {region} market."
        )
        
        return ComplianceProfile(
            organic_certified=organic,
            fda_registered=fda_registered,
            non_gmo=non_gmo,
            grade=grade,
            lead_time_days=lead_time,
            certifications=certifications,
            notes=notes,
            extracted_from="synthetic_generation",
            extraction_confidence=0.7 if supplier_quality == "premium" else 0.5,
        )
    
    def _categorize_ingredient(self, ingredient_name: str, supplier_type: str) -> str:
        """Categorize ingredient for realistic generation."""
        name_lower = ingredient_name.lower()
        
        if supplier_type != "unknown":
            return supplier_type
        
        if any(x in name_lower for x in ["vitamin", "cholecalciferol", "ascorbic", "tocopherol"]):
            return "vitamin"
        elif any(x in name_lower for x in ["protein", "whey", "casein", "collagen"]):
            return "protein"
        elif any(x in name_lower for x in ["calcium", "magnesium", "zinc", "iron", "selenium"]):
            return "mineral"
        elif any(x in name_lower for x in ["extract", "powder", "root", "leaf", "herb"]):
            return "botanical"
        else:
            return "excipient"
    
    def _generate_supplier_name(self, region: str) -> str:
        """Generate realistic supplier name."""
        prefixes = ["Pure", "Nutri", "Bio", "Vita", "Health", "Natural", "Global", "Premier"]
        suffixes = ["Ingredients", "Chemicals", "Nutrition", "Supplies", "Labs", "Pharma"]
        
        if region == "international":
            suffixes.extend(["China", "India", "EU", "International", "Global"])
        
        prefix = random.choice(prefixes)
        suffix = random.choice(suffixes)
        
        # Sometimes add location
        if random.random() > 0.7:
            locations = ["USA", "California", "New Jersey", "Germany", "Netherlands"]
            return f"{prefix} {suffix} ({random.choice(locations)})"
        
        return f"{prefix} {suffix}"
    
    def generate_dataset(
        self,
        ingredients: list[str],
        n_variants_per_ingredient: int = 3,
        output_path: Optional[str] = None,
    ) -> list[dict]:
        """
        Generate a full synthetic dataset.
        
        Args:
            ingredients: List of ingredient names to generate for
            n_variants_per_ingredient: Number of supplier variants per ingredient
            output_path: Optional path to save JSON dataset
            
        Returns:
            List of synthetic profiles as dictionaries
        """
        dataset = []
        
        for i, ingredient in enumerate(ingredients):
            for j in range(n_variants_per_ingredient):
                seed = i * 1000 + j  # Deterministic seeds
                
                profile = self.generate_supplier_profile(
                    ingredient_name=ingredient,
                    seed=seed,
                )
                
                dataset.append(profile.to_dict())
        
        if output_path:
            Path(output_path).write_text(
                json.dumps(dataset, indent=2),
                encoding="utf-8"
            )
            if self.verbose:
                print(f"  [synthetic] Saved {len(dataset)} profiles to {output_path}")
        
        return dataset
    
    def get_stats(self) -> dict:
        """Get generation statistics."""
        return {
            "generated_count": self._generated_count,
            "teacher_model": self.teacher_model,
            "has_llm": self.client is not None,
        }


class TeacherStudentPipeline:
    """
    Complete pipeline: Teacher generates synthetic data → Student model fine-tuned.
    
    This is a conceptual framework. In production, you would:
    1. Generate large synthetic dataset (Teacher)
    2. Format for fine-tuning (OpenAI, Gemini, or local LoRA)
    3. Fine-tune Student model
    4. Evaluate Student vs Teacher on held-out test set
    5. Deploy Student for cost-effective inference
    """
    
    def __init__(
        self,
        teacher_client: genai.Client,
        teacher_model: str = "gemini-flash-latest",
    ):
        self.teacher = SyntheticDataGenerator(
            gemini_client=teacher_client,
            teacher_model=teacher_model,
        )
    
    def generate_training_corpus(
        self,
        ingredients: list[str],
        n_variants: int = 5,
        output_dir: str = "training_data",
    ) -> Path:
        """
        Generate complete training corpus.
        
        Returns path to formatted training files.
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Generate raw data
        raw_path = output_dir / "synthetic_suppliers.json"
        dataset = self.teacher.generate_dataset(
            ingredients=ingredients,
            n_variants_per_ingredient=n_variants,
            output_path=str(raw_path),
        )
        
        # Format for fine-tuning (conversational format)
        training_examples = []
        for item in dataset:
            compliance = item["compliance"]
            training_examples.append({
                "messages": [
                    {
                        "role": "system",
                        "content": "You are a supply chain compliance extraction agent."
                    },
                    {
                        "role": "user",
                        "content": f"Extract compliance data for {item['ingredient_name']} from supplier {item['supplier_name']}"
                    },
                    {
                        "role": "assistant",
                        "content": json.dumps(compliance)
                    }
                ]
            })
        
        # Save formatted
        formatted_path = output_dir / "fine_tuning_format.jsonl"
        with open(formatted_path, "w") as f:
            for ex in training_examples:
                f.write(json.dumps(ex) + "\n")
        
        print(f"[pipeline] Training corpus generated:")
        print(f"  Raw data: {raw_path}")
        print(f"  Fine-tuning format: {formatted_path}")
        print(f"  Total examples: {len(training_examples)}")
        
        return output_dir
    
    def fine_tune_student(
        self,
        training_data_path: Path,
        student_model_name: str = "compliance-extractor-v1",
    ) -> str:
        """
        Initiate fine-tuning job (platform-specific).
        
        Note: This is a placeholder. Actual implementation would use:
        - OpenAI fine-tuning API
        - Gemini fine-tuning API  
        - Local LoRA training (Hugging Face PEFT)
        """
        raise NotImplementedError(
            "Fine-tuning implementation depends on target platform. "
            "See training_data/fine_tuning_format.jsonl for prepared data."
        )
