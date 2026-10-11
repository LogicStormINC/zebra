"""Execute actual shared-runner fragments with mocked I/O; no live acceptance claim."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from test_joint_navigation_cases import shared_runner

BOOTSTRAP = r"""
import assert from 'node:assert/strict';
import path from 'node:path';
import {EventEmitter} from 'node:events';
import {pathToFileURL} from 'node:url';
const {closeNativeChild} = await import(pathToFileURL(process.argv[2]).href);
const source = process.argv[1];
const start = source.indexOf('    if (faultCase || takeoverCase || authorityCase) {');
const end = source.indexOf('    phase = "navigation";', start);
assert.ok(start >= 0 && end > start);
const AsyncFunction = Object.getPrototypeOf(async function(){}).constructor;
const makeHook = (body = source.slice(start, end)) => new AsyncFunction(
  'assert','path','spawn','guard','setTimeout','clearTimeout','config','turn',
  'faultCase','takeoverCase','authorityCase','authorityObserver','caseId','closeNativeChild',
  'let operatorChild,operatorExit,operatorClose,operatorTimer,operatorResult;\n' +
  'let operatorClosed = false;\n' + body +
  '\nreturn {child:operatorChild,exit:operatorExit,close:operatorClose,result:operatorResult};');
const events = [];
const config = {python:'/qa/python',operator_script:'/qa/operator.py',
  fault_script:'/qa/fault.py',timeout_ms:5000,browser_container:'NOT_A_TARGET'};
const turn = {conversation_key:'conversation',run_id:'run',turn_id:'turn',
  browser_container:'NOT_A_TARGET'};
let spawned = 0, timerCallback;
class Child extends EventEmitter {
  constructor() {
    super(); this.stdout = new EventEmitter(); this.stdin = new EventEmitter();
    this.exitCode = null; this.signalCode = null;
    this.stdin.end = (value) => { this.input = JSON.parse(value); events.push('stdin'); };
    this.stdin.destroy = () => { this.stdin.destroyed = true; };
    this.stdout.destroy = () => { this.stdout.destroyed = true; };
  }
  kill(signal) { events.push(signal); }
  complete(proof = {status:'passed'}, code = 0) {
    this.stdout.emit('data',Buffer.from(JSON.stringify(proof)));
    this.exitCode = code; this.emit('close',code);
  }
}
const child = new Child();
const spawn = (executable,argv,options) => {
  spawned++; events.push('spawn');
  assert.equal(executable,config.python); assert.equal(argv.length,1);
  child.script = argv[0]; assert.deepEqual(options.stdio,['pipe','pipe','ignore']);
  assert.equal(options.detached,process.platform !== 'win32');
  assert.equal(options.env,process.env); return child;
};
const guard = () => events.push('guard');
const setTimer = (callback,delay) => {
  timerCallback = callback; assert.equal(delay,config.timeout_ms); return 77;
};
const clearTimer = (id) => { assert.equal(id,77); events.push('clear'); };
function invoke({fault=false,takeover=false,authority=false,observer,
                 guardCallback=guard,hook=makeHook()}={}) {
  return hook(assert,path,spawn,guardCallback,setTimer,clearTimer,config,turn,
              fault,takeover,authority,observer,config.case_id ?? 'worker_takeover',
              closeNativeChild);
}
"""


def run_fragment(code: str) -> None:
    result = subprocess.run(
        [
            "node",
            "--input-type=module",
            "-e",
            BOOTSTRAP + code,
            shared_runner().read_text(),
            str(Path(__file__).with_name("browser_guard_rpc.mjs").resolve()),
        ],
        timeout=5,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr[-4000:]


@pytest.mark.parametrize("case", ["slow_execution", "partial_failure", "worker_takeover"])
def test_operator_uses_private_three_field_input_and_correct_executor(case):
    run_fragment(
        f"const takeover = {str(case == 'worker_takeover').lower()};\n"
        + f"config.case_id = {case!r};\n"
        + r"""
const pending = await invoke({fault:!takeover,takeover});
assert.deepEqual(events,['guard','spawn','stdin']);
assert.deepEqual(child.input,{case_id:caseId,conversation_key:'conversation',run_id:'run'});
assert.equal(child.script,takeover ? config.operator_script : config.fault_script);
assert.equal('browser_container' in child.input,false);
child.complete(); assert.equal((await pending.result).status,'passed');
assert.equal(events.at(-1),'clear');
""".replace("caseId", repr(case))
    )


def test_authority_waits_for_actual_observer_gate_and_forwards_exact_target():
    run_fragment(
        r"""
