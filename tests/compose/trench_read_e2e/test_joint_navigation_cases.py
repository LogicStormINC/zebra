"""Contract regressions, NOT live browser/provider passes or healthy latency samples."""

from __future__ import annotations

import copy
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from joint_navigation_cases import (
    NAVIGATION_CASES,
    navigation_prompt,
    run_navigation_case,
    validate_native_navigation_rows,
    validate_navigation,
)
from support import E2EError


def seed():
    return {
        "scope": "actual_scratch_business_rows",
        "provider_or_receipt_injection": False,
        "seed_id": "abc",
        "source_ids": ["a", "b"],
        "event_ids": [str(i) for i in range(48)],
        "event_count": 48,
        "per_source_count": 24,
    }


def evidence(case_id):
    baseline = [
        {"cursor": 1, "type": "tool_start"},
        {"cursor": 2, "type": "tool_result"},
        {"cursor": 3, "type": "done", "answer_committed": True},
    ]
    return {
        "case_id": case_id,
        "scope": "real_scratch_host_browser_sse",
        "fixture_routes": False,
        "post_count": 1,
        "final_count": 1,
        "admission_terminal": False,
        "frames": baseline,
        "cleanup": {"worker_cleanup": {"status": "passed"}},
        "navigation": {
            "scope": "actual_browser_observation_faults",
            "fixture_provider": False,
            "fault_cohort": True,
            "healthy_samples": 0,
            "observe_only": True,
            "frame_disconnect": {
                "scope": "native_browser_per_frame_cancel_replay_and_live_ui_fault",
                "baseline": baseline,
                "restored": copy.deepcopy(baseline),
                "cuts": [
                    {
                        "cut_cursor": i,
                        "next_cursor": i + 1 if i < 3 else None,
                        "request_started": True,
                        "abort_called": True,
                        "reader_cancelled": True,
                    }
                    for i in range(1, 4)
                ],
                "ui_transport_failed": True,
                "ui_reconnected": True,
                "real_eof": True,
                "no_duplicate_tools": True,
            },
            "navigation": {
                "a_key": "actual-A",
                "b_key": "actual-B",
                "refresh": True,
                "a_b_a": True,
                "late_ack": True,
                "b_not_contaminated": True,
                "same_admission": True,
                "no_duplicate_dom_tools": True,
                "dom_tool_count": 1,
                "response_unmodified": True,
                "spa_navigation": True,
            },
        },
    }


@pytest.mark.parametrize("case_id", sorted(NAVIGATION_CASES))
def test_fault_prompts_request_real_read_tools_not_fixture_output(case_id):
    prompt = navigation_prompt(case_id, "marker", seed())
    assert "events.search_history" in prompt and "limit=20" in prompt
    assert "12%" in prompt and "8%" in prompt and "marker" in prompt
    with pytest.raises(E2EError):
        navigation_prompt(case_id, "marker", {**seed(), "provider_or_receipt_injection": True})


@pytest.mark.parametrize("case_id", sorted(NAVIGATION_CASES))
def test_common_contract_disallows_fixture_and_new_admission(case_id):
    validate_navigation(evidence(case_id))
    for key, value in (
        ("fixture_routes", True),
        ("post_count", 2),
        ("final_count", 2),
        ("admission_terminal", True),
    ):
        data = evidence(case_id)
        data[key] = value
        with pytest.raises(E2EError):
            validate_navigation(data)


@pytest.mark.parametrize(
    "key,value",
    [
        ("fault_cohort", False),
        ("healthy_samples", 1),
        ("observe_only", False),
        ("fixture_provider", True),
    ],
)
def test_fault_replay_is_never_a_healthy_p95_sample(key, value):
    data = evidence("frame_disconnect")
    data["navigation"][key] = value
    with pytest.raises(E2EError):
        validate_navigation(data)


@pytest.mark.parametrize(
    "key", ["ui_transport_failed", "ui_reconnected", "real_eof", "no_duplicate_tools"]
)
def test_cancel_probes_alone_do_not_prove_real_ui_recovery(key):
    data = evidence("frame_disconnect")
    data["navigation"]["frame_disconnect"][key] = False
    with pytest.raises(E2EError):
        validate_navigation(data)


