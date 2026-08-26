import type { FrontendProfile } from '@/lib/platform/types';

/**
 * Hook Contract 代码生成器（PRD 13.7）。
 *
 * 只依据所选 Frontend Profile 生成 Contract Name、Schema 与 Provider 配置；
 * 不生成业务 Handler 实现（PRD 13.7 约束）。
 */

export type HookFramework = 'react' | 'nextjs' | 'copilotkit';
export type HookLanguage = 'typescript' | 'javascript';

export const HOOK_FRAMEWORK_LABELS: Record<HookFramework, string> = {
  react: 'React',
  nextjs: 'Next.js App Router',
  copilotkit: 'CopilotKit Adapter'
};

export const HOOK_FILE_NAMES: Record<HookFramework, Record<HookLanguage, string>> = {
  react: {
    typescript: 'app/zebra-agent-provider.tsx',
    javascript: 'app/zebra-agent-provider.jsx'
  },
  nextjs: {
    typescript: 'app/layout.tsx + app/api/zebra/[...path]/route.ts',
    javascript: 'app/layout.jsx + app/api/zebra/[...path]/route.js'
  },
  copilotkit: {
    typescript: 'app/copilot-adapter.tsx',
    javascript: 'app/copilot-adapter.jsx'
  }
};

function firstReadable(profile: FrontendProfile) {
  return profile.readables[0] ?? null;
}

function secondReadable(profile: FrontendProfile) {
  return profile.readables[1] ?? null;
}

function firstAction(profile: FrontendProfile) {
  return profile.actions[0] ?? null;
}

function humanConfirmedAction(profile: FrontendProfile) {
  return (
    profile.actions.find((action) => action.executionMode === 'human_confirmed') ?? null
  );
}

function headerComment(profile: FrontendProfile, frameworkLabel: string): string {
  const readable = firstReadable(profile);
  return [
    `// Zebra Agent Frontend Hook Contract 示例（${frameworkLabel}）`,
    '// 声明：示例代码只包含 Contract Name、Schema 和 Provider 配置，',
    '//       不生成业务 Handler 实现（PRD 13.7）。',
    `// Profile : ${profile.id} (rev ${profile.revision})`,
    `// Digest  : ${profile.digest.slice(0, 16)}…`,
    `// Build   : ${profile.buildId}`,
    `// Origin  : ${profile.allowedOrigins.join(', ') || '（未配置）'}`,
    readable ? `// 首个 Readable 示例 : ${readable.name}` : '// 该 Profile 暂未声明 Readable'
  ].join('\n');
}

function readableComment(profile: FrontendProfile, name: string): string {
  const readable = profile.readables.find((item) => item.name === name);
  if (!readable) return '';
  return ` // sensitivity=${readable.sensitivity} max=${readable.maxBytes}B update=${readable.updateStrategy}`;
}

function actionComment(profile: FrontendProfile, name: string): string {
  const action = profile.actions.find((item) => item.name === name);
  if (!action) return '';
  return ` // risk=${action.risk} mode=${action.executionMode} timeout=${action.timeoutMs}ms`;
}

