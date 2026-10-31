"""Run: python3 -B tests/test_maintenance_checks.py. Actual bootstrap/send guards, no services."""

import ast
import subprocess
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
LIVE = ROOT.parents[1] / "work/maintenance-ux-live"
api_paths = [ROOT / "zebra_erpnext/api.py"]
front_paths = [ROOT / "frontend/index.tsx"]
if (LIVE / "api.after.py").exists():
    api_paths.append(LIVE / "api.after.py")
    front_paths.append(LIVE / "index.after.tsx")
for path in api_paths:
    function = next(
        n
        for n in ast.parse(path.read_text()).body
        if isinstance(n, ast.FunctionDef) and n.name == "bootstrap"
    )
    function.decorator_list = []
    frappe = SimpleNamespace(
        conf={},
        get_list=lambda *a, **kw: [SimpleNamespace(name="QA")],
        defaults=SimpleNamespace(get_global_default=lambda key: "QA"),
    )
    scope = dict(
        frappe=frappe,
        cloud=SimpleNamespace(principal=lambda: "qa-user"),
        chat=SimpleNamespace(MODEL_OPTIONS=[], REASONING_OPTIONS=[]),
    )
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(path), "exec"), scope)
    for value in (True, False, None, "true", 1):
        frappe.conf["zebra_agent"] = {"enabled": True, "admission_paused": value}
        result = scope["bootstrap"]()
        assert result["enabled"] is True and result["admission_paused"] is (value is True)
        assert set(result) == {
            "user",
            "companies",
            "company",
            "enabled",
            "admission_paused",
            "model_profile",
            "model_options",
            "reasoning_options",
            "reasoning_effort",
            "https_url",
        }

# Execute the actual TypeScript functions after the already-installed esbuild transform.
# RPC doubles prove paused cached/fresh status prevents both submit and retry mutation.
subprocess.run(
    ["node", "-", *map(str, front_paths)],
    cwd=ROOT,
    check=True,
    text=True,
    input=(
        "\nconst assert = require('node:assert/strict');\ncon"
        "st fs = require('node:fs');\nconst vm = require('no"
        "de:vm');\nconst {transformSync} = require('esbuild'"
        ");\n(async () => {\n for (const path of process.argv"
        ".slice(2)) {\n  const source = fs.readFileSync(path"
        ", 'utf8');\n  const start = source.indexOf('  async"
        " function send(');\n  const end = source.indexOf(' "
        " function pickSuggestion(', start);\n  assert.ok(st"
        "art >= 0 && end > start);\n  const functions = tran"
        "sformSync(source.slice(start, end) + '\\n globalThi"
        "s.actions = {send' +\n    (source.slice(start, end)"
        ".includes('async function retryFresh') ? ', retryF"
        "resh' : '') + '};', {loader:'ts'}).code;\n  const c"
        "alls = [], errors = [];\n  const context = {textRef"
        ":{current:'synthetic'},boot:{enabled:true,admissio"
        "n_paused:true}, text:'synthetic', readingFiles:fal"
        "se,\n    sendGate:{current:false}, savingSettings:f"
        "alse, loadingSettings:false,\n    state:{status:'id"
        "le',command_outcome:{retry_eligible:true,run_id:'r"
        "un',accepted_event_id:'event'}},\n    isActive:()=>"
        "false, setSending:()=>{}, setError:()=>{}, setNoti"
        "ce:()=>{},\n    viewEpoch:{current:1}, selected:'ow"
        "ned', activeConversation:{current:'owned'},\n    cr"
        "ypto:{randomUUID:()=> 'synthetic-id'},\n    refresh"
        "Bootstrap:async()=>{calls.push('bootstrap');return"
        " context.latest;},\n    latest:{enabled:true,admiss"
        "ion_paused:true},\n    setState:()=>{calls.push('st"
        "ate-mutation');},\n    api:async(method)=>{calls.pu"
        "sh(method);throw new Error('safe generic RPC error"
        "');},\n    fail:error=>errors.push(error.message),\n"
        "    validateAttachmentBatch:()=>{}, filesRef:{curr"
        "ent:[]}, model:'flash',reasoning:'high',\n    pendi"
        "ng:{current:null}, submissionIdentity:()=>false, p"
        "ageContext:()=>({})};\n  vm.createContext(context);"
        "vm.runInContext(functions, context);\n  assert.equa"
        "l(await context.actions.send(),false);\n  if(contex"
        "t.actions.retryFresh) await context.actions.retryF"
        "resh();\n  assert.deepEqual(calls,[]);\n  context.bo"
        "ot.admission_paused=false;\n  assert.equal(await co"
        "ntext.actions.send(),false);\n  assert.deepEqual(ca"
        "lls,['bootstrap']);calls.length=0;\n  if(context.ac"
        "tions.retryFresh){await context.actions.retryFresh"
        "();assert.deepEqual(calls,['bootstrap']);calls.len"
        "gth=0;}\n  context.latest.admission_paused=false;\n "
        " await assert.rejects(context.actions.send(),/safe"
        " generic RPC error/);\n  assert.deepEqual(calls,['b"
        "ootstrap','submit']);\n  assert.deepEqual(errors,['"
        "safe generic RPC error']);\n  assert.ok(source.incl"
        "udes('void refreshBootstrap().catch(fail)'));\n  co"
        "nst observationStart = source.indexOf('  async fun"
        "ction observe(');\n  const observationEnd = source."
        "indexOf('  async function saveSettings(', observat"
        "ionStart);\n  assert.ok(observationStart >= 0 && ob"
        "servationEnd > observationStart);\n  const observat"
        "ion = transformSync(source.slice(observationStart,"
        " observationEnd) +\n    '\\n globalThis.observeCurre"
        "nt = observe;', {loader:'ts'}).code;\n  let release"
        "Bootstrap;\n  context.refreshBootstrap = () => new "
        "Promise(resolve => { releaseBootstrap = resolve; }"
        ");\n  context.isCurrentView = (name, epoch, active,"
        " current) => name === active && epoch === current;"
        "\n  const observed = [];\n  context.select = async n"
        "ame => observed.push(name);\n  vm.runInContext(obse"
        "rvation, context);\n  let waiting = context.observe"
        "Current();\n  releaseBootstrap(); await waiting;\n  "
        "assert.deepEqual(observed, ['owned']);\n  observed."
        "length = 0;\n  waiting = context.observeCurrent();\n"
        "  context.activeConversation.current = 'other'; co"
        "ntext.viewEpoch.current++;\n  releaseBootstrap(); a"
        "wait waiting;\n  assert.deepEqual(observed, []);\n  "
        "assert.ok(source.includes('disabled={!boot?.enable"
        "d || boot.admission_paused === true'));\n }\n consol"
        "e.log('PASS actual cached/fresh maintenance guards"
        ", submit/retry refusal, unchanged RPC errors and r"
        "efresh wiring');\n})().catch(error=>{console.error("
        "error);process.exitCode=1;});\n"
    ),
)
print("PASS actual bootstrap strict boolean for local and optional production-baseline candidates")
