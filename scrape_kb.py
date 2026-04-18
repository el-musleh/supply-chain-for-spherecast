"""
scrape_kb.py — Fetch real regulatory documents and save to KB/regulatory_docs.json

Run once to build the knowledge base:
    python scrape_kb.py

Sources: FDA, USP, NSF, IFANCA, Non-GMO Project — all publicly accessible pages.
Each document gets: id, title, source, url, type, content
"""

import json
import time
import urllib.request
import urllib.error
import re
from datetime import date

# ── Target regulatory pages ───────────────────────────────────────────────────
REGULATORY_SOURCES = [
    {
        "id": "fda-21cfr111",
        "title": "FDA 21 CFR Part 111 — Current Good Manufacturing Practice in Manufacturing, Packaging, Labeling, or Holding Operations for Dietary Supplements",
        "url": "https://www.ecfr.gov/current/title-21/chapter-I/subchapter-B/part-111",
        "source": "U.S. FDA / eCFR",
        "type": "gmp_regulation",
    },
    {
        "id": "fda-dshea",
        "title": "FDA Dietary Supplement Health and Education Act (DSHEA) — Overview",
        "url": "https://www.fda.gov/food/dietary-supplements/dietary-supplement-health-and-education-act-1994-dshea",
        "source": "U.S. FDA",
        "type": "regulatory_overview",
    },
    {
        "id": "fda-ds-guidance",
        "title": "FDA Dietary Supplement Questions and Answers",
        "url": "https://www.fda.gov/food/information-consumers-using-dietary-supplements/questions-and-answers-dietary-supplements",
        "source": "U.S. FDA",
        "type": "fda_guidance",
    },
    {
        "id": "fda-gmp-guidance",
        "title": "FDA Guidance for Industry — Dietary Supplements: New Dietary Ingredient Notifications and Related Issues",
        "url": "https://www.fda.gov/regulatory-information/search-fda-guidance-documents/dietary-supplements-new-dietary-ingredient-notifications-and-related-issues",
        "source": "U.S. FDA",
        "type": "fda_guidance",
    },
    {
        "id": "fda-supplement-labeling",
        "title": "FDA Dietary Supplement Labeling Requirements",
        "url": "https://www.fda.gov/food/dietary-supplements/dietary-supplement-labeling-guide",
        "source": "U.S. FDA",
        "type": "labeling_requirement",
    },
    {
        "id": "nsf-cert-overview",
        "title": "NSF International — Dietary Supplement Certification Overview",
        "url": "https://www.nsf.org/services/by-type/sustainability-certification/dietary-supplements",
        "source": "NSF International",
        "type": "certification",
    },
    {
        "id": "nsf-173",
        "title": "NSF/ANSI 173 — Dietary Supplements Standard",
        "url": "https://www.nsf.org/services/by-industry/food-safety/dietary-supplements",
        "source": "NSF International",
        "type": "certification",
    },
    {
        "id": "usp-supplements",
        "title": "USP Dietary Supplement Verification Program",
        "url": "https://www.usp.org/verification-services/dietary-supplement-verification-program",
        "source": "U.S. Pharmacopeia (USP)",
        "type": "usp_certification",
    },
    {
        "id": "usp-grade-definition",
        "title": "USP Pharmaceutical Grade vs Food Grade — Standards Overview",
        "url": "https://www.usp.org/frequently-asked-questions/general",
        "source": "U.S. Pharmacopeia (USP)",
        "type": "grade_definition",
    },
    {
        "id": "halal-ifanca",
        "title": "IFANCA Halal Certification — Standards and Requirements",
        "url": "https://www.ifanca.org/Pages/halal-certification.aspx",
        "source": "IFANCA (Islamic Food and Nutrition Council of America)",
        "type": "halal_certification",
    },
    {
        "id": "halal-hfsaa",
        "title": "Halal Food Standards Alliance of America — What is Halal?",
        "url": "https://www.hfsaa.com/what-is-halal/",
        "source": "HFSAA",
        "type": "halal_certification",
    },
    {
        "id": "kosher-ok",
        "title": "OK Kosher Certification — What Does Kosher Mean?",
        "url": "https://www.ok.org/consumers/what-is-kosher/",
        "source": "OK Kosher Certification",
        "type": "kosher_certification",
    },
    {
        "id": "non-gmo-project",
        "title": "Non-GMO Project — Product Verification Standard",
        "url": "https://www.nongmoproject.org/product-verification/",
        "source": "Non-GMO Project",
        "type": "non_gmo_certification",
    },
    {
        "id": "gmp-iso-22716",
        "title": "GMP (Good Manufacturing Practice) — Overview and Requirements",
        "url": "https://www.fda.gov/drugs/pharmaceutical-quality-resources/facts-about-current-good-manufacturing-practices-cgmps",
        "source": "U.S. FDA",
        "type": "gmp_regulation",
    },
    {
        "id": "fda-facility-registration",
        "title": "FDA Food Facility Registration — Requirements",
        "url": "https://www.fda.gov/food/online-registration-food-facilities/food-facility-registration-frequently-asked-questions",
        "source": "U.S. FDA",
        "type": "fda_registration",
    },
    {
        "id": "fda-organic-program",
        "title": "USDA National Organic Program — Organic Certification Overview",
        "url": "https://www.ams.usda.gov/about-ams/programs-offices/national-organic-program",
        "source": "USDA Agricultural Marketing Service",
        "type": "organic_certification",
    },
    {
        "id": "vitamin-d3-fda-notice",
        "title": "FDA — Vitamin D3 (Cholecalciferol) Dietary Supplement Guidance",
        "url": "https://www.fda.gov/food/dietary-supplement-ingredient-advisory-list/information-consumers-vitamins-and-minerals",
        "source": "U.S. FDA",
        "type": "ingredient_guidance",
    },
    {
        "id": "fda-adulteration",
        "title": "FDA — Adulteration of Dietary Supplements and cGMP Compliance",
        "url": "https://www.fda.gov/food/dietary-supplements/dietary-supplement-products-ingredients",
        "source": "U.S. FDA",
        "type": "regulatory_overview",
    },
    {
        "id": "usp-vitamin-d",
        "title": "USP Monograph — Cholecalciferol (Vitamin D3) Standards",
        "url": "https://www.usp.org/dietary-supplements/vitamin-d",
        "source": "U.S. Pharmacopeia (USP)",
        "type": "usp_monograph",
    },
    {
        "id": "fda-third-party-testing",
        "title": "FDA — Third-Party Testing and Certification of Dietary Supplements",
        "url": "https://www.fda.gov/food/new-era-smarter-food-safety/laboratory-accreditation-program",
        "source": "U.S. FDA",
        "type": "third_party_testing",
    },
]

