/**
 * 全局搜索静态实体索引（PRD 8.4）。
 *
 * 从 repository 的 mock 数据构建可搜索实体集合，供全局搜索（kbar）
 * 定位实体：Task / Session / Effect / Host / Trust / Connector /
 * Manifest / Namespace / AgentDefinition / Release / Artifact /
 * Orchestration，以及全部版本化对象的 digest 值。
 * 接入 Management API 后，本文件改为调用搜索接口构建，接口不变。
 */
import { repository } from './repository';

export type SearchEntityKind =
  | 'task'
  | 'clientSession'
  | 'clientEffect'
  | 'host'
  | 'trust'
  | 'connector'
  | 'manifest'
  | 'namespace'
  | 'agentDefinition'
  | 'agentRelease'
  | 'artifact'
  | 'orchestration'
  | 'digest';

export type SearchEntity = {
  kind: SearchEntityKind;
  /** 结果主标题 */
  label: string;
  /** 实体标识（Task ID / Session ID / Run Ref / digest 值等） */
  id: string;
  /** 跳转目标（实体详情；无详情页的实体跳列表页） */
  href: string;
  /** 参与关键词匹配的附加文本 */
  keywords: string[];
};

export const SEARCH_KIND_LABELS: Record<SearchEntityKind, string> = {
  task: 'Task',
  clientSession: 'Client Session',
  clientEffect: 'Client Effect',
  host: 'Host 应用',
  trust: '入站信任',
  connector: 'Connector',
  manifest: 'Backend Manifest',
  namespace: 'Namespace Binding',
  agentDefinition: 'AgentDefinition',
  agentRelease: 'Agent Release',
  artifact: 'Artifact',
  orchestration: 'Orchestration',
  digest: 'Digest'
};

function buildEntities(): SearchEntity[] {
  const entities: SearchEntity[] = [];

  for (const task of repository.tasks()) {
    entities.push({
      kind: 'task',
      label: task.title,
      id: task.id,
      href: `/runtime/tasks/${task.id}`,
      keywords: [task.hostAppId, task.namespace, task.agentReleaseId, task.agentName, task.status]
    });
  }

  for (const session of repository.clientSessions()) {
    entities.push({
      kind: 'clientSession',
      label: `${session.frontendAppId} 会话 · ${session.route}`,
      id: session.id,
      href: '/frontend/client-sessions',
      keywords: [
        session.hostAppId,
        session.namespace,
        session.frontendAppId,
        session.buildId,
        session.role,
        session.status
      ]
    });
  }

  for (const effect of repository.clientEffects()) {
    entities.push({
      kind: 'clientEffect',
      label: `${effect.action} · ${effect.status}`,
      id: effect.id,
      href: '/frontend/client-effects',
      keywords: [
        effect.taskId,
        effect.runId,
        effect.action,
        effect.hostAppId,
        effect.frontendAppId,
        effect.clientSessionId,
        effect.status
      ]
    });
  }

  for (const host of repository.hosts()) {
    entities.push({
      kind: 'host',
      label: host.name,
      id: host.appId,
      href: `/integrations/hosts/${host.id}`,
      keywords: [host.id, host.appId, host.owner, host.environment, host.status, ...host.tags]
    });
  }

  for (const trust of repository.trusts()) {
    entities.push({
      kind: 'trust',
      label: `${trust.hostAppId} 入站信任 · rev ${trust.revision}`,
      id: trust.id,
      href: `/integrations/trust?hostAppId=${encodeURIComponent(trust.hostAppId)}`,
      keywords: [trust.hostAppId, trust.issuer, trust.policyVersion, trust.status, trust.health]
    });
  }

  for (const connector of repository.connectors()) {
    entities.push({
      kind: 'connector',
      label: `${connector.hostAppId} Connector · rev ${connector.latestRevision}`,
      id: connector.id,
      href: `/integrations/connectors/${connector.id}`,
      keywords: [connector.hostAppId, connector.baseUri, connector.status, connector.health]
    });
  }

  for (const manifest of repository.manifests()) {
    entities.push({
      kind: 'manifest',
      label: `${manifest.hostAppId} Manifest · rev ${manifest.revision}`,
      id: manifest.id,
      href: `/integrations/backend-manifests/${manifest.id}`,
      keywords: [
        manifest.hostAppId,
        manifest.protocolVersion,
        manifest.status,
        ...manifest.tools.map((tool) => tool.name)
      ]
    });
  }

  for (const binding of repository.bindings()) {
    entities.push({
      kind: 'namespace',
      label: binding.namespace,
      id: binding.id,
      href: `/integrations/bindings?namespace=${encodeURIComponent(binding.namespace)}`,
      keywords: [
        binding.hostAppId,
        binding.namespace,
        binding.environment,
        binding.agentReleaseId,
        binding.status
      ]
    });
  }

  for (const definition of repository.agentDefinitions()) {
    entities.push({
      kind: 'agentDefinition',
      label: definition.name,
      id: definition.id,
      href: `/agents/definitions/${definition.id}`,
      keywords: [definition.name, definition.status, ...definition.capabilityCeiling]
    });
  }

  for (const release of repository.agentReleases()) {
    entities.push({
      kind: 'agentRelease',
      label: `${release.definitionName} · v${release.version}（${release.channel}）`,
      id: release.id,
      href: '/agents/releases',
      keywords: [
        release.definitionId,
        release.definitionName,
        release.channel,
        release.status,
        `v${release.version}`
      ]
    });
  }

  for (const artifact of repository.artifacts()) {
    entities.push({
      kind: 'artifact',
      label: artifact.name,
      id: artifact.id,
      href: '/runtime/artifacts',
      keywords: [artifact.taskId, artifact.kind, artifact.name]
    });
  }

  for (const run of repository.orchestrations()) {
    entities.push({
      kind: 'orchestration',
      label: `Orchestration · ${run.strategy} · ${run.nodes.length} 节点`,
      id: run.runRef,
      href: `/runtime/orchestrations/${run.runRef}`,
      keywords: [run.taskId, run.strategy, run.status]
    });
  }

  // digest 作为独立可搜索项：命中后跳到所属实体详情（PRD 8.4 Digest 定位）
  const digestOwners: { digest: string; href: string; label: string }[] = [
    ...repository.trusts().map((trust) => ({
      digest: trust.digest,
      href: `/integrations/trust?hostAppId=${encodeURIComponent(trust.hostAppId)}`,
      label: `${trust.hostAppId} 入站信任 digest`
    })),
    ...repository.connectors().map((connector) => ({
      digest: connector.digest,
      href: `/integrations/connectors/${connector.id}`,
      label: `${connector.hostAppId} Connector digest`
    })),
    ...repository.manifests().map((manifest) => ({
      digest: manifest.digest,
      href: `/integrations/backend-manifests/${manifest.id}`,
      label: `${manifest.hostAppId} Manifest digest`
    })),
    ...repository.agentReleases().map((release) => ({
      digest: release.digest,
      href: '/agents/releases',
      label: `${release.definitionName} v${release.version} Release digest`
    })),
    ...repository.artifacts().map((artifact) => ({
      digest: artifact.digest,
      href: '/runtime/artifacts',
      label: `${artifact.name} Artifact digest`
    }))
  ];

  for (const owner of digestOwners) {
    if (!owner.digest) continue;
    entities.push({
      kind: 'digest',
      label: owner.label,
      id: owner.digest,
      href: owner.href,
      keywords: [owner.digest]
    });
  }

  return entities;
}

/** 静态实体索引：mock 阶段模块级构建一次（确定性数据，无随机/时间依赖）。 */
export const searchEntities: SearchEntity[] = buildEntities();
