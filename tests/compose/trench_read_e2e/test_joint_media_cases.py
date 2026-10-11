"""Executor contracts only: these synthetic test dictionaries are NOT live P1 evidence."""

import copy
import json
from types import SimpleNamespace

import pytest
from joint_media_cases import (
    BAD_CHART,
    GOOD_CHART,
    MEDIA_CASES,
    MEDIA_SEED,
    media_prompt,
    run_media_case,
    validate_media,
    validate_media_fixture,
    validate_native_media_points,
)
from support import E2EError
from test_joint_public_cases import evidence as common_evidence


def fixture():
    return {
        "scope": "actual_scratch_business_rows",
        "provider_or_receipt_injection": False,
        "event_id": "a" * 32,
        "period_id": "qa-period-" + "b" * 32,
        "image_url": "https://media.example.org/proof.png",
        "video_url": "https://media.example.org/proof.mp4",
    }


def browser_evidence(case_id):
    data = common_evidence()
    data.update(case_id=case_id, run_id="run1")
    data["media"] = {
        "scope": "actual_browser_media_observation",
        "fixture_provider": False,
        "preterminal": {"before_terminal": True, "before_final_receipt": True},
        "image": {"decoded": True, "fault_aborted": True, "sibling_survived": True},
        "video": {
            "played": True,
            "time_advanced_seconds": 0.5,
            "frames_advanced": 5,
            "source_kind": "verified_external_direct",
            "download_requests": 0,
        },
        "chart": {
            "valid_svg": True,
            "isolated_failure": True,
            "markdown_table": True,
            "latex_rendered": True,
        },
        "revision": {
            "canonical_replacement": True,
            "same_video_node": True,
            "playback_continued": True,
            "reader_anchor": True,
            "replacements": [{"output_id": "second", "replaces_output_id": "first"}],
        },
    }
    return data


@pytest.mark.parametrize("case_id", sorted(MEDIA_CASES))
def test_executable_prompts_use_real_tools_and_do_not_inject_receipts(case_id):
    prompt = media_prompt(case_id, "ZEBRA_QA_SIMPLE_marker", fixture())
    assert "events.get_historical_event" in prompt and fixture()["period_id"] in prompt
    assert "content.present" in prompt and len(prompt) < 4000
    assert "ZEBRA_QA_SIMPLE_marker" in prompt
    if case_id in {"inline_video", "revision"}:
        assert "external_video" in prompt and "不得下载" in prompt or "不下载" in prompt
    if case_id == "chart_markdown_latex":
        assert "files.publish" in prompt and "qa-invalid-mark" in prompt


@pytest.mark.parametrize(
    "url",
    [
        "http://public.example/a.mp4",
        "https://127.0.0.1/a.mp4",
        "https://localhost/a.mp4",
        "https://x.internal/a.mp4",
        "https://user:secret@example.org/a.mp4",
        "https://example.org:8443/a.mp4",
        "https://example.org/watch",
    ],
)
def test_no_ssrf_or_arbitrary_page_source_in_media_fixture(url):
    with pytest.raises(E2EError):
        validate_media_fixture({**fixture(), "video_url": url})


def test_media_seed_writes_only_entitled_business_rows_not_runtime_receipts():
    compile(MEDIA_SEED, "scratch_media_seed", "exec")
    assert MEDIA_SEED.index("assert os.environ['DATABASE_URL']") < MEDIA_SEED.index(
        "async_sessionmaker(engine)()"
    )
    assert "period.workspace_id" in MEDIA_SEED
    assert "event.images_json" in MEDIA_SEED and "event.videos_json" in MEDIA_SEED
    assert "session_events" not in MEDIA_SEED and "model_response" not in MEDIA_SEED


@pytest.mark.parametrize("case_id", sorted(MEDIA_CASES))
def test_complete_browser_contract_is_required(case_id):
    validate_media(browser_evidence(case_id))
    data = browser_evidence(case_id)
    data["media"]["preterminal"]["before_final_receipt"] = False
    with pytest.raises(E2EError):
        validate_media(data)


@pytest.mark.parametrize(
    "case_id,section,field,value",
    [
        ("image", "image", "decoded", False),
        ("image", "image", "fault_aborted", False),
        ("image", "image", "sibling_survived", False),
        ("inline_video", "video", "frames_advanced", 0),
        ("inline_video", "video", "time_advanced_seconds", 0),
        ("inline_video", "video", "source_kind", "artifact_download"),
        ("inline_video", "video", "download_requests", 1),
        ("chart_markdown_latex", "chart", "valid_svg", False),
        ("chart_markdown_latex", "chart", "isolated_failure", False),
        ("chart_markdown_latex", "chart", "latex_rendered", False),
        ("revision", "revision", "same_video_node", False),
        ("revision", "revision", "playback_continued", False),
        ("revision", "revision", "reader_anchor", False),
    ],
)
def test_presence_or_synthetic_revision_is_not_playback_proof(case_id, section, field, value):
    data = browser_evidence(case_id)
    data["media"][section][field] = value
    with pytest.raises(E2EError):
        validate_media(data)


