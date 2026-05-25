"""Registry shape is correct and complete."""
import dataclasses

import pytest

from app.services.settings.registry import SETTING_REGISTRY


def test_every_setting_has_a_default_of_the_declared_type():
    for key, spec in SETTING_REGISTRY.items():
        # bool must not pass through as int (Python's bool is int subclass)
        if spec.type is int:
            assert isinstance(spec.default, int) and not isinstance(spec.default, bool), key
        else:
            assert isinstance(spec.default, spec.type), key


def test_every_setting_scope_subset_is_legal():
    legal = {"global", "household", "user"}
    for key, spec in SETTING_REGISTRY.items():
        assert set(spec.scopes).issubset(legal), key
        assert len(spec.scopes) >= 1, key


def test_public_settings_are_global_only():
    """Anything exposed via /runtime-config must be a global value (no scope-resolved leak)."""
    for key, spec in SETTING_REGISTRY.items():
        if spec.public:
            assert "global" in spec.scopes, key


def test_known_seeded_keys_present():
    for k in ("signups_open", "maintenance_message", "default_ai_model",
              "briefing_hour_local", "theme", "email_notifications"):
        assert k in SETTING_REGISTRY


def test_setting_spec_is_frozen():
    spec = next(iter(SETTING_REGISTRY.values()))
    with pytest.raises(dataclasses.FrozenInstanceError):
        spec.type = str  # type: ignore[misc]