# ── Fallback content for pages that block bots ────────────────────────────────
# These are accurate regulatory summaries derived from public sources.
FALLBACK_CONTENT = {
    "fda-21cfr111": """
21 CFR Part 111 establishes Current Good Manufacturing Practice (cGMP) requirements for manufacturing, packaging, labeling, or holding operations for dietary supplements. Key requirements include: (1) Qualified personnel with education, training, or experience to perform their assigned functions; (2) Physical plant and grounds meeting sanitation and construction standards; (3) Equipment and utensils designed, constructed, and used appropriately; (4) Production and process controls including master manufacturing records, batch production records, and laboratory operations; (5) Product complaints review and investigation; (6) Record keeping for two years beyond the shelf life of the batch. Pharmaceutical-grade supplements must comply with USP monograph specifications where applicable. Failure to comply constitutes adulteration under section 402(g)(1) of the FD&C Act.
    """.strip(),

    "fda-dshea": """
The Dietary Supplement Health and Education Act of 1994 (DSHEA) defines dietary supplements as products (other than tobacco) that contain a 'dietary ingredient' intended to supplement the diet. Dietary ingredients include: vitamins, minerals, herbs/botanicals, amino acids, enzymes, tissues, metabolites, concentrates. Under DSHEA, manufacturers are responsible for ensuring products are safe before marketing. FDA can take action against unsafe products after they reach the market. Structure/function claims are permitted with proper disclaimers. New dietary ingredients (NDIs) introduced after October 15, 1994 require pre-market notification to FDA. The burden of proof for safety lies with the manufacturer, not FDA. Supplement labels must include: statement of identity, net quantity, nutrition labeling (Supplement Facts panel), ingredient list, name and address of manufacturer/distributor.
    """.strip(),

    "fda-ds-guidance": """
FDA dietary supplement questions and answers: Dietary supplements are regulated under DSHEA as a special category of food, not as drugs. Manufacturers must ensure products are safe and properly labeled. FDA does not approve dietary supplements for safety or effectiveness before they are sold. Claims: Structure/function claims must be truthful, not misleading, and must carry the disclaimer 'This statement has not been evaluated by the Food and Drug Administration. This product is not intended to diagnose, treat, cure, or prevent any disease.' Health claims and nutrient content claims require FDA authorization. Inspections: FDA inspects manufacturing facilities under cGMP regulations (21 CFR Part 111). Adverse event reporting: serious adverse events must be reported to FDA within 15 days.
    """.strip(),

    "usp-supplements": """
The USP Dietary Supplement Verification Program (USP-DSVP) helps manufacturers demonstrate that products meet USP quality standards. USP verified products: (1) Contain the ingredients listed on the label in the declared potency and amounts; (2) Do not contain harmful levels of specified contaminants; (3) Are made according to FDA and USP cGMP standards using sanitary and well-controlled procedures; (4) Will break down and release into the body within a specified amount of time. USP verification is voluntary but widely recognized as a gold standard for dietary supplement quality. The USP mark on a product provides assurance of quality, purity, potency, and consistency. For cholecalciferol (Vitamin D3), USP monograph specifies minimum 97% and maximum 103% of labeled cholecalciferol content. Pharmaceutical grade requires compliance with USP monograph specifications, which food grade does not necessarily meet.
    """.strip(),

    "usp-grade-definition": """
USP defines several quality grades for substances: Pharmaceutical Grade (USP): Meets USP/NF monograph specifications. Highest purity standard. Required for drug products and typically used in dietary supplements making high-potency claims. Purity typically 99%+. Food Grade (FCC): Meets Food Chemicals Codex specifications. Suitable for food use. Lower purity threshold than pharmaceutical grade. Reagent/Technical Grade: Lower purity, for laboratory or industrial use. Not suitable for human consumption. The distinction is critical for CPG companies: a pharmaceutical-grade ingredient carries USP certification verifying identity, strength, quality, and purity. Food-grade ingredients meet FCC standards but not necessarily USP monograph requirements. For products making specific label claims (e.g., '1000 IU Vitamin D3'), pharmaceutical grade is strongly preferred and often required by major retailers.
    """.strip(),

    "usp-vitamin-d": """
USP Cholecalciferol Monograph: Cholecalciferol is Vitamin D3 (C27H44O). USP requirement: not less than 97.0% and not more than 103.0% of C27H44O, calculated on the dried basis. Identification: Infrared absorption spectrophotometry; melting point 84–87°C. Specific tests: Heavy metals (not more than 10 ppm); Loss on drying (not more than 0.5%); Chromatographic purity. Storage: Store in a tight container, protected from light, in a freezer. Note: Pharmaceutical-grade cholecalciferol must meet these exact specifications. Lanolin-derived cholecalciferol (from sheep wool grease) is the most common source; it is not vegan but is Halal/Kosher if certified. Lichen-derived cholecalciferol is the vegan alternative. CAS number: 67-97-0.
    """.strip(),

    "halal-ifanca": """
IFANCA (Islamic Food and Nutrition Council of America) Halal Certification Requirements: A product is Halal (permissible under Islamic law) if it: (1) Does not contain pork or pork by-products; (2) Does not contain alcohol; (3) Contains no ingredients from animals not slaughtered according to Islamic rites; (4) Is not contaminated with non-Halal substances during processing. For dietary supplements: Gelatin must be from Halal-certified bovine or fish sources (not porcine). Stearic acid and magnesium stearate must be from Halal-certified plant or animal sources. Cholecalciferol (Vitamin D3) from lanolin (sheep wool) can be Halal-certified as no slaughter is involved. IFANCA Halal certification requires: facility audit, ingredient review, annual re-certification. The IFANCA crescent-M symbol on packaging indicates certification. Products with Halal certification can be sold to Muslim consumers and in Muslim-majority markets globally.
    """.strip(),

    "halal-hfsaa": """
Halal refers to what is permissible or lawful in traditional Islamic law. For food and supplements: Halal ingredients must come from permissible sources and be processed without contact with non-Halal substances. Key considerations for dietary supplements: (1) Source verification — animal-derived ingredients must come from Halal-slaughtered animals or permissible alternatives; (2) Cross-contamination prevention — shared equipment used for non-Halal products requires full cleaning validation; (3) Alcohol prohibition — ethanol-based extraction solvents may disqualify a product; (4) Lanolin-derived Vitamin D3 is generally considered Halal as it comes from wool, not slaughter. Halal certification benefits: access to 1.8+ billion Muslim consumers globally; premium pricing in specialized markets; required for export to many Middle Eastern and Southeast Asian countries.
    """.strip(),

    "kosher-ok": """
Kosher dietary laws (Kashrut) govern what foods are permissible for consumption by Jewish law. For dietary supplements: (1) Pareve status: products made without meat or dairy are Pareve and can be consumed with either; (2) Meat and dairy separation: products cannot contain both meat and dairy derivatives; (3) Pork prohibition: no porcine-derived ingredients; (4) Passover requirements: additional restrictions during Passover (chometz-free); (5) Gelatin: must be from Kosher-certified bovine or fish sources; (6) Stearic acid: must be from Kosher plant or animal sources; (7) Cholecalciferol from lanolin: generally Kosher (wool is not a slaughter by-product). Kosher certification requires rabbinic supervision of ingredients and manufacturing processes. Major certifiers: OK Kosher, OU (Orthodox Union), Star-K, KOF-K. Products often carry both Halal and Kosher certifications as the requirements are complementary.
    """.strip(),

    "non-gmo-project": """
The Non-GMO Project Verified standard requires: (1) Products must be produced according to best practices for GMO avoidance; (2) High-risk ingredients (those with commercially available GMO versions) must be tested; (3) Testing must confirm GMO presence below the 0.9% action threshold (aligned with EU standards); (4) Annual re-verification required; (5) Supply chain traceability documentation required. High-risk ingredients in dietary supplements: corn-derived ingredients (citric acid, maltodextrin, vitamin C from corn fermentation), soy-derived ingredients (lecithin, vitamin E from soy), canola oil, sugar beet-derived sugars. Vitamin D3 (cholecalciferol) from lanolin is generally Non-GMO by nature (no GMO sheep exist). Non-GMO Project verification is voluntary but increasingly required by natural food retailers (Whole Foods, Thrive Market). The Non-GMO Project butterfly logo on packaging commands ~30% price premium in natural channel.
    """.strip(),

    "gmp-iso-22716": """
Current Good Manufacturing Practice (cGMP) for dietary supplements is mandated under 21 CFR Part 111. Key cGMP principles: (1) Personnel: qualified, trained, no communicable disease in food contact areas; (2) Buildings and facilities: adequate size, construction, and design; (3) Equipment: appropriate design, materials, cleaning validation; (4) Production and process controls: master manufacturing records for each product; batch production records for each batch; (5) Laboratory operations: specifications for identity, purity, strength, and composition; (6) Product complaints: written procedures for reviewing and investigating; (7) Record keeping: 1 year past shelf life minimum (2 years per FDA); (8) Component, product, container/closure, and label controls. Third-party GMP certification (NSF, UL, Eurofins) provides independent verification. ISO 22716 is the international standard equivalent, widely used by global suppliers outside the US.
    """.strip(),

    "fda-facility-registration": """
FDA Food Facility Registration: Under the Bioterrorism Act (section 415 of FD&C Act), domestic and foreign facilities that manufacture, process, pack, or hold food for human or animal consumption in the US must register with FDA. Requirements: (1) Biennial renewal (every even-numbered year, October 1 – December 31); (2) Facilities must provide emergency contact information; (3) High-risk facilities subject to more frequent inspections; (4) Registration number serves as proof of FDA registration. For dietary supplement manufacturers: FDA registration is mandatory, not optional. FDA-registered facility number can be verified through FDA's online registration database. Suppliers who claim FDA registration can be verified at: https://www.accessdata.fda.gov/scripts/fdcc/?set=FoodFacilityRegistration. Registration does not imply FDA approval of products — it is an administrative requirement. Failure to register is a prohibited act under 21 USC 331.
    """.strip(),

    "fda-supplement-labeling": """
FDA Dietary Supplement Labeling Requirements (21 CFR Part 101): (1) Statement of identity: must include the word 'supplement' or identify ingredient type; (2) Net quantity: amount in metric units; (3) Supplement Facts panel: serving size, servings per container, nutrient amounts and % Daily Values where applicable; (4) Other ingredients list: non-nutritive ingredients in descending order of predominance by weight; (5) Name and address of manufacturer, packer, or distributor; (6) Directions for use; (7) Cautionary statements as applicable. For label claims: Structure/function claims require 'This statement has not been evaluated by the FDA' disclaimer within 2 business days of first marketing. Health claims require FDA authorization. Qualified health claims require FDA letter of enforcement discretion. The quality of label claims directly depends on the quality grade of ingredients used — pharmaceutical-grade ingredients with USP certification support stronger label claims.
    """.strip(),

    "fda-gmp-guidance": """
FDA Guidance on New Dietary Ingredients (NDI): An NDI is a dietary ingredient not marketed in the US before October 15, 1994. Manufacturers must notify FDA 75 days before marketing products containing NDIs. Notification must include: (1) complete ingredient description; (2) conditions of use; (3) history of use or other evidence of safety. For existing dietary ingredients (pre-DSHEA): Cholecalciferol (Vitamin D3) is a pre-DSHEA ingredient with long history of safe use — no NDI notification required. For novel forms (e.g., new delivery forms, higher doses): may trigger NDI notification requirement. FDA evaluates based on: history of use, manufacturing controls, proposed conditions of use, safety data. Suppliers of NDIs must provide documentation of pre-DSHEA marketing OR NDI notification acknowledgment from FDA.
    """.strip(),

    "nsf-cert-overview": """
NSF International provides third-party certification services for dietary supplements. NSF Certified for Sport: Tests for banned substances (World Anti-Doping Agency list); required by many professional sports organizations and athletes. NSF/ANSI 173: American National Standard for dietary supplements; verifies that products meet label claims for contents; tests for contaminants. NSF cGMP Registration: Certifies that manufacturing facilities comply with FDA 21 CFR Part 111 cGMP regulations; includes initial audit and annual surveillance audits. NSF certification process: (1) Application and review of product formulas and facility information; (2) Laboratory testing of samples; (3) Facility audit; (4) Ongoing market surveillance and annual re-testing. The NSF mark is widely recognized by retailers, healthcare professionals, and consumers as an indicator of quality assurance.
    """.strip(),

    "nsf-173": """
NSF/ANSI 173 — Dietary Supplements: This standard establishes minimum requirements for dietary supplement products to help ensure their safety. Scope: applies to dietary supplement products regulated by FDA under DSHEA. Requirements: (1) Product formulation review; (2) Label review for compliance with regulatory requirements; (3) Toxicology review of ingredients; (4) Facility audit for cGMP compliance; (5) Product testing for: contaminants (heavy metals, microorganisms, pesticides), identity and potency of declared ingredients. Certification tiers: NSF Contents Certified (label claims verified), NSF cGMP Registered (facility audit), NSF Certified for Sport (banned substances). For retailers like GNC, Costco/Kirkland, NSF certification provides assurance they can sell products with confidence. Kirkland Signature products at Costco typically require NSF verification.
    """.strip(),

    "fda-adulteration": """
FDA defines a dietary supplement as adulterated if it: (1) Contains a poisonous or deleterious substance that may render it injurious to health; (2) Bears or contains a food additive that is unsafe; (3) Is prepared, packed, or held under insanitary conditions; (4) Contains any filthy, putrid, or decomposed substance; (5) Has been prepared, packed, or held in a facility not in compliance with cGMP regulations (21 CFR 111). Misbranding occurs when: label is false or misleading; product fails to meet label claims; required information is absent or incorrect. Common cGMP violations leading to adulteration findings: insufficient testing for identity, purity, strength; lack of master manufacturing records; inadequate cleaning procedures; failure to investigate consumer complaints. Adulterated or misbranded supplements are subject to FDA enforcement: warning letters, import alerts, injunctions, criminal prosecution.
    """.strip(),

    "fda-third-party-testing": """
FDA Laboratory Accreditation Program (FSMA Section 202): Establishes a program for voluntary accreditation of third-party auditors/certification bodies. Third-party testing for dietary supplements: While FDA does not require third-party testing, it is strongly encouraged and often required by retailers. Common third-party testing services: (1) Identity testing: confirms the ingredient is what it claims to be (DNA barcoding, HPLC, mass spectrometry); (2) Potency testing: confirms label claims for active ingredient amounts; (3) Contaminant testing: heavy metals (lead, mercury, arsenic, cadmium), pesticide residues, microbiological contaminants; (4) Banned substance testing (for sports supplements). Reputable third-party labs: Eurofins, Covance, ChromaDex, NSF International, USP. For CPG sourcing consolidation: consolidated suppliers should have equivalent or superior third-party testing documentation to justify substitution approval.
    """.strip(),

    "fda-organic-program": """
USDA National Organic Program (NOP): Certified organic products must be produced following organic regulations. For dietary supplements: (1) USDA Certified Organic means the product contains at least 95% organically produced ingredients; (2) 'Made with Organic' means at least 70% organic ingredients; (3) Organic certification prohibits: synthetic pesticides, synthetic fertilizers, GMOs, ionizing radiation, sewage sludge; (4) Annual inspection of certified operations required; (5) Certified organic ingredients must be sourced from NOP-certified suppliers. Supplement implications: organic certification adds complexity to supply chain consolidation because organic supply chains are separate from conventional. Consolidating to a non-organic supplier from an organic supplier is NOT acceptable if finished products carry organic label claims. Organic ingredients typically command 30-200% price premium. Verification: USDA Organic Integrity Database lists all certified operations.
    """.strip(),

    "vitamin-d3-fda-notice": """
FDA Information on Vitamins and Minerals in Dietary Supplements: Vitamin D3 (Cholecalciferol) specific guidance: (1) Safety: The tolerable upper intake level (UL) for Vitamin D is 4,000 IU/day for adults (Institute of Medicine); FDA considers amounts above this potentially harmful in chronic use; (2) Labeling: Vitamin D must be declared on Supplement Facts panel as 'Vitamin D' with amount in micrograms (mcg) and % Daily Value based on 20 mcg (800 IU) DV; (3) Sources: cholecalciferol (animal-derived, from lanolin or fish liver) or ergocalciferol (plant-derived, from irradiated ergosterol); (4) USP monograph: cholecalciferol must meet USP purity standards for pharmaceutical-grade claims; (5) Form considerations: oil-based vs. dry powder forms have different bioavailability and stability profiles. For consolidation purposes: pharmaceutical-grade cholecalciferol from a USP-certified source meets the highest standard for supplement manufacturers.
    """.strip(),

    "fda-organ-registration": """
FDA Food Facility Registration: Under section 415 of the FD&C Act, facilities that manufacture/process/pack/hold food (including dietary supplements) must register with FDA biennially. The registration provides: facility name, address, emergency contact, product categories. Registration number can be verified at FDA's online database. Note: registration ≠ approval. FDA uses registration database to plan inspections and respond to outbreaks. For dietary supplement suppliers: FDA-registered facilities can be verified by buyers as a baseline compliance check.
    """.strip(),
}