def points(case_id):
    data = []

    def point(kind, payload):
        if kind == "tool_execution_completed":
            payload = {**payload, "tool_call_id": f"call-{len(data)}"}
            data.append(
                {
                    "event_type": "tool_call_proposed",
                    "task_sequence": len(data) + 1,
                    "payload": {
                        "tool_call_id": payload["tool_call_id"],
                        "tool_name": payload["tool_name"],
                        "arguments": {"event_id": fixture()["event_id"]},
                    },
                }
            )
        data.append({"event_type": kind, "task_sequence": len(data) + 1, "payload": payload})

    point(
        "model_response_received",
        {
            "provider": "deepseek",
            "model_call_id": "real-call",
            "request_hash": "a" * 64,
            "normalized_error": None,
        },
    )
    point(
        "tool_execution_completed",
        {
            "tool_name": "events.get_historical_event",
            "status": "executed",
            "output": json.dumps(
                {
                    "items": [
                        {
                            "event_id": fixture()["event_id"],
                            "original_url": fixture()["video_url"],
                        }
                    ]
                }
            ),
        },
    )
    parts = [{"type": "external_video", "sourceUrl": fixture()["video_url"]}]
    if case_id == "image":
        for _ in range(2):
            point(
                "tool_execution_completed",
                {
                    "tool_name": "media.import_historical",
                    "status": "executed",
                    "metadata": {"host_media_import": True},
                },
            )
        parts = [{"type": "image"}, {"type": "image"}]
    if case_id == "chart_markdown_latex":
        for spec in (GOOD_CHART, BAD_CHART):
            point(
                "tool_call_proposed",
                {"tool_name": "files.publish", "arguments": {"content": json.dumps(spec)}},
            )
        parts = [{"type": "chart"}, {"type": "chart"}]
    point(
        "tool_execution_completed",
        {
            "tool_name": "content.present",
            "status": "executed",
            "metadata": {"content_parts": parts},
        },
    )
    if case_id == "revision":
        point("public_output", {"output_id": "second", "replaces_output_id": "first"})
    point("answer_committed", {})
    return data


@pytest.mark.parametrize("case_id", sorted(MEDIA_CASES))
def test_native_source_proof_must_match_actual_browser_case(case_id):
    result = validate_native_media_points(
        points(case_id), browser_evidence(case_id), fixture(), task="task1", thread="thread1"
    )
    assert result["whole_history_hydrated"] is False
    bad = copy.deepcopy(points(case_id))
    bad[0]["payload"]["provider"] = "fixture"
    with pytest.raises(E2EError, match="provider"):
        validate_native_media_points(
            bad, browser_evidence(case_id), fixture(), task="t", thread="h"
        )


def test_inline_video_rejects_object_store_substitution_and_missing_model():
    data = points("inline_video")
    data[-2]["payload"]["metadata"]["content_parts"] = [{"type": "video", "artifactId": "a"}]
    with pytest.raises(E2EError, match="direct"):
        validate_native_media_points(
            data, browser_evidence("inline_video"), fixture(), task="t", thread="h"
        )
    with pytest.raises(E2EError, match="missing"):
        validate_native_media_points(
            data[1:], browser_evidence("inline_video"), fixture(), task="t", thread="h"
        )


def test_native_revision_cannot_pass_on_uncorrelated_dom_replacement():
    data = browser_evidence("revision")
    data["media"]["revision"]["replacements"][0]["output_id"] = "fixture-revision"
    with pytest.raises(E2EError, match="canonical"):
        validate_native_media_points(points("revision"), data, fixture(), task="t", thread="h")


def test_old_image_cannot_start_media_executor(monkeypatch, tmp_path):
    monkeypatch.setattr("joint_media_cases.joint_preflight", lambda *_: {})
    monkeypatch.setattr(
        "joint_media_cases.native_source_identity",
        lambda *_: {"worker": {"current_checkout_match": False}},
    )
    monkeypatch.setattr(
        "joint_media_cases.subprocess.run", lambda *_a, **_k: pytest.fail("old image run")
    )
    with pytest.raises(E2EError, match="freeze"):
        run_media_case(SimpleNamespace(), {}, tmp_path, case_id="image", fixture=fixture())
