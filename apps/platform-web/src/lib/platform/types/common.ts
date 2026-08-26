/**
 * 通用展示模型：状态语义、版本化对象、环境。
 * PRD 25.1：状态颜色必须与文字共同表达。
 */
export type StatusTone =
  | 'success' // 绿：正常、完成、通过
  | 'running' // 蓝：运行、处理中
  | 'waiting' // 紫：等待、需输入
  | 'warning' // 琥珀：警告、即将过期
  | 'failure' // 红：失败、拒绝、撤销
  | 'uncertain' // 橙：不确定
  | 'draft'; // 灰：草稿、未开始

export type RevisionedObject = {
  revision: number;
  digest: string;
  status: 'draft' | 'published' | 'deprecated' | 'revoked';
  createdBy: string;
  createdAt: string;
};

export type Environment = 'development' | 'staging' | 'production';
