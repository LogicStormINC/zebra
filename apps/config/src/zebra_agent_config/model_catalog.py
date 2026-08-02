from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from zebra_agent_config.settings import ModelSettings, ZebraAgentSettings


MODEL_CATALOG_SCHEMA = "zebra.model-catalog.v1"
_CATALOG_KEYS = frozenset({"default_id", "models"})
_ENTRY_KEYS = frozenset({"id", "label", "available", "settings"})
_SETTING_KEYS = frozenset(
    {
        "provider",
        "api_key_env",
        "base_url",
        "model",
        "profile_id",
        "executor_profile",
        "planner_profile",
        "reviewer_profile",
        "summarizer_profile",
        "analyst_profile",
        "classifier_profile",
        "max_retries",
        "deepseek_beta_enabled",
        "deepseek_beta_base_url",
    }
)
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$")


@dataclass(frozen=True)
class ModelCatalogEntry:
    id: str
    label: str
    available: bool
    settings: ModelSettings

    def to_public_mapping(self) -> dict[str, object]:
        return {"id": self.id, "label": self.label, "available": self.available}


@dataclass(frozen=True)
class ModelCatalog:
    default_id: str
    entries: tuple[ModelCatalogEntry, ...]

    @classmethod
    def single(cls, settings: ModelSettings) -> ModelCatalog:
        return cls(
            default_id="default",
            entries=(
                ModelCatalogEntry(
                    id="default",
                    label=settings.model,
                    available=True,
                    settings=settings,
                ),
            ),
        )

    def select(self, model_id: str | None = None) -> ModelCatalogEntry:
        selected_id = self.default_id if model_id is None else model_id.strip()
        if not selected_id:
            raise ValueError("model catalog id must not be blank")
        entry = next((item for item in self.entries if item.id == selected_id), None)
        if entry is None:
            raise ValueError(f"unknown model catalog id: {selected_id}")
        if not entry.available:
            raise ValueError(f"model catalog entry unavailable: {selected_id}")
        return entry


def load_model_catalog(raw: str | None, fallback: ModelSettings) -> ModelCatalog:
    if raw is None or not raw.strip():
        return ModelCatalog.single(fallback)
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("ZEBRA_MODEL_CATALOG_JSON must be valid JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("ZEBRA_MODEL_CATALOG_JSON must be a JSON object")
    unknown = set(payload) - _CATALOG_KEYS
    if unknown:
        raise ValueError("ZEBRA_MODEL_CATALOG_JSON contains unsupported fields")
    raw_models = payload.get("models")
    if not isinstance(raw_models, list) or not raw_models:
        raise ValueError("ZEBRA_MODEL_CATALOG_JSON models must be a non-empty list")
    if len(raw_models) > 16:
        raise ValueError("ZEBRA_MODEL_CATALOG_JSON supports at most 16 models")
    entries = tuple(_parse_entry(item, fallback) for item in raw_models)
    ids = [entry.id for entry in entries]
    if len(set(ids)) != len(ids):
        raise ValueError("ZEBRA_MODEL_CATALOG_JSON model ids must be unique")
    default_id = payload.get("default_id", ids[0])
    if not isinstance(default_id, str) or not _ID_RE.fullmatch(default_id):
        raise ValueError("ZEBRA_MODEL_CATALOG_JSON default_id is invalid")
    if default_id not in ids:
        raise ValueError("ZEBRA_MODEL_CATALOG_JSON default_id is unknown")
    if not next(entry.available for entry in entries if entry.id == default_id):
        raise ValueError("ZEBRA_MODEL_CATALOG_JSON default_id is unavailable")
    return ModelCatalog(default_id=default_id, entries=entries)


def catalog_for_settings(settings: ZebraAgentSettings) -> ModelCatalog:
    configured = getattr(settings, "model_catalog", None)
    return configured if configured is not None else ModelCatalog.single(settings.model)


def select_model_catalog_entry(
    settings: ZebraAgentSettings,
    model_id: str | None,
) -> ModelCatalogEntry:
    return catalog_for_settings(settings).select(model_id)


def settings_for_model(
    settings: ZebraAgentSettings,
    model_id: str | None,
) -> ZebraAgentSettings:
    return replace(settings, model=select_model_catalog_entry(settings, model_id).settings)


def _parse_entry(raw: object, fallback: ModelSettings) -> ModelCatalogEntry:
    if not isinstance(raw, dict) or set(raw) - _ENTRY_KEYS:
        raise ValueError("ZEBRA_MODEL_CATALOG_JSON model entry is invalid")
    model_id = raw.get("id")
    label = raw.get("label")
    available = raw.get("available", True)
    if not isinstance(model_id, str) or not _ID_RE.fullmatch(model_id):
        raise ValueError("ZEBRA_MODEL_CATALOG_JSON model id is invalid")
    if not isinstance(label, str) or not label.strip() or len(label.strip()) > 128:
        raise ValueError("ZEBRA_MODEL_CATALOG_JSON model label is invalid")
    if not isinstance(available, bool):
        raise ValueError("ZEBRA_MODEL_CATALOG_JSON model available must be boolean")
    return ModelCatalogEntry(
        id=model_id,
        label=label.strip(),
        available=available,
        settings=_parse_settings(raw.get("settings"), fallback),
    )


def _parse_settings(raw: object, fallback: ModelSettings) -> ModelSettings:
    if not isinstance(raw, dict):
        raise ValueError("ZEBRA_MODEL_CATALOG_JSON model settings are required")
    if set(raw) - _SETTING_KEYS:
        raise ValueError("ZEBRA_MODEL_CATALOG_JSON model settings contain unsupported fields")
    required = ("provider", "api_key_env", "base_url", "model")
    if any(not isinstance(raw.get(key), str) or not raw[key].strip() for key in required):
        raise ValueError("ZEBRA_MODEL_CATALOG_JSON model settings are incomplete")
    optional_text = {
        key: _optional_text(raw.get(key))
        for key in (
            "profile_id",
            "executor_profile",
            "planner_profile",
            "reviewer_profile",
            "summarizer_profile",
            "analyst_profile",
            "classifier_profile",
            "deepseek_beta_base_url",
        )
        if key in raw
    }
    max_retries = raw.get("max_retries", 1)
    if not isinstance(max_retries, int) or isinstance(max_retries, bool) or max_retries < 0:
        raise ValueError("ZEBRA_MODEL_CATALOG_JSON max_retries is invalid")
    beta_enabled = raw.get("deepseek_beta_enabled", False)
    if not isinstance(beta_enabled, bool):
        raise ValueError("ZEBRA_MODEL_CATALOG_JSON deepseek_beta_enabled is invalid")
    return replace(
        fallback,
        provider=raw["provider"].strip(),
        api_key_env=raw["api_key_env"].strip(),
        base_url=raw["base_url"].strip(),
        model=raw["model"].strip(),
        profile_id=optional_text.get("profile_id"),
        executor_profile=optional_text.get("executor_profile"),
        planner_profile=optional_text.get("planner_profile"),
        reviewer_profile=optional_text.get("reviewer_profile"),
        summarizer_profile=optional_text.get("summarizer_profile"),
        analyst_profile=optional_text.get("analyst_profile"),
        classifier_profile=optional_text.get("classifier_profile"),
        max_retries=max_retries,
        deepseek_beta_enabled=beta_enabled,
        deepseek_beta_base_url=optional_text.get("deepseek_beta_base_url"),
    )


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError("ZEBRA_MODEL_CATALOG_JSON optional text field is invalid")
    return value.strip()