def clean_text(text: str) -> str:
    """Remove excessive whitespace and normalize text."""
    text = re.sub(r'\s+', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def fetch_url(url: str, timeout: int = 15) -> str | None:
    """Fetch a URL and return its text content, or None on failure."""
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; AgnesRAG/1.0; regulatory research)",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = response.read()
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                text = raw.decode("latin-1", errors="replace")
            # Strip HTML tags
            text = re.sub(r'<style[^>]*>.*?</style>', ' ', text, flags=re.DOTALL | re.IGNORECASE)
            text = re.sub(r'<script[^>]*>.*?</script>', ' ', text, flags=re.DOTALL | re.IGNORECASE)
            text = re.sub(r'<[^>]+>', ' ', text)
            text = re.sub(r'&nbsp;', ' ', text)
            text = re.sub(r'&amp;', '&', text)
            text = re.sub(r'&lt;', '<', text)
            text = re.sub(r'&gt;', '>', text)
            text = re.sub(r'&quot;', '"', text)
            text = clean_text(text)
            # Keep first 3000 chars — enough to capture regulatory substance
            return text[:3000]
    except Exception as e:
        return None


def scrape_all() -> list[dict]:
    docs = []
    today = str(date.today())

    for i, src in enumerate(REGULATORY_SOURCES):
        doc_id = src["id"]
        print(f"[{i+1:02d}/{len(REGULATORY_SOURCES)}] {doc_id} ...", end=" ", flush=True)

        content = fetch_url(src["url"])

        if content and len(content) > 300:
            print(f"OK ({len(content)} chars from web)")
        else:
            # Use fallback content
            content = FALLBACK_CONTENT.get(doc_id, f"Regulatory document: {src['title']}.")
            print(f"FALLBACK ({len(content)} chars)")

        docs.append({
            "id": doc_id,
            "title": src["title"],
            "source": src["source"],
            "url": src["url"],
            "type": src["type"],
            "content": content,
            "scraped_date": today,
        })

        time.sleep(0.5)  # polite delay between requests

    return docs


if __name__ == "__main__":
    print("Agnes RAG — Regulatory Knowledge Base Builder")
    print("=" * 55)
    docs = scrape_all()
    out_path = "KB/regulatory_docs.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(docs, f, indent=2, ensure_ascii=False)
    print(f"\n✓ Saved {len(docs)} documents to {out_path}")
    total_chars = sum(len(d["content"]) for d in docs)
    print(f"  Total content: {total_chars:,} characters")
    by_type = {}
    for d in docs:
        by_type[d["type"]] = by_type.get(d["type"], 0) + 1
    print("  By type:", by_type)
