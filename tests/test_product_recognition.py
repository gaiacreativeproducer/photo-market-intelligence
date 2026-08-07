"""Tests for deterministic Product Recognition V1."""

from __future__ import annotations

import ast
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from catalog import load_product_aliases, load_products
from connectors.models import Listing
from knowledge import ProductMatcher, recognize_listing
from knowledge.models import ProductMatchCandidate
from knowledge.ranking import score_candidate, select_primary


class ProductRecognitionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        data = PROJECT_ROOT / "data"
        cls.products = load_products(data / "products.csv")
        cls.aliases = load_product_aliases(data / "product_aliases.csv", cls.products)
        cls.matcher = ProductMatcher(cls.products, cls.aliases)

    def test_sony_a7_iv_exact_alias(self) -> None:
        result = self.matcher.recognize("Sony A7 IV body", "")
        self.assertEqual(result.product_id, "sony-alpha-a7-iv")
        self.assertGreaterEqual(result.confidence, 90)
        self.assertFalse(result.ambiguous)
        self.assertIn("Provenance: stored alias.", result.candidates[0].reasons)

    def test_sony_model_code(self) -> None:
        result = self.matcher.recognize("Sony ILCE-7M4", "")
        self.assertEqual(result.product_id, "sony-alpha-a7-iv")
        self.assertEqual(result.candidates[0].matched_alias, "ilce-7m4")

    def test_a7_numeric_version(self) -> None:
        result = self.matcher.recognize("Sony A7 4 corpo", "")
        self.assertEqual(result.product_id, "sony-alpha-a7-iv")
        self.assertEqual(result.candidates[0].match_type, "normalized_alias")
        self.assertIn(
            "Provenance: derived normalized form from stored alias.",
            result.candidates[0].reasons,
        )

    def test_a7_versions_are_distinguished(self) -> None:
        for text, product_id in (
            ("Sony A7 III", "sony-alpha-a7-iii"),
            ("Sony A7 IV", "sony-alpha-a7-iv"),
            ("Sony A7 V", "sony-alpha-a7-v"),
        ):
            with self.subTest(text=text):
                self.assertEqual(self.matcher.recognize(text, "").product_id, product_id)

    def test_sigma_first_and_second_generation(self) -> None:
        first = self.matcher.recognize("Sigma 24-70 DG DN prima serie", "")
        second = self.matcher.recognize("Sigma 24-70 DG DN II", "")
        self.assertEqual(first.product_id, "sigma-24-70mm-f2-8-dg-dn-art")
        self.assertEqual(second.product_id, "sigma-24-70mm-f2-8-dg-dn-ii-art")
        self.assertNotIn(
            "sigma-24-70mm-f2-8-dg-dn-art",
            [candidate.product_id for candidate in second.candidates],
        )

    def test_sony_gm_generations(self) -> None:
        first = self.matcher.recognize("Sony 24-70 GM prima serie", "")
        second = self.matcher.recognize("Sony 24-70 GM2", "")
        self.assertEqual(first.product_id, "sony-fe-24-70mm-f2-8-gm")
        self.assertEqual(second.product_id, "sony-fe-24-70mm-f2-8-gm-ii")

    def test_lumix_and_nikon_compact_versions(self) -> None:
        self.assertEqual(
            self.matcher.recognize("Panasonic Lumix S5D", "").product_id,
            "panasonic-lumix-s5d",
        )
        self.assertEqual(
            self.matcher.recognize("Lumix S5II", "").product_id,
            "panasonic-lumix-s5-ii",
        )
        self.assertEqual(
            self.matcher.recognize("Nikon Z6III", "").product_id,
            "nikon-z6-iii",
        )

    def test_vintage_lenses(self) -> None:
        self.assertEqual(
            self.matcher.recognize("Canon FD 50mm f/1.2 L", "").product_id,
            "canon-fd-50mm-f1-2-l",
        )
        self.assertEqual(
            self.matcher.recognize(
                "Contax Carl Zeiss Planar 85mm f/1.4 AEG", ""
            ).product_id,
            "contax-carl-zeiss-planar-85mm-f1-4-aeg",
        )

    def test_camera_lens_and_gimbal_kit(self) -> None:
        result = self.matcher.recognize(
            "Sony A7 IV + Sigma 24-70 DG DN II + DJI RS 4", ""
        )
        self.assertEqual(result.product_id, "sony-alpha-a7-iv")
        self.assertFalse(result.ambiguous)
        self.assertEqual(len(result.candidates), 3)
        self.assertTrue(any("kit" in warning.casefold() for warning in result.warnings))

    def test_camera_and_accessory_keep_camera_primary(self) -> None:
        result = self.matcher.recognize("Sony A7 IV con DJI RS 4", "")
        self.assertEqual(result.product_id, "sony-alpha-a7-iv")
        self.assertFalse(result.ambiguous)
        self.assertEqual(len(result.candidates), 2)

    def test_two_camera_bodies_are_ambiguous(self) -> None:
        result = self.matcher.recognize("Sony A7 IV + Sony A7 III", "")
        self.assertIsNone(result.product_id)
        self.assertTrue(result.ambiguous)

    def test_sold_separately_is_not_assumed_to_be_a_kit(self) -> None:
        for phrase in ("body sold separately", "corpo venduto separatamente"):
            with self.subTest(phrase=phrase):
                result = self.matcher.recognize(
                    f"Sigma 24-70 DG DN II + Sony A7 IV {phrase}", ""
                )
                self.assertTrue(any("separately" in item for item in result.warnings))
                self.assertFalse(any("kit listing" in item for item in result.warnings))

    def test_title_description_version_conflict(self) -> None:
        result = self.matcher.recognize("Sony A7 IV", "In realtà Sony A7 III")
        self.assertIsNone(result.product_id)
        self.assertTrue(result.ambiguous)
        self.assertTrue(any("incompatible" in item for item in result.warnings))
        conflicting = next(
            candidate for candidate in result.candidates
            if candidate.product_id == "sony-alpha-a7-iii"
        )
        self.assertIn("Title-description incompatible version: -30.", conflicting.reasons)

    def test_negated_product_version_is_not_a_candidate(self) -> None:
        result = self.matcher.recognize("Sony A7 IV, non A7 III", "")
        self.assertEqual(result.product_id, "sony-alpha-a7-iv")
        self.assertNotIn(
            "sony-alpha-a7-iii", [candidate.product_id for candidate in result.candidates]
        )

    def test_compatible_brand_is_not_a_camera_body(self) -> None:
        result = self.matcher.recognize("Flash compatible with Sony", "")
        self.assertIsNone(result.product_id)
        self.assertEqual(result.candidates, [])
        self.assertEqual(result.unmatched_terms, [])

    def test_camera_compatibility_accessory_matrix_is_not_camera_body(self) -> None:
        titles = (
            "underwater housing for Sony A7 IV",
            "cage for Sony A7 IV",
            "battery for Sony A7 IV",
            "charger for Sony A7 IV",
            "screen protector Sony A7 IV",
            "camera strap compatible with Sony A7 IV",
            "L bracket for Sony A7 IV",
            "dummy battery Sony A7 IV",
            "grip for Sony A7 IV",
            "manual/book for Sony A7 IV",
            "box only Sony A7 IV",
            "scafandro subacqueo per Sony A7 IV",
            "custodia compatibile con Sony A7 IV",
        )
        for title in titles:
            with self.subTest(title=title):
                result = self.matcher.recognize(title, "")
                self.assertNotEqual(result.product_id, "sony-alpha-a7-iv")
                self.assertTrue(any(
                    "compatibility reference" in warning
                    for warning in result.warnings
                ))

    def test_supported_accessory_wins_over_camera_compatibility_reference(self) -> None:
        result = self.matcher.recognize(
            "Sony VG-C4EM battery grip for Sony A7 IV", ""
        )
        self.assertEqual(result.product_id, "sony-vg-c4em")
        self.assertEqual(result.recognized_category, "Grip")

    def test_camera_body_and_included_accessory_remain_camera(self) -> None:
        for title in (
            "Sony A7 IV body with battery",
            "Sony A7 IV corpo macchina con caricatore",
            "Sony Alpha a7 IV ILCE-7M4",
        ):
            with self.subTest(title=title):
                self.assertEqual(
                    self.matcher.recognize(title, "").product_id,
                    "sony-alpha-a7-iv",
                )

    def test_focal_length_and_aperture_are_not_products(self) -> None:
        result = self.matcher.recognize("Obiettivo 24-70mm f/2.8 anno 2024", "")
        self.assertIsNone(result.product_id)
        self.assertEqual(result.candidates, [])

    def test_unmatched_listing(self) -> None:
        result = self.matcher.recognize("Generic camera in good condition", "")
        self.assertIsNone(result.product_id)
        self.assertFalse(result.ambiguous)

    def test_conservative_unmatched_terms(self) -> None:
        result = self.matcher.recognize("Sony Mystery X100, excellent condition €500", "")
        self.assertEqual(result.unmatched_terms, ["sony mystery x100 excellent"])
        plain = self.matcher.recognize("Excellent condition, invoice and box", "")
        self.assertEqual(plain.unmatched_terms, [])

    def test_source_spans_are_exact(self) -> None:
        title = "Kit Sony A7IV"
        description = "Include DJI RS 4"
        source = f"{title}\n{description}"
        result = self.matcher.recognize(title, description)
        for candidate in result.candidates:
            self.assertEqual(
                source[candidate.source_start:candidate.source_end],
                candidate.matched_text,
            )

    def test_title_match_bonus(self) -> None:
        title = self.matcher.recognize("DJI RS 4", "").candidates[0]
        description = self.matcher.recognize("Listing", "DJI RS 4").candidates[0]
        self.assertEqual(title.score - description.score, 5)
        self.assertIn("Title match: +5.", title.reasons)

    def test_title_description_agreement_bonus(self) -> None:
        candidate = self.matcher.recognize("DJI RS 4", "DJI RS 4 included").candidates[0]
        self.assertIn("Title and description agree: +3.", candidate.reasons)

    def test_primary_threshold_and_margin_rules(self) -> None:
        low = self.candidate("one", 69)
        product_id, ambiguous, warnings = select_primary([low], set())
        self.assertIsNone(product_id)
        self.assertFalse(ambiguous)
        self.assertTrue(any("below 70" in warning for warning in warnings))

        top = self.candidate("one", 80)
        seven = self.candidate("two", 73)
        pair = {frozenset(("one", "two"))}
        self.assertEqual(select_primary([top, seven], pair)[:2], (None, True))
        eight = self.candidate("two", 72)
        self.assertEqual(select_primary([top, eight], pair)[:2], ("one", False))

    def test_fuzzy_match_never_becomes_primary(self) -> None:
        result = self.matcher.recognize("Nikon ZG III", "")
        fuzzy = [item for item in result.candidates if item.match_type == "fuzzy_fallback"]
        self.assertTrue(fuzzy)
        self.assertLessEqual(fuzzy[0].score, 55)
        self.assertIsNone(result.product_id)
        self.assertTrue(any("Fuzzy" in warning for warning in result.warnings))
        source = "Nikon ZG III\n"
        self.assertEqual(
            source[fuzzy[0].source_start:fuzzy[0].source_end],
            fuzzy[0].matched_text,
        )

    def test_every_score_adjustment_is_traceable(self) -> None:
        score, reasons = score_candidate(
            "brand_model_match", title_match=True, version_match=True,
            mount_match=True, conflicting_version=True,
        )
        adjustments = 75 + 5 + 5 + 3 - 30
        self.assertEqual(score, adjustments)
        self.assertEqual(len(reasons), 5)
        for candidate in self.matcher.recognize("Sony A7 IV", "").candidates:
            self.assertTrue(candidate.reasons)
            self.assertTrue(any("Provenance:" in reason for reason in candidate.reasons))

    def test_recognize_listing_does_not_mutate_frozen_listing(self) -> None:
        listing = self.listing("Sony A7 IV", "ILCE-7M4")
        result = recognize_listing(listing, self.products, self.aliases)
        self.assertEqual(result.product_id, "sony-alpha-a7-iv")
        self.assertEqual(listing.title, "Sony A7 IV")

    def test_sources_parse_as_python_3_9(self) -> None:
        for source_path in (PROJECT_ROOT / "src" / "knowledge").glob("*.py"):
            with self.subTest(source=source_path.name):
                ast.parse(source_path.read_text(), feature_version=(3, 9))

    @staticmethod
    def candidate(product_id: str, score: int) -> ProductMatchCandidate:
        return ProductMatchCandidate(
            product_id, product_id, product_id, "token_match", score,
            ["test"], 0, len(product_id),
        )

    @staticmethod
    def listing(title: str, description: str) -> Listing:
        return Listing(
            "1", "test", title, "https://example.invalid/1", None, "EUR",
            "Unknown", "", "", description, datetime.now(timezone.utc), {}, "test",
        )


if __name__ == "__main__":
    unittest.main()
