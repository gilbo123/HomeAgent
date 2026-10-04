"""Model providers: the inference servers the UI can pick from.

Each :class:`Provider` pairs an id/label with a client — an
:class:`~homeagent.ollama.OllamaClient` or an
:class:`~homeagent.openai_compat.OpenAICompatClient` — which share one
interface (``list_models`` / ``supports`` / ``stream_chat``).

A provider with an empty URL in the config is simply not offered.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .ollama import OllamaClient
from .openai_compat import OpenAICompatClient


@dataclass(frozen=True)
class Provider:
    id: str
    label: str
    url: str
    client: Any  # OllamaClient | OpenAICompatClient

    def public(self) -> dict[str, str]:
        return {"id": self.id, "label": self.label, "url": self.url}


class ProviderRegistry:
    def __init__(self, providers: list[Provider], default_id: str) -> None:
        self._providers = {p.id: p for p in providers}
        self.default_id = default_id if default_id in self._providers else next(iter(self._providers))

    def get(self, provider_id: str | None) -> Provider:
        """The provider with that id, or the default for unknown/missing ids."""
        return self._providers.get(provider_id or "", self._providers[self.default_id])

    def public(self) -> list[dict[str, str]]:
        return [p.public() for p in self._providers.values()]


def build_providers(ollama: OllamaClient, openai_compat: list[tuple[str, str, str, str]],
                    temperature: float, default_id: str) -> ProviderRegistry:
    """Ollama plus each ``(id, label, base_url, api_key)`` with a non-empty URL."""
    providers = [Provider("ollama", "Ollama", ollama.host, ollama)]
    for pid, label, url, key in openai_compat:
        if url:
            providers.append(Provider(pid, label, url, OpenAICompatClient(url, key, temperature)))
    return ProviderRegistry(providers, default_id)
