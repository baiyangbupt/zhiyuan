from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.harness.binding import BindingError, ThreadBinding, ToolContext


@dataclass(frozen=True)
class TrustedToolContext:
    binding: ThreadBinding

    @classmethod
    def from_binding(cls, binding: ThreadBinding) -> "TrustedToolContext":
        return cls(binding=binding)

    def authorize(self, capability: str) -> ToolContext:
        self.binding.authorize(capability)
        return self.binding.context()

    def with_model_arguments(self, arguments: dict[str, Any] | None) -> ToolContext:
        # Model arguments can describe a query, but can never replace server identity.
        return self.binding.resolve_tool_context(arguments)

    @property
    def session_id(self) -> str:
        return self.binding.session_id

    @property
    def user_id(self) -> str:
        return self.binding.user_id


__all__ = ["BindingError", "TrustedToolContext"]
