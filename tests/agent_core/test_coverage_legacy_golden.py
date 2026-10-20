"""Captured pre-v2 contract/admission JSON identity (2026-10-20)."""

import json

GOLDEN = json.loads(r"""{
  "contract": {
    "schema_version": 1,
    "mode": "exhaustive",
    "dataset": "trench.subscribed_events",
    "scope": {
      "time_field": "visible_at",
      "timezone": "Asia/Shanghai",
      "from_inclusive": "2026-10-07T00:00:00Z",
      "to_exclusive": "2026-10-08T00:00:00Z",
      "source_selection": "all_entitled_periods"
    },
    "content_requirements": [
      "canonical_body"
    ],
    "checks": [
      {
        "id": "risk",
        "version": "1",
        "kind": "model",
        "definition_digest": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
      }
    ],
    "cross_record_checks": [],
    "unresolved_policy": "block",
    "publication_policy": "certified_report_only",
    "contract_revision": 1
  },
  "contract_digest": "a46dc8e95bb725fc5a7ef226445a0c58755801ee99ae27b810e267987e6d9984",
  "admission": {
    "contract": {
      "schema_version": 1,
      "mode": "exhaustive",
      "dataset": "trench.subscribed_events",
      "scope": {
        "time_field": "visible_at",
        "timezone": "UTC",
        "from_inclusive": "2029-12-31T00:00:00Z",
        "to_exclusive": "2030-01-01T00:00:00Z",
        "source_selection": "all_entitled_periods"
      },
      "content_requirements": [
        "canonical_body"
      ],
      "checks": [
        {
          "id": "bounded_semantic",
          "version": "1",
          "kind": "model",
          "definition_digest": "2da8e9712f69d971dc4046434050c8a059a290769bede621432711634f3ef355"
        }
      ],
      "cross_record_checks": [],
      "unresolved_policy": "block",
      "publication_policy": "certified_report_only",
      "contract_revision": 1
    },
    "history_ref": "history-1",
    "model_profile": "review-profile",
    "execution_budget": {
      "max_attempts": 100,
      "max_input_bytes": 1000
    },
    "max_model_calls": 100,
    "max_model_tokens": 1000,
    "max_runtime_seconds": 60
  }
}""")