let release;
const barrier = new Promise((resolve)=>{release=resolve;});
const payload = {case_id:'authority',subcase:'approval',conversation_key:'conversation',
                 run_id:'run',turn_id:'turn'};
const observer = {beforeOperator: async (actual) => {
  assert.equal(actual,turn); events.push('observe'); await barrier; return payload;
}};
const running = invoke({authority:true,observer});
assert.equal(spawned,0); assert.deepEqual(events,['observe']);
release(); const pending = await running;
assert.deepEqual(events,['observe','guard','spawn','stdin']);
assert.deepEqual(child.input,payload); assert.equal(child.script,config.operator_script);
child.complete(); await pending.result;
"""
    )


def test_failed_observer_or_guard_and_relative_executor_never_fall_back():
    run_fragment(
        r"""
await assert.rejects(invoke({authority:true,observer:{beforeOperator:async()=>{
  throw new Error('pending approval not visible');
}}}),/not visible/);
assert.equal(spawned,0);
for (const flags of [{fault:true},{takeover:true},{authority:true,
  observer:{beforeOperator:async()=>({case_id:'authority'})}}]) {
  await assert.rejects(invoke({...flags,guardCallback:()=>{throw new Error('drift');}}),/drift/);
  assert.equal(spawned,0);
}
config.operator_script = 'relative.py';
await assert.rejects(invoke({takeover:true})); assert.equal(spawned,0);
"""
    )


@pytest.mark.parametrize("fault", ["output_limit", "timeout", "exit", "failed_proof"])
def test_operator_failure_is_not_a_pass_and_cleanup_timer_is_cleared(fault):
    run_fragment(
        f"const fault = {fault!r};\n"
        + r"""
const pending = await invoke({takeover:true});
let settled = false;
pending.result.finally(()=>{settled=true;}).catch(()=>{});
if (fault === 'output_limit') {
  child.stdout.emit('data',Buffer.alloc(65537,'x')); assert.equal(events.at(-1),'SIGKILL');
} else if (fault === 'timeout') {
  timerCallback(); assert.equal(events.at(-1),'SIGKILL');
} else if (fault === 'exit') child.complete({status:'passed'},2);
else child.complete({status:'failed'});
if (fault === 'output_limit' || fault === 'timeout') {
  await new Promise(setImmediate);
  assert.equal(settled,false); assert.equal(events.includes('clear'),false);
  assert.equal(child.stdin.destroyed,true); assert.notEqual(child.stdout.destroyed,true);
  child.emit('close',9);
}
await assert.rejects(pending.result);
assert.equal(events.includes('clear'),true);
if (fault === 'output_limit' || fault === 'timeout') {
  await new Promise(setImmediate); assert.equal(child.stdout.destroyed,true);
}
"""
    )


def test_normal_and_authority_final_gates_execute_without_operator_or_fake_final():
    run_fragment(
        r"""
const classify = new Function('assert','config',source.slice(source.indexOf('const caseId ='),
  source.indexOf('const base ='))+';return {simple,noFinalCase,navigationCase};');
const countStart = source.indexOf('    assert.equal(finalCount,');
const countEnd = source.indexOf('\n',countStart);
const count = new Function('assert','noFinalCase','finalCount',source.slice(countStart,countEnd));
const snapshotStart = source.indexOf('    assert.equal(final.status,');
const snapshotEnd = source.indexOf('    if (simple) {',snapshotStart);
const snapshot = new Function('assert','noFinalCase','config','simple','final','finalObserved',
  'turn',source.slice(snapshotStart,snapshotEnd));
const partialStart = source.indexOf('    if (simple) {',
  source.indexOf('const publicOutputCount ='));
const partial = new Function('assert','simple','noFinalCase','publicOutputCount','toolCount',
  'navigationCase','publicVisibility',source.slice(partialStart,countStart));
const normal = ['simple_answer','multi_source','tool_only','image','inline_video',
  'chart_markdown_latex','revision','slow_execution','partial_failure','worker_takeover',
  'frame_disconnect','navigation'];
const cases = normal.map((case_id)=>({case_id})).concat(
  ['cancel','approval','scope_denial','unknown_write_receipt'].map((authority_subcase)=>
    ({case_id:'authority',authority_subcase})));
