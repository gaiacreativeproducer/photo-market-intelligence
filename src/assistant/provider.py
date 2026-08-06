"""Assistant provider boundary and deterministic implementation."""
from __future__ import annotations

from abc import ABC, abstractmethod


class AssistantProvider(ABC):
    @abstractmethod
    def query(self, request): ...
    @abstractmethod
    def capabilities(self): ...


class ExternalAIProvider(AssistantProvider):
    enabled = False
    context_policy = "allowlisted structured facts only; no files, payloads, personal data, or credentials"
    def query(self, request): raise RuntimeError("External AI provider is disabled in V1")
    def capabilities(self): return {"enabled": False, "provider": "external", "reason": "not configured in V1"}