@pytest.mark.parametrize("field", ["request_started", "abort_called", "reader_cancelled"])
def test_every_frame_requires_actual_request_and_consumer_cancellation(field):
    data = evidence("frame_disconnect")
    data["navigation"]["frame_disconnect"]["cuts"][1][field] = False
    with pytest.raises(E2EError):
        validate_navigation(data)


@pytest.mark.parametrize(
    "fault", ["missing_cut", "wrong_next", "reordered_replay", "duplicate_cursor", "truncated_eof"]
)
def test_no_last_n_or_ordering_shortcut_for_per_frame_faults(fault):
    data = evidence("frame_disconnect")
    frame = data["navigation"]["frame_disconnect"]
    if fault == "missing_cut":
        frame["cuts"].pop()
    elif fault == "wrong_next":
        frame["cuts"][0]["next_cursor"] = 3
    elif fault == "reordered_replay":
        frame["restored"].reverse()
    elif fault == "duplicate_cursor":
        frame["baseline"][1]["cursor"] = 1
    else:
        frame["cuts"][-1]["next_cursor"] = 4
    with pytest.raises(E2EError):
        validate_navigation(data)


@pytest.mark.parametrize(
    "field",
    [
        "refresh",
        "a_b_a",
        "late_ack",
        "b_not_contaminated",
        "same_admission",
        "no_duplicate_dom_tools",
        "response_unmodified",
        "spa_navigation",
    ],
)
def test_navigation_cannot_infer_late_ack_or_epoch_isolation(field):
    data = evidence("navigation")
    data["navigation"]["navigation"][field] = False
    with pytest.raises(E2EError):
        validate_navigation(data)


def rows():
    return [
        {"event_type": "session_command_accepted"},
        {
            "event_type": "model_response_received",
            "provider": "deepseek",
            "model_call_id": "model1",
            "request_hash": "a" * 64,
            "model_error": None,
        },
        {"event_type": "tool_execution_started", "tool_call_id": "tool1"},
        {"event_type": "tool_execution_completed", "tool_call_id": "tool1"},
        {"event_type": "answer_committed"},
    ]


def test_real_canonical_proof_has_no_duplicate_tools_and_no_fixture_provider():
    value = validate_native_navigation_rows(rows(), task="task1", thread="thread1", run_id="run1")
    assert value["tool_ids"] == ["tool1"] and value["whole_history_hydrated"] is False
    for fault in (
        "duplicate",
        "fixture",
        "new_admission",
        "missing_completion",
        "new_final",
        "limit",
    ):
        data = copy.deepcopy(rows())
        if fault == "duplicate":
            data.append(data[2])
        elif fault == "fixture":
            data[1]["provider"] = "fake"
        elif fault == "new_admission":
            data.append(data[0])
        elif fault == "missing_completion":
            data.pop(3)
        elif fault == "new_final":
            data.append(data[-1])
        else:
            data *= 52
        with pytest.raises(E2EError):
            validate_native_navigation_rows(data, task="task1", thread="thread1", run_id="run1")


def test_navigation_requires_actual_tool_dom_not_vacuous_unique_list():
    for count in (0, None, True):
        data = evidence("navigation")
        data["navigation"]["navigation"]["dom_tool_count"] = count
        with pytest.raises(E2EError):
            validate_navigation(data)


def test_old_images_cannot_run_fault_executor(monkeypatch, tmp_path):
    monkeypatch.setattr("joint_navigation_cases.joint_preflight", lambda *_: {})
    monkeypatch.setattr("joint_navigation_cases.native_admission_gate", lambda *_: None)
    monkeypatch.setattr(
        "joint_navigation_cases.native_source_identity",
        lambda *_: {"worker": {"current_checkout_match": False}},
    )
    monkeypatch.setattr(
        "joint_navigation_cases.subprocess.run", lambda *_a, **_k: pytest.fail("old image run")
    )
    with pytest.raises(E2EError, match="freeze"):
        run_navigation_case(SimpleNamespace(), {}, tmp_path, case_id="navigation", seed=seed())


