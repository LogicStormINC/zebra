"""Trusted E1-only operator factory. Business requests cannot select this module."""

import re
import runpy
from dataclasses import replace
from pathlib import Path
from urllib.parse import urlsplit

from agent_integrations.bundle_model import BundleModelGateway
from agent_storage import cloud_composition_from_environment
from metering import measure_request
from zebra_agent_worker.cloud_composition import compose_cloud_worker


def counter_for(model, assembly):
    if (
        type(model) is not BundleModelGateway
        or assembly is None
        or model._assembly != assembly
        or model._client is not None
        or model._api_key != "synthetic-only"
        or model._base_url != "https://api.deepseek.com"
        or model._model_name != "deepseek-v4-pro"
        or assembly.bundle.manifest.scope.namespace_id != "ha-e1-20261102"
        or assembly.provider_profile.api_key_env != "ZEBRA_E2E_MODEL_API_KEY"
        or assembly.bundle.manifest.domains.model.parameters.max_output_tokens > 1024
    ):
        return None
    return measure_request


def compose(settings, cloud=None):
    cloud = cloud if cloud is not None else cloud_composition_from_environment()
    address = urlsplit(cloud.dsn)
    legacy = (
        cloud.deployment_namespace == "ha-e1-20261102"
        and address.path in {"/ha_e1", "/zebra_e1_corpus_fleet"}
    )
    rebuilt = (
        address.path == "/zebra_e1_corpus_rebuilt"
        and re.fullmatch(r"e1-corpus-[0-9a-f]{32}", cloud.deployment_namespace) is not None
    )
    if (
        settings.deployment != "cloud"
        or settings.storage_authority != "postgresql"
        or not (legacy or rebuilt)
        or (address.hostname, address.port) != ("127.0.0.1", 25432)
    ):
        raise ValueError("E1 operator factory refuses another deployment")
    runpy.run_path(str(Path(__file__).with_name("check_model.py")))
    return replace(
        compose_cloud_worker(cloud, memory_settings=settings.memory_gateway),
        model_request_budget_factory=counter_for,
    )
