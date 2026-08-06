"""Helpers for concise, dashboard-ready decision explanations."""

from typing import List, Sequence

from .models import DecisionFactor


def key_reasons(factors: Sequence[DecisionFactor], limit: int = 5) -> List[str]:
    ranked = sorted(factors, key=lambda item: abs(item.score_impact), reverse=True)
    reasons = [item.explanation for item in ranked if item.score_impact != 0]
    return reasons[:limit]


def format_report_summary(label: str, report) -> List[str]:
    fair_price = "unavailable" if report.expected_fair_price is None else f"{report.expected_fair_price:.2f}"
    return [
        f"Decision example: {label}",
        f"Recommendation: {report.recommendation.value}",
        f"Buy score: {report.buy_score}",
        f"Confidence: {report.confidence}",
        f"Expected fair price: {fair_price}",
        f"New versus used: {report.new_vs_used_recommendation.value}",
        f"Key reasons: {'; '.join(report.reasons) if report.reasons else 'None'}",
        f"Warnings: {'; '.join(report.warnings) if report.warnings else 'None'}",
    ]
