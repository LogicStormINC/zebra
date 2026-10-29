"""Run: python3 cloud-patches/tests/test_build_initial_images.py; no Docker mutations."""
import contextlib
import importlib.util
import io
from pathlib import Path
import sys
import tempfile

spec=importlib.util.spec_from_file_location('build_initial_images',Path(__file__).resolve().parents[1]/'build_initial_images.py')
build=importlib.util.module_from_spec(spec);spec.loader.exec_module(build)
commands=[]
build.subprocess.run=lambda command,**kwargs:commands.append(command)
build.image_id=lambda reference:reference if reference.startswith('sha256:') else build.BASES['api']
with contextlib.redirect_stdout(io.StringIO()):
    sys.argv=['build_initial_images.py','--role','all','--check-only']
    build.main()
assert commands==[]
with contextlib.redirect_stdout(io.StringIO()):
    sys.argv=['build_initial_images.py','--role','api','--stage','followup']
    build.main()
assert commands[0]==['docker','image','tag',build.BASES['api'],
    'erpnext-agent-api-base:'+build.BASES['api'].removeprefix('sha256:')]
assert commands[1][:3]==['docker','build','--pull=false'] and '--network=none' in commands[1]
assert commands[1][commands[1].index('--tag')+1]=='erpnext-agent-api:http-input-followup-review'
commands.clear()
build.image_id=lambda reference:'wrong' if reference==build.BASES['worker'] else reference
sys.argv=['build_initial_images.py']
try:build.main()
except SystemExit:pass
else:raise AssertionError('Changed base identity was accepted')
assert commands==[], 'Must validate every selected base before any tag/build'
build.image_id=lambda reference:build.BASES['api']
with tempfile.TemporaryDirectory() as folder:
    build.ROOT=Path(folder)
    (build.ROOT/'Dockerfile.api').write_text('FROM unrelated:latest\n')
    sys.argv=['build_initial_images.py','--role','api']
    try:build.main()
    except SystemExit:pass
    else:raise AssertionError('Dockerfile reference drift was accepted')
assert commands==[]
print('PASS local base identity preflight, exact-ID tagging, no-pull build and fail-closed drift checks')
