"""Tests for connector execution and operational health monitoring."""

from __future__ import annotations

import ast
import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import List


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from connectors import (
    Connector,
    ConnectorManager,
    ConnectorStatus,
    Listing,
    MockConnector,
    SearchQuery,
)


class StaticConnector(Connector):
    def __init__(self, listings: List[Listing], **kwargs) -> None:
        super().__init__(**kwargs)
        self.listings = listings
        self.search_attempts = 0

    def search(self, query: SearchQuery) -> List[Listing]:
        self.search_attempts += 1
        return self.listings


class ConnectorTests(unittest.TestCase):
    def test_healthy_connector(self) -> None:
        connector = MockConnector(retry_count=2)
        result, _, delays = self.run_manager([connector])
        connector_result = result.connector_results[0]

        self.assertEqual(connector_result.health.status, ConnectorStatus.HEALTHY)
        self.assertEqual(len(connector_result.listings), 1)
        self.assertEqual(connector.search_attempts, 1)
        self.assertEqual(delays, [])

    def test_empty_response_is_healthy_without_previous_results(self) -> None:
        connector = MockConnector(scenario="empty")
        result, _, _ = self.run_manager([connector])
        self.assertEqual(
            result.connector_results[0].health.status, ConnectorStatus.HEALTHY
        )

    def test_empty_response_is_degraded_after_previous_results(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            data_directory = Path(temporary_directory)
            connector = MockConnector()
            manager = ConnectorManager(
                [connector], data_directory, sleep_func=lambda _: None
            )
            manager.search(SearchQuery("Sony A7 IV"))
            connector.scenario = "empty"
            result = manager.search(SearchQuery("Sony A7 IV"))

        health = result.connector_results[0].health
        self.assertEqual(health.status, ConnectorStatus.DEGRADED)
        self.assertEqual(health.consecutive_failures, 0)
        self.assertIsNotNone(health.last_success_at)

    def test_partial_data_is_degraded_and_successful(self) -> None:
        result, _, _ = self.run_manager([MockConnector(scenario="partial")])
        health = result.connector_results[0].health
        self.assertEqual(health.status, ConnectorStatus.DEGRADED)
        self.assertEqual(health.consecutive_failures, 0)
        self.assertIsNotNone(health.last_success_at)

    def test_successful_retry_after_timeout(self) -> None:
        connector = MockConnector(scenario="timeout_then_success", retry_count=2)
        result, _, delays = self.run_manager([connector])
        self.assertEqual(
            result.connector_results[0].health.status, ConnectorStatus.HEALTHY
        )
        self.assertEqual(connector.search_attempts, 2)
        self.assertEqual(delays, [1.0])

    def test_repeated_timeout_fails_after_retry_limit(self) -> None:
        connector = MockConnector(scenario="timeout", retry_count=2)
        result, _, delays = self.run_manager([connector])
        health = result.connector_results[0].health
        self.assertEqual(health.status, ConnectorStatus.FAILED)
        self.assertEqual(health.consecutive_failures, 1)
        self.assertEqual(connector.search_attempts, 3)
        self.assertEqual(delays, [1.0, 2.0])

    def test_authentication_failure_is_not_retried(self) -> None:
        connector = MockConnector(
            scenario="authentication_failure", retry_count=3
        )
        result, _, delays = self.run_manager([connector])
        self.assertEqual(
            result.connector_results[0].health.status, ConnectorStatus.FAILED
        )
        self.assertEqual(connector.search_attempts, 1)
        self.assertEqual(delays, [])

    def test_malformed_data_is_not_retried(self) -> None:
        connector = MockConnector(scenario="malformed", retry_count=3)
        result, _, delays = self.run_manager([connector])
        self.assertEqual(
            result.connector_results[0].health.status, ConnectorStatus.FAILED
        )
        self.assertEqual(connector.search_attempts, 1)
        self.assertEqual(delays, [])

    def test_failed_connector_does_not_stop_another(self) -> None:
        failed = MockConnector(scenario="timeout", name="failed", retry_count=0)
        healthy = MockConnector(name="healthy")
        result, _, _ = self.run_manager([failed, healthy])
        self.assertEqual(len(result.connector_results), 2)
        self.assertEqual(len(result.listings), 1)
        self.assertEqual(result.connector_results[0].health.status, ConnectorStatus.FAILED)
        self.assertEqual(result.connector_results[1].health.status, ConnectorStatus.HEALTHY)

    def test_health_and_incident_csv_persistence(self) -> None:
        result, data_directory, _ = self.run_manager(
            [MockConnector(scenario="timeout", retry_count=0)]
        )
        with (data_directory / "connector_health.csv").open(newline="") as source:
            health_rows = list(csv.DictReader(source))
        with (data_directory / "connector_incidents.csv").open(newline="") as source:
            incident_rows = list(csv.DictReader(source))

        self.assertEqual(len(health_rows), 1)
        self.assertEqual(health_rows[0]["status"], "FAILED")
        self.assertEqual(len(incident_rows), 1)
        self.assertEqual(incident_rows[0]["error_type"], "timeout")
        self.assertEqual(result.connector_results[0].incident_count, 1)

    def test_duplicate_listings_from_same_connector_are_removed(self) -> None:
        sample = MockConnector().search(SearchQuery("Sony A7 IV"))[0]
        connector = StaticConnector(
            [sample, sample], name="mock-marketplace", source_type="mock"
        )
        result, _, _ = self.run_manager([connector])
        self.assertEqual(len(result.listings), 1)

    def test_failed_connector_creates_repair_proposal(self) -> None:
        _, data_directory, _ = self.run_manager(
            [MockConnector(scenario="authentication_failure")]
        )
        proposals = json.loads(
            (data_directory / "repair_proposals.json").read_text()
        )
        self.assertEqual(len(proposals), 1)
        self.assertEqual(proposals[0]["connector_name"], "mock-marketplace")
        self.assertEqual(proposals[0]["repair_status"], "proposed")

    def test_identical_incident_is_updated_not_duplicated(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            data_directory = Path(temporary_directory)
            connector = MockConnector(scenario="timeout", retry_count=0)
            manager = ConnectorManager(
                [connector], data_directory, sleep_func=lambda _: None
            )
            manager.search(SearchQuery("Sony A7 IV"))
            manager.search(SearchQuery("Sony A7 IV"))
            with (data_directory / "connector_incidents.csv").open(newline="") as source:
                rows = list(csv.DictReader(source))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["resolved"], "false")

    def test_changed_error_resolves_old_incident_and_creates_new_one(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            data_directory = Path(temporary_directory)
            connector = MockConnector(scenario="timeout", retry_count=0)
            manager = ConnectorManager(
                [connector], data_directory, sleep_func=lambda _: None
            )
            manager.search(SearchQuery("Sony A7 IV"))
            connector.scenario = "authentication_failure"
            manager.search(SearchQuery("Sony A7 IV"))
            with (data_directory / "connector_incidents.csv").open(newline="") as source:
                rows = list(csv.DictReader(source))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["resolved"], "true")
        self.assertEqual(rows[1]["error_type"], "authentication")

    def test_recovery_resets_failures_and_resolves_incident(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            data_directory = Path(temporary_directory)
            connector = MockConnector(scenario="timeout", retry_count=0)
            manager = ConnectorManager(
                [connector], data_directory, sleep_func=lambda _: None
            )
            failed = manager.search(SearchQuery("Sony A7 IV"))
            connector.scenario = "healthy"
            recovered = manager.search(SearchQuery("Sony A7 IV"))
            with (data_directory / "connector_incidents.csv").open(newline="") as source:
                rows = list(csv.DictReader(source))

        self.assertEqual(failed.connector_results[0].health.consecutive_failures, 1)
        self.assertEqual(recovered.connector_results[0].health.status, ConnectorStatus.HEALTHY)
        self.assertEqual(recovered.connector_results[0].health.consecutive_failures, 0)
        self.assertEqual(rows[0]["resolved"], "true")
        self.assertTrue(rows[0]["resolved_at"])

    def test_disabled_connector_is_not_executed(self) -> None:
        connector = MockConnector(enabled=False)
        result, _, _ = self.run_manager([connector])
        self.assertEqual(
            result.connector_results[0].health.status, ConnectorStatus.DISABLED
        )
        self.assertEqual(connector.search_attempts, 0)

    def test_connector_sources_parse_as_python_3_9(self) -> None:
        for source_path in (PROJECT_ROOT / "src" / "connectors").glob("*.py"):
            with self.subTest(source=source_path.name):
                ast.parse(source_path.read_text(), feature_version=(3, 9))

    def run_manager(self, connectors):
        temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(temporary_directory.cleanup)
        data_directory = Path(temporary_directory.name)
        delays = []
        manager = ConnectorManager(
            connectors,
            data_directory,
            sleep_func=lambda delay: delays.append(delay),
        )
        return manager.search(SearchQuery("Sony A7 IV")), data_directory, delays


if __name__ == "__main__":
    unittest.main()