function reactCode(profile: FrontendProfile, language: HookLanguage): string {
  const readable = firstReadable(profile);
  const readable2 = secondReadable(profile);
  const action = firstAction(profile);
  const approvalAction = humanConfirmedAction(profile);
  const ts = language === 'typescript';

  return `${headerComment(profile, 'React')}

import {
  ZebraAgentProvider,
  useZebraReadable,
  useZebraAction,
  useZebraApproval,
  useZebraClarification
} from '@zebra-agent/react';

// 1. 根组件挂载 Provider：浏览器只连接同源 BFF，禁止 Direct Browser 模式${ts ? '' : '（JavaScript 版）'}
export function AppRoot(${ts ? '{ children }: { children: React.ReactNode }' : '{ children }'}) {
  return (
    <ZebraAgentProvider
      appId="${profile.frontendAppId}"
      profileId="${profile.id}"
      profileDigest="${profile.digest}"
      bffEndpoint="/api/zebra/session"
    >
      {children}
    </ZebraAgentProvider>
  );
}

// 2. 业务组件中订阅 Readable（平台注入的是脱敏后的上下文值）
function TicketBoard() {
  const route = useZebraReadable('${readable?.name ?? 'page.route'}');${readableComment(profile, readable?.name ?? 'page.route')}${
    readable2
      ? `
  const reportId = useZebraReadable('${readable2.name}');${readableComment(profile, readable2.name)}`
      : ''
  }

  // 3. 调用 Action：一次一效（Fence），Receipt 由 SDK 自动回传平台
  const ${action ? camel(action.name) : 'clientAction'} = useZebraAction('${action?.name ?? 'ui.none'}');${actionComment(profile, action?.name ?? 'ui.none')}

  // 4. human_confirmed Action 必须配置确认 UI：useZebraApproval 弹出确认对话框
  const [${approvalAction ? camel(approvalAction.name) : 'humanConfirm'}, confirmation] = useZebraApproval('${approvalAction?.name ?? 'ui.human_confirm'}');

  // 5. useZebraClarification（与 useZebraApproval 并列）：渲染 Agent 发起的澄清问题，
  //    用户答复经平台写回事件流，Agent 侧继续执行
  const [clarification, respondClarification] = useZebraClarification();

  function onAgentSuggest(ticketId${ts ? ': string' : ''}) {
    // Handler 实现由业务方编写：此处仅展示 Contract 调用方式
    ${action ? camel(action.name) : 'clientAction'}({ ticketId });
  }

  function onClarificationAnswer(answer${ts ? ': string' : ''}) {
    // Handler 实现由业务方编写：confirmation / clarification 的 UI 由 Host App 自行实现
    respondClarification({ questionId: clarification?.id, answer });
  }

  return null; // 业务渲染逻辑由 Host App 自行实现
}`;
}

function nextjsCode(profile: FrontendProfile, language: HookLanguage): string {
  const readable = firstReadable(profile);
  const action = firstAction(profile);
  const approvalAction = humanConfirmedAction(profile);
  const ts = language === 'typescript';

  return `${headerComment(profile, 'Next.js App Router')}

// ------------------------------------------------------------
// app/layout.tsx：在根布局挂载 Provider（客户端组件边界内）
// ------------------------------------------------------------
import { ZebraAgentProvider } from '@zebra-agent/react';

export default function RootLayout(${ts ? '{ children }: { children: React.ReactNode }' : '{ children }'}) {
  return (
    <html lang="zh-CN">
      <body>
        <ZebraAgentProvider
          appId="${profile.frontendAppId}"
          profileId="${profile.id}"
          profileDigest="${profile.digest}"
          bffEndpoint="/api/zebra"
        >
          {children}
        </ZebraAgentProvider>
      </body>
    </html>
  );
}

// ------------------------------------------------------------
// app/api/zebra/[...path]/route.ts：BFF 接入说明
// ------------------------------------------------------------
// import { createZebraBffHandler } from '@zebra-agent/next';
//
// 浏览器 SDK 只请求同源 /api/zebra/*；由 BFF 在服务端持有
// 签名授权调用平台 API，平台凭证与 Fence 校验绝不进入浏览器。
//
// export const { GET, POST } = createZebraBffHandler({
//   profileId: '${profile.id}',
//   buildId: '${profile.buildId}',
//   allowedOrigins: [${profile.allowedOrigins.map((origin) => `'${origin}'`).join(', ')}]
// });

// ------------------------------------------------------------
// app/${readable ? 'risk' : 'page'}/page.tsx：页面内使用 Hooks
// ------------------------------------------------------------
'use client';
import { useZebraReadable, useZebraAction, useZebraApproval, useZebraClarification } from '@zebra-agent/react';

export default function Page() {
  const route = useZebraReadable('${readable?.name ?? 'page.route'}');${readableComment(profile, readable?.name ?? 'page.route')}

  const ${action ? camel(action.name) : 'clientAction'} = useZebraAction('${action?.name ?? 'ui.none'}');${actionComment(profile, action?.name ?? 'ui.none')}

  // human_confirmed Action 必须配置确认 UI：useZebraApproval 弹出确认对话框
  const [${approvalAction ? camel(approvalAction.name) : 'humanConfirm'}, confirmation] = useZebraApproval('${approvalAction?.name ?? 'ui.human_confirm'}');

  // useZebraClarification（与 useZebraApproval 并列）：渲染 Agent 发起的澄清问题，
  // 用户答复经平台写回事件流，Agent 侧继续执行
  const [clarification, respondClarification] = useZebraClarification();
  function onClarificationAnswer(answer${ts ? ': string' : ''}) {
    // Handler 实现由业务方编写：confirmation / clarification 的 UI 由 Host App 自行实现
    respondClarification({ questionId: clarification?.id, answer });
  }

  // Handler 实现由业务方编写：此处仅展示 Contract 调用方式
  return null;
}`;
}