def test_browser_fault_plugin_is_executable_and_never_fulfills_or_replaces_dom():
    script = Path(__file__).with_name("browser_navigation_observer.mjs")
    subprocess.run(["node", "--check", str(script)], check=True, capture_output=True)
    source = script.read_text()
    assert ".fulfill(" not in source and ".innerHTML =" not in source
    assert "Fetch.continueResponse" in source and "Fetch.getResponseBody" in source
    assert "Network.emulateNetworkConditions" in source and "reader.cancel()" in source
    assert "qa_navigation_probe=1" in source and "createCapture(stream" in source
    assert source.index('await guard("navigation_ack_release");\n      // Continue') < source.index(
        'await network.send("Fetch.continueResponse", { requestId: event.requestId });'
    )


def test_empty_or_fixture_callbacks_cannot_start_browser_executor():
    script = Path(__file__).with_name("browser_navigation_observer.mjs")
    code = """
import assert from 'node:assert/strict';
const {startNavigationObserver}=await import(process.argv[1]);
await assert.rejects(startNavigationObserver({caseId:'navigation',guard:null}),/function/);
await assert.rejects(startNavigationObserver({caseId:'fixture',guard:()=>{}}));
"""
    subprocess.run(
        ["node", "--input-type=module", "-e", code, script.as_uri()],
        check=True,
        capture_output=True,
    )


def shared_runner():
    script = Path(__file__).resolve().parents[3].parent / (
        "Trench/toc-frontend/scripts/strategy-joint-acceptance.mjs"
    )
    if not script.is_file():
        pytest.skip("shared runner guards require the paired Trench checkout")
    return script


def test_shared_runner_navigation_wiring_preserves_non_navigation_gates():
    script = shared_runner()
    subprocess.run(["node", "--check", str(script)], check=True, capture_output=True)
    source = script.read_text()
    assert 'trench_read_e2e/browser_navigation_observer.mjs"' in source
    assert (
        source.index('page.goto("/dashboard/strategy"')
        < source.index("await navigationObserver.beforeSubmit()")
        < source.index('getByRole("textbox").press("Enter")')
    )
    assert source.index("await navigationObserver.afterAdmission(turn)") < source.index(
        'phase = "navigation"'
    )
    assert 'navigationCase && url.searchParams.get("qa_navigation_probe") === "1"' in source
    assert "navigationObserver?.onFrame(frame, event)" in source
    assert "navigationObserver.finish({ turn })" in source and "{ navigation }" in source
    assert "navigationObserver?.isExpectedFailure(requestId)" in source
    assert source.index("if (stream.expected_disconnect === true) return;") < source.index(
        "parser.finish();"
    )
    assert (
        'const noFinalCase = authorityCase && ["cancel", "approval"]'
        ".includes(config.authority_subcase);" in source
    )
    assert "if (!navigationCase && !noFinalCase) await page.waitForFunction((turnId)" in source
    assert "if (!navigationCase) assert.ok(publicVisibility.some" in source
    assert (
        "} else if (!noFinalCase) {\n      assert.ok(publicOutputCount > 0 && toolCount > 0"
        in source
    )
    assert "assert.equal(finalCount, noFinalCase ? 0 : 1," in source
    assert "else if (simple) assert.equal(final.answer, config.expected);" in source
    assert "else assert.ok(final.answer.includes(config.expected));" in source
    assert "assert.equal(publicOutputCount, 0" in source
    assert "assert.equal(toolCount, 0" in source
    assert "mediaObserver?.onFrame(frame, event)" in source
    assert "mediaObserver.finish({ frames })" in source
    assert "operatorResult ? await operatorResult" in source