for (const item of cases) {
  const flags = classify(assert,item);
  assert.equal(flags.noFinalCase,item.case_id === 'authority' &&
    ['cancel','approval'].includes(item.authority_subcase));
  const expectedCount = flags.noFinalCase ? 0 : 1;
  count(assert,flags.noFinalCase,expectedCount);
  assert.throws(()=>count(assert,flags.noFinalCase,1-expectedCount));
  const expectedStatus = flags.noFinalCase
    ? item.authority_subcase === 'cancel' ? 'cancelled' : 'failed' : 'completed';
  const final = {...turn,status:expectedStatus,answer:'MARKER'};
  snapshot(assert,flags.noFinalCase,{...item,expected:'MARKER'},flags.simple,final,
           !flags.noFinalCase,turn);
  if (flags.noFinalCase) {
    assert.throws(()=>snapshot(assert,true,item,false,{...final,status:'completed'},true,turn));
  } else {
    assert.throws(()=>snapshot(assert,false,{...item,expected:'MARKER'},flags.simple,
      {...final,answer:'missing'},true,turn));
    const goodVisibility = [{before_terminal:true,before_final_receipt:true}];
    partial(assert,flags.simple,false,flags.simple ? 0 : 1,flags.simple ? 0 : 1,
      flags.navigationCase,goodVisibility);
    if (!flags.simple && !flags.navigationCase) {
      assert.throws(()=>partial(assert,false,false,1,1,false,[]));
    }
  }
}
const pending = await invoke();
assert.equal(spawned,0); assert.equal(pending.result,undefined);
"""
    )


@pytest.mark.parametrize("emit_close", [True, False])
def test_finally_joins_bounded_child_close_and_always_closes_browser_last(emit_close):
    run_fragment(
        f"const emitClose = {str(emit_close).lower()};\n"
        + r"""
const cleanupStart = source.lastIndexOf('\n} finally {') + '\n} finally {'.length;
const cleanupEnd = source.indexOf('\n}\nif (result)',cleanupStart);
assert.ok(cleanupStart > 0 && cleanupEnd > cleanupStart);
const cleanup = new AsyncFunction('commitObserver','clearTimeout','operatorTimer',
  'operatorChild','operatorExit','operatorClose','operatorClosed','browser','guardRpc',
  'closeNativeChild','assert',source.slice(cleanupStart,cleanupEnd));
const pending = await invoke({takeover:true}); events.length = 0;
let settled = false, succeeded = false, exitSettled = false, closeObserved = false;
child.once('close',()=>{closeObserved=true; events.push('actual_close');});
pending.exit.finally(()=>{exitSettled=true;}).catch(()=>{});
const started = performance.now();
const running = cleanup({abort:async()=>events.push('abort')},clearTimer,77,child,
  pending.exit,pending.close,false,{close:async()=>{
    assert.equal(child.stdout.destroyed,true); events.push('browser');
  }},
  {close:async()=>events.push('guard_close')},closeNativeChild,assert)
  .then(()=>{settled=true; succeeded=true;},(error)=>{settled=true; throw error;});
running.catch(()=>{});
await new Promise(setImmediate);
assert.deepEqual(events,['clear','SIGKILL','abort','SIGKILL','guard_close']);
assert.equal(child.stdin.destroyed,true); assert.notEqual(child.stdout.destroyed,true);
assert.equal(settled,false);
if (emitClose) {
  child.complete(); await running;
  assert.equal(closeObserved,true); assert.equal(exitSettled,true);
  assert.equal(child.stdout.destroyed,true); assert.equal(settled,true);
  assert.equal(succeeded,true);
  assert.deepEqual(events.slice(-3),['clear','actual_close','browser']);
} else {
  let watchdog;
  try {
    await assert.rejects(Promise.race([running,new Promise((_,reject)=>{
      watchdog = globalThis.setTimeout(()=>reject(new Error('cleanup_unbounded')),2500);
    })]),/QA cleanup must confirm actual child close/);
  } finally { globalThis.clearTimeout(watchdog); }
  const elapsed = performance.now() - started;
  assert.ok(elapsed >= 900 && elapsed < 2500,`bounded join took ${elapsed}ms`);
  assert.equal(settled,true); assert.equal(succeeded,false);
  assert.equal(closeObserved,false); assert.equal(exitSettled,false);
  assert.equal(child.stdout.destroyed,true);
  assert.deepEqual(events,['clear','SIGKILL','abort','SIGKILL','guard_close','browser']);
}
"""
    )
