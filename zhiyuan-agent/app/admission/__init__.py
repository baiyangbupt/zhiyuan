"""招生事实层的规范化与校验工具。"""

from .facts import (
    AdmissionFactError,
    AdmissionMode,
    adapt_backend_admission_rate,
    canonical_admission_mode,
    derive_risk_tier,
    mode_dependent_cache_key,
    validate_admission_fact,
)

__all__ = [
    "AdmissionFactError",
    "AdmissionMode",
    "adapt_backend_admission_rate",
    "canonical_admission_mode",
    "derive_risk_tier",
    "mode_dependent_cache_key",
    "validate_admission_fact",
]
