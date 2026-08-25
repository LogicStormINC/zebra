#!/usr/bin/env node
/**
 * 路由冒烟验证：启动 dev server 后，检查全部导航路由与详情路由返回 200。
 * 用法：node scripts/verify-routes.mjs [baseUrl]
 */
const baseUrl = process.argv[2] ?? 'http://localhost:3000';

// 全部列表路由（来自 nav-config PRD 7.2/7.3）
const listRoutes = [
  '/overview',
  '/integrations/onboarding',
  '/integrations/hosts',
  '/integrations/hosts/host_01H9TRENCH',
  '/integrations/trust',
  '/integrations/connectors',
  '/integrations/connectors/conn_trench_01',
  '/integrations/backend-manifests',
  '/integrations/backend-manifests/bm_trench_v5',
  '/integrations/bindings',
  '/agents/definitions',
  '/agents/definitions/def_trench_code_reviewer',
  '/agents/releases',
  '/agents/capability-profiles',
  '/agents/policies/models',
  '/agents/policies/tools',
  '/agents/policies/memory',
  '/agents/policies/runtime',
  '/runtime/tasks',
  '/runtime/tasks/tsk_01JK2M4Q8T',
  '/runtime/tasks/tsk_01JK2LR3XA',
  '/runtime/tasks/tsk_01JK2LP9ZC',
  '/runtime/orchestrations',
  '/runtime/orchestrations/orch_8842f',
  '/runtime/subagents',
  '/runtime/approvals',
  '/runtime/host-effects',
  '/runtime/artifacts',
  '/runtime/workers',
  '/frontend/profiles',
  '/frontend/profiles/fp_trench_web',
  '/frontend/hooks',
  '/frontend/client-sessions',
  '/frontend/client-bindings',
  '/frontend/client-effects',
  '/frontend/mounted-inspector',
  '/quality/conformance',
  '/quality/conformance/conf_20260826_02',
  '/quality/dry-runs',
  '/quality/rollouts',
  '/quality/evaluations',
  '/quality/release-gates',
  '/governance/policies',
  '/governance/quotas',
  '/governance/usage',
  '/governance/audit',
  '/governance/security',
  '/governance/reconciliation',
  '/system/environments',
  '/system/operators',
  '/system/feature-flags',
  '/system/credentials',
  '/system/notifications',
  '/system/health'
];

async function main() {
  let failed = 0;
  for (const route of listRoutes) {
    try {
      const response = await fetch(`${baseUrl}${route}`, { redirect: 'follow' });
      const ok = response.ok;
      if (!ok) failed += 1;
      console.log(`${ok ? 'PASS' : 'FAIL'} ${response.status} ${route}`);
    } catch (error) {
      failed += 1;
      console.log(`FAIL ERR ${route} ${error.message}`);
    }
  }
  console.log(`\n${listRoutes.length - failed}/${listRoutes.length} routes passed`);
  process.exit(failed > 0 ? 1 : 0);
}

main();
