"""Formatting helpers for ownership demos and interfaces."""

from __future__ import annotations

from typing import List

from .models import OwnershipComparison


def format_comparison(label: str, comparison: OwnershipComparison) -> List[str]:
    lines = [
        f"Ownership example: {label}",
        f"Ownership recommendation: {comparison.recommendation.value}",
        f"Recommended option: {comparison.recommended_option_id or 'None'}",
        f"Ownership confidence: {comparison.confidence}",
    ]
    for projection in comparison.projections:
        lines.extend([
            f"{projection.option_id} acquisition cost: {_money(projection.acquisition_cost)}",
            f"{projection.option_id} protected value: {_money(projection.protected_value)}",
            f"{projection.option_id} risk cost: {_money(projection.risk_cost)}",
            f"{projection.option_id} resale value: {_money(projection.estimated_resale_value)}",
            f"{projection.option_id} cost with resale: {_money(projection.estimated_net_ownership_cost_with_resale)}",
            f"{projection.option_id} cost without resale: {_money(projection.estimated_net_ownership_cost_without_resale)}",
        ])
    lines.extend([
        f"Break-even target used price: {_money(comparison.break_even_target_price)}",
        "Break-even discount: " + (
            f"{comparison.break_even_discount_percent:.2f}%"
            if comparison.break_even_discount_percent is not None else "Unavailable"
        ),
        f"Ownership reasons: {'; '.join(comparison.reasons) or 'None'}",
        f"Ownership warnings: {'; '.join(comparison.warnings) or 'None'}",
    ])
    return lines


def _money(value) -> str:
    return f"{value:.2f}" if value is not None else "Unavailable"
