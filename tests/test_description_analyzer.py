"""Tests for deterministic Description Intelligence V1."""

from __future__ import annotations

import ast
import sys
import unittest
from dataclasses import replace
from datetime import date, datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from analyzers import DescriptionAnalyzer, apply_analysis_to_listing
from connectors.models import Listing


class DescriptionAnalyzerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.analyzer = DescriptionAnalyzer(as_of=date(2026, 4, 15))

    def test_italian_shutter_count_with_separator(self) -> None:
        self.assertEqual(self.analyze("Ha 60.000 scatti").shutter_count, 60_000)

    def test_english_shutter_count(self) -> None:
        self.assertEqual(self.analyze("Shutter count 60000").shutter_count, 60_000)
        self.assertEqual(self.analyze("60,000 actuations").shutter_count, 60_000)

    def test_compact_shutter_count(self) -> None:
        self.assertEqual(self.analyze("Circa 60k scatti").shutter_count, 60_000)
        self.assertEqual(self.analyze("Otturatore a 60 mila").shutter_count, 60_000)

    def test_unrelated_numbers_are_not_shutter_counts(self) -> None:
        analysis = self.analyze("€1,200 anno 2024 sensore 33 MP zoom 24-70mm")
        self.assertIsNone(analysis.shutter_count)
        self.assertFalse(any(fact.fact_type == "shutter_count" for fact in analysis.extracted_facts))

    def test_exact_warranty_date(self) -> None:
        analysis = self.analyze("Garanzia fino al 30/04/2027")
        self.assertEqual(analysis.warranty_until, "2027-04-30")

    def test_month_year_warranty(self) -> None:
        self.assertEqual(self.analyze("Garanzia fino ad aprile 2027").warranty_until, "2027-04-30")
        self.assertEqual(self.analyze("Warranty until April 2027").warranty_until, "2027-04-30")

    def test_relative_warranty_uses_as_of(self) -> None:
        self.assertEqual(self.analyze("Ancora 12 mesi di garanzia").warranty_until, "2027-04-15")

    def test_imprecise_warranty_is_claim_not_date(self) -> None:
        analysis = self.analyze("Acquistata quattro mesi fa con garanzia italiana")
        self.assertIsNone(analysis.warranty_until)
        self.assertTrue(analysis.seller_claims)
        self.assertTrue(analysis.warnings)

    def test_invoice_present_and_absent(self) -> None:
        self.assertTrue(self.analyze("Fattura presente").invoice_available)
        self.assertFalse(self.analyze("Senza fattura").invoice_available)
        self.assertTrue(self.analyze("Proof of purchase").invoice_available)

    def test_generic_documentation_does_not_imply_invoice(self) -> None:
        self.assertIsNone(self.analyze("Documentazione completa").invoice_available)

    def test_original_box_present_and_absent(self) -> None:
        self.assertTrue(self.analyze("Scatola originale").original_box_available)
        self.assertFalse(self.analyze("Scatola non inclusa").original_box_available)
        self.assertTrue(self.analyze("Original box").original_box_available)

    def test_three_original_sony_batteries(self) -> None:
        analysis = self.analyze("Tre batterie originali Sony")
        self.assertEqual(analysis.accessories, ["Sony original battery"] * 3)
        english = self.analyze("Three original Sony batteries")
        self.assertEqual(english.accessories, ["Sony original battery"] * 3)

    def test_identifiable_third_party_accessories(self) -> None:
        analysis = self.analyze(
            "SmallRig 3667 cage, filtro NiSi True Color 82mm, DJI RS 4 e caricatore doppio Patona"
        )
        joined = " | ".join(analysis.accessories).casefold()
        self.assertIn("smallrig", joined)
        self.assertIn("nisi", joined)
        self.assertIn("dji rs 4", joined)
        self.assertIn("patona", joined)

    def test_front_element_crack_is_specific_and_critical(self) -> None:
        defect = self.analyze("Lente frontale crepata", "Lens").defects[0]
        self.assertEqual(defect.category, "cracks")
        self.assertEqual(defect.severity, "critical")
        self.assertEqual(defect.affected_component, "front element")

    def test_front_element_scratch_uses_scratches(self) -> None:
        defect = self.analyze("Graffio evidente sulla lente frontale", "Lens").defects[0]
        self.assertEqual(defect.category, "scratches")
        self.assertEqual(defect.affected_component, "front element")

    def test_vague_optical_damage_uses_optical_damage(self) -> None:
        defect = self.analyze("Presenta un danno ottico", "Lens").defects[0]
        self.assertEqual(defect.category, "optical_damage")

    def test_fungus_and_haze(self) -> None:
        fungus = self.analyze("Presenza di funghi", "Lens").defects[0]
        haze = self.analyze("Internal haze", "Lens").defects[0]
        self.assertEqual(fungus.category, "fungus")
        self.assertEqual(haze.category, "haze")
        self.assertEqual(fungus.severity, "unknown")

    def test_damaged_filter_thread(self) -> None:
        defect = self.analyze("Filettatura filtro ammaccata", "Lens").defects[0]
        self.assertEqual(defect.category, "mechanical_damage")
        self.assertEqual(defect.affected_component, "filter thread")

    def test_autofocus_failure(self) -> None:
        defect = self.analyze("Autofocus non funziona", "Lens").defects[0]
        self.assertEqual(defect.category, "electronic_damage")
        self.assertEqual(defect.affected_component, "autofocus system")
        self.assertEqual(defect.severity, "major")

    def test_minor_cosmetic_scratch(self) -> None:
        defect = self.analyze("Piccolo graffio sulla scocca", "Camera").defects[0]
        self.assertEqual(defect.category, "cosmetic_damage")
        self.assertEqual(defect.severity, "minor")
        self.assertEqual(defect.affected_component, "body")

    def test_negated_defects_do_not_create_defects(self) -> None:
        for text in ("Nessun graffio", "Senza funghi", "Non ha preso acqua"):
            with self.subTest(text=text):
                analysis = self.analyze(text, "Lens")
                self.assertEqual(analysis.defects, [])
                self.assertTrue(any(fact.fact_type == "verified_negative" for fact in analysis.extracted_facts))

    def test_minimization_is_separate_and_does_not_lower_defect(self) -> None:
        analysis = self.analyze("Lente frontale crepata ma non influisce sulle foto", "Lens")
        self.assertEqual(analysis.defects[0].severity, "critical")
        self.assertIn("non influisce sulle foto", [claim.casefold() for claim in analysis.seller_claims])
        self.assertFalse(any("contradict" in warning.casefold() for warning in analysis.warnings))

    def test_cosmetic_defect_and_functional_claim_do_not_contradict(self) -> None:
        analysis = self.analyze(
            "Piccolo graffio sulla scocca. Perfettamente funzionante.", "Camera"
        )
        self.assertEqual(len(analysis.defects), 1)
        self.assertFalse(any("contradict" in warning.casefold() for warning in analysis.warnings))

    def test_autofocus_failure_and_functional_claim_contradict(self) -> None:
        analysis = self.analyze(
            "Autofocus non funziona. Perfettamente funzionante.", "Lens"
        )
        self.assertTrue(any("contradict" in warning.casefold() for warning in analysis.warnings))
        self.assertLess(analysis.confidence, 100)

    def test_no_defects_claim_and_crack_contradict(self) -> None:
        analysis = self.analyze("Lente frontale crepata. Nessun difetto.", "Lens")
        self.assertEqual(analysis.defects[0].category, "cracks")
        self.assertTrue(any("contradict" in warning.casefold() for warning in analysis.warnings))

    def test_camera_missing_shutter_count(self) -> None:
        analysis = self.analyze("Fattura presente", "Camera")
        self.assertIn("shutter count", analysis.missing_information)

    def test_lens_missing_optical_information(self) -> None:
        analysis = self.analyze("Scatola originale", "Lens")
        self.assertIn("optical condition", analysis.missing_information)

    def test_analysis_applies_to_frozen_listing(self) -> None:
        listing = self.listing()
        analysis = self.analyze("60000 scatti, fattura presente e scatola originale", "Camera")
        enriched = apply_analysis_to_listing(listing, analysis)
        self.assertIsNot(enriched, listing)
        self.assertIsNone(listing.shutter_count)
        self.assertEqual(enriched.shutter_count, 60_000)
        self.assertTrue(enriched.invoice_available)

    def test_listing_integration_preserves_existing_structured_facts(self) -> None:
        listing = replace(
            self.listing(),
            shutter_count=12_000,
            warranty_until="2027-04-30",
            condition="Used - Excellent",
        )
        analysis = self.analyze("Scatola originale", "Camera")
        enriched = apply_analysis_to_listing(listing, analysis)
        self.assertEqual(enriched.shutter_count, 12_000)
        self.assertEqual(enriched.warranty_until, "2027-04-30")
        self.assertNotIn("shutter count", enriched.missing_information)
        self.assertNotIn("warranty status", enriched.missing_information)
        self.assertNotIn("condition details", enriched.missing_information)

    def test_every_extracted_fact_has_exact_source_text_and_span(self) -> None:
        title = "Sony A7 IV"
        description = "60000 scatti, fattura presente, scatola originale"
        combined = f"{title}\n{description}"
        analysis = self.analyzer.analyze(title, description, "Camera")
        self.assertTrue(analysis.extracted_facts)
        for fact in analysis.extracted_facts:
            self.assertEqual(
                combined[fact.start_position:fact.end_position], fact.source_text
            )

    def test_analysis_confidence_is_0_to_100(self) -> None:
        confidence = self.analyze("", "Camera").confidence
        self.assertIsInstance(confidence, int)
        self.assertGreaterEqual(confidence, 10)
        self.assertLessEqual(confidence, 100)

    def test_analyzer_sources_parse_as_python_3_9(self) -> None:
        for source_path in (PROJECT_ROOT / "src" / "analyzers").glob("*.py"):
            with self.subTest(source=source_path.name):
                ast.parse(source_path.read_text(), feature_version=(3, 9))

    def analyze(self, description: str, category: str = "Camera"):
        return self.analyzer.analyze("Test listing", description, category)

    @staticmethod
    def listing() -> Listing:
        return Listing(
            external_id="1", source="Test", title="Camera", url="https://example.invalid/1",
            price=1000, currency="EUR", condition="Unknown", location="Rome",
            seller="Seller", description="", detected_at=datetime.now(timezone.utc),
            raw_data={}, connector_name="test",
        )


if __name__ == "__main__":
    unittest.main()
