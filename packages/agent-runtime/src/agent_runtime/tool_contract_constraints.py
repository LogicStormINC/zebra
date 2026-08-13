from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace

from agent_core.domain.tools import ToolCallStatus, ToolResult
from agent_storage.model_tool_argument_values import (
    ModelToolArgumentValues as ModelToolArgumentValues,
)
from agent_storage.model_tool_argument_values import (
    validate_model_tool_argument_values,
)
from agent_tools import ToolContract


def constrained_tool_contracts(
    contracts: Mapping[str, ToolContract],
    values: ModelToolArgumentValues | None,
    selected_tool_names: tuple[str, ...] | None,
) -> dict[str, ToolContract]:
    if values is None:
        return dict(contracts)
    normalized = validate_model_tool_argument_values(
        values,
        selected_tool_names=selected_tool_names,
        catalog={name: contract.argument_properties for name, contract in contracts.items()},
    )
    narrowed = dict(contracts)
    for tool_name, property_values in normalized:
        properties = dict(narrowed[tool_name].argument_properties)
        for property_name, allowed_values in property_values:
            schema = properties.get(property_name)
            assert isinstance(schema, Mapping)
            properties[property_name] = {**schema, "enum": list(allowed_values)}
        narrowed[tool_name] = replace(narrowed[tool_name], argument_properties=properties)
    return narrowed


def trusted_typed_evidence_result(
    result: ToolResult, *, trusted_evidence: tuple[str, ...]
) -> ToolResult:
    metadata = dict(result.metadata)
    metadata.pop("typed_evidence", None)
    evidence = tuple(dict.fromkeys(label.strip() for label in trusted_evidence if label.strip()))
    if result.status is ToolCallStatus.EXECUTED and evidence:
        metadata["typed_evidence"] = list(evidence)
    return result.model_copy(update={"metadata": metadata})