function copilotKitCode(profile: FrontendProfile, language: HookLanguage): string {
  const readable = firstReadable(profile);
  const action = firstAction(profile);
  const approvalAction = humanConfirmedAction(profile);
  const ts = language === 'typescript';

  return `${headerComment(profile, 'CopilotKit Adapter')}

// CopilotKit Adapter：把 Zebra Readable / Action 映射到 CopilotKit 体系。
// Adapter 只做 Contract 映射，不生成业务 Handler 实现。
import { CopilotKit, useCopilotReadable, useCopilotAction } from '@copilotkit/react-core';
import {
  ZebraAgentProvider,
  useZebraReadable,
  useZebraAction,
  useZebraApproval,
  useZebraClarification
} from '@zebra-agent/react';

export function AppRoot(${ts ? '{ children }: { children: React.ReactNode }' : '{ children }'}) {
  return (
    <CopilotKit runtimeUrl="/api/copilotkit">
      <ZebraAgentProvider
        appId="${profile.frontendAppId}"
        profileId="${profile.id}"
        profileDigest="${profile.digest}"
        bffEndpoint="/api/zebra"
      >
        {children}
      </ZebraAgentProvider>
    </CopilotKit>
  );
}

export function AgentPanel() {
  // 1. Zebra Readable → useCopilotReadable：注入脱敏后的上下文值
  const route = useZebraReadable('${readable?.name ?? 'page.route'}');${readableComment(profile, readable?.name ?? 'page.route')}
  useCopilotReadable({
    description: '${readable?.description ?? '当前路由路径'}',
    value: route
  });

  // 2. Zebra Action → useCopilotAction：包装为 CopilotKit 工具，内部转发 Zebra SDK
  const ${action ? camel(action.name) : 'clientAction'} = useZebraAction('${action?.name ?? 'ui.none'}');${actionComment(profile, action?.name ?? 'ui.none')}
  useCopilotAction({
    name: '${action?.name ?? 'ui.none'}',
    description: '${action?.description ?? 'Zebra Client Action'}',
    parameters: [
      { name: 'ticketId', type: 'string', description: '目标工单 ID', required: true }
    ],
    handler: (args${ts ? ': { ticketId: string }' : ''}) =>
      ${action ? camel(action.name) : 'clientAction'}(args) // Receipt 由 Zebra SDK 回传
  });

  // 3. human_confirmed Action 必须配置确认 UI：useZebraApproval 弹出确认对话框
  const [${approvalAction ? camel(approvalAction.name) : 'humanConfirm'}, confirmation] = useZebraApproval('${approvalAction?.name ?? 'ui.human_confirm'}');

  // 4. useZebraClarification（与 useZebraApproval 并列）：渲染 Agent 发起的澄清问题，
  //    用户答复经平台写回事件流，再转发回 CopilotKit 对话
  const [clarification, respondClarification] = useZebraClarification();
  function onClarificationAnswer(answer${ts ? ': string' : ''}) {
    // Handler 实现由业务方编写：confirmation / clarification 的 UI 由 Host App 自行实现
    respondClarification({ questionId: clarification?.id, answer });
  }

  return null; // 业务渲染逻辑由 Host App 自行实现
}`;
}

/** 下划线命名 → 小驼峰，用于生成 Hook 返回值变量名。 */
function camel(name: string): string {
  const parts = name.split('.');
  const last = parts[parts.length - 1];
  return last.replace(/_([a-z])/g, (_, ch: string) => ch.toUpperCase());
}

export function generateHookCode(
  profile: FrontendProfile,
  framework: HookFramework,
  language: HookLanguage
): string {
  switch (framework) {
    case 'nextjs':
      return nextjsCode(profile, language);
    case 'copilotkit':
      return copilotKitCode(profile, language);
    default:
      return reactCode(profile, language);
  }
}
