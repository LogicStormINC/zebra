import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
/** Runs the actual Python source projector and schema checks; synthetic source facts only. */
export function producerRecording(): unknown[] {
  const cwd = fileURLToPath(new URL('../../../../../', import.meta.url));
  return JSON.parse(execFileSync('uv', ['run', '--frozen', 'python', 'sdks/typescript/packages/client-core/tests/agui-view-producer.py'], { cwd, encoding: 'utf8' }));
}