def test_shared_runner_executes_hash_verified_replay_deduplication():
    # Execute the actual pure runner function without its browser-launching entrypoint.
    source = shared_runner().read_text()
    function = (
        "function deduplicateNavigationFrames"
        + source.split("function deduplicateNavigationFrames", 1)[1].split("\n}\n", 1)[0]
        + "\n}"
    )
    code = """
import assert from 'node:assert/strict';
const dedup = new Function('assert',
  process.argv[1] + ';return deduplicateNavigationFrames;')(assert);
const frame = (cursor, hash='a'.repeat(64)) => ({cursor,payload_sha256:hash});
assert.deepEqual(dedup([frame(2),frame(1),frame(2)]), [frame(1),frame(2)]);
assert.throws(()=>dedup([frame(1),frame(1,'b'.repeat(64))]), /changed canonical payload/);
for (const rows of [[],[frame(0)],[frame(1,'')],Array.from({length:257},(_,i)=>frame(i+1))]) {
  assert.throws(()=>dedup(rows));
}
"""
    subprocess.run(
        ["node", "--input-type=module", "-e", code, function],
        check=True,
        capture_output=True,
    )


def test_shared_runner_only_marks_observer_authorized_disconnect_ids():
    source = shared_runner().read_text()
    callback = (
        source.split('network.on("Network.loadingFailed", ', 1)[1].split("\n    });", 1)[0]
        + "\n    }"
    )
    code = """
import assert from 'node:assert/strict';
let settled=0;
const captures=new Map(['known','unknown'].map(id=>[id,{stream:{},finish:()=>settled++}]));
const make = observer => new Function('captures','navigationObserver',
  'return '+process.argv[1])(captures,observer);
const handle=make({isExpectedFailure:id=>id==='known'});
handle({requestId:'known',canceled:true,errorText:'net::ERR_ABORTED'});
handle({requestId:'unknown',canceled:false,errorText:'net::ERR_FAILED'});
assert.equal(captures.get('known').stream.expected_disconnect,true);
assert.equal(captures.get('unknown').stream.expected_disconnect,undefined);
assert.equal(captures.get('unknown').stream.transport_end,'network_failed');
assert.equal(settled,2);
captures.set('ordinary',{stream:{},finish:()=>{}});
make(undefined)({requestId:'ordinary',canceled:true,errorText:'net::ERR_ABORTED'});
assert.equal(captures.get('ordinary').stream.expected_disconnect,undefined);
"""
    subprocess.run(
        ["node", "--input-type=module", "-e", code, callback],
        check=True,
        capture_output=True,
    )


def test_committed_answer_selector_rejects_user_div_accepts_one_assistant_paragraph():
    source = shared_runner().read_text()
    start = "await page.waitForFunction(({ marker, messageId }) =>"
    callback = (
        "({ marker, messageId }) =>"
        + source.split(start, 1)[1].split(",\n      { marker: config.expected", 1)[0]
    )
    assert source.index("expect.poll(() => finalObserved") < source.index(start)
    assert "committedMessageId = event.message_id" in source
    code = """
import assert from 'node:assert/strict';
const marker='ZEBRA_QA_SIMPLE_contract', messageId='message:canonical';
// DOM contract objects only: this unit check is not live browser/provider evidence.
const div=(id,text,children=[])=>({tagName:'DIV',textContent:text,children,
  getAttribute:key=>key==='data-message-id'?id:null});
let nodes=[];
const document={querySelectorAll:selector=>{
  assert.equal(selector,'[data-message-id]'); return nodes;
}};
const matches=new Function('document','return ('+process.argv[1]+');')(document);
const user=div('user:prompt',marker);
nodes=[user];
assert.equal(matches({marker,messageId}),false);
nodes=[user,div('message:other',marker)];
assert.equal(matches({marker,messageId}),false);
nodes=[user,div(messageId,'answer without acceptance token')];
assert.equal(matches({marker,messageId}),false);
const paragraph={tagName:'P',textContent:marker};
nodes=[user,div(messageId,marker,[paragraph])];
assert.equal(nodes[1].children.length,1);
assert.equal(matches({marker,messageId}),true);
"""
    subprocess.run(
        ["node", "--input-type=module", "-e", code, callback],
        check=True,
        capture_output=True,
    )
