# Zebra Agent Runtime Upgrade Proposal v2.0

## 从 Agent Runtime 到 Agent Operating Runtime

| 字段 | 值 |
|---|---|
| 状态 | 长期目标提案；不是当前可执行任务表 |
| 版本 | v2.0 Draft |
| 项目边界 | 通用 Agent Runtime 基础设施，不承载业务系统、用户体系或商业化 |
| 当前实施基线 | [`执行收敛与最小Runtime_Task_Memory切片方案_v1.0.md`](./执行收敛与最小Runtime_Task_Memory切片方案_v1.0.md) |

本提案描述 Zebra 从 Agent Runtime 向 Agent Operating Runtime 演进的长期目标。
2026-07-28 的循环故障修复只激活 Runtime / Task Memory 的最小事件投影切片，
不提前激活本文完整 Memory 2.0、Agent Layer、Trust 或 Evaluation 路线。可执行
状态、Owner、分支和 owned paths 以 `docs/AGENT_TASKS.md` 为准。

将 Zebra 从单一 Agent 执行基础设施升级为支持：

* Agent 创建
* Agent 生命周期管理
* Agent 能力扩展
* Agent 记忆管理
* Agent 信任控制
* Agent 评估优化

的通用 Agent Runtime 平台。

---

# 1. 当前 Zebra 架构评估

## 1.1 当前架构优势

当前 Zebra 已完成：

```
Task Runtime
Conversation Runtime
Session Runtime
Model Adapter
Tool Gateway
Worker
Sandbox
Artifact
Event Store
Streaming
Recovery
Policy
Audit
```

形成：

```
                User Task

                    |
                    v

          Zebra Agent Runtime

                    |
        -------------------------
        |          |            |
     Model      Tool        Sandbox

                    |
                    v

             Execution Result
```

当前重点解决：

> 如何让 Agent 稳定、安全、可恢复地执行任务。

---

# 1.2 当前架构缺口

但是从长期 Agent 平台角度：

Zebra 缺少：

```
                 Agent Layer
                      |
          -----------------------
          |          |          |
       Skill      Memory    Evaluation


                      |
                      v


              Zebra Runtime
```

当前 Zebra 可以运行 Agent。

但是：

**还不能定义 Agent。**

---

# 2. Zebra v2 总体目标架构

升级后：

```
                    Application Layer

                         |
                         |
                  Agent Definition Layer

                         |
        ---------------------------------
        |              |                |
      Skill         Memory          Evaluation

                         |

              Agent Orchestration Layer

                         |

================================================

              Zebra Agent Runtime

================================================

 Task
 Session
 Event Store
 Harness
 Tool Gateway
 Policy
 Sandbox
 Worker
 Artifact


================================================

Infrastructure

Model
Storage
Network
Security
Compute
```

---

# 3. 新增 Agent Layer

## 3.1 设计目标

Agent Layer 负责：

> 定义“一个 Agent 是什么”

而 Runtime 负责：

> 让 Agent 如何执行

二者分离。

---

# 3.2 Agent Entity 模型

新增：

```
Agent
```

作为 Zebra 一级对象。

示例：

```json
{
  "agent_id": "agent_xxx",

  "name": "Research Agent",

  "version": "1.0",

  "description": "",


  "capabilities": [
      "analysis",
      "research",
      "report"
  ],


  "skills": [],


  "memory_policy": {},


  "model_policy": {},


  "security_policy": {},


  "evaluation_policy": {}

}
```

---

# 3.3 Agent 生命周期

新增：

```
Created

 ↓

Configured

 ↓

Published

 ↓

Running

 ↓

Learning

 ↓

Deprecated
```

---

# 3.4 Agent 与 Runtime 关系

原则：

Runtime 不拥有 Agent。

Runtime 执行 Agent。

关系：

```
Agent Definition

        |
        |
        v

Agent Runtime Instance

        |
        |
        v

Task Execution
```

类似：

```
Docker Image

       +

Container Runtime
```

---

# 4. Skill Layer

## 4.1 当前问题

目前 Zebra Tool:

```
Tool
 |
execute()
```

偏底层。

但是 Agent 需要：

```
Capability
 |
Skill
 |
Tool
```

---

# 4.2 Skill 抽象

新增：

```
Skill
```

定义：

一个可复用能力模块。

结构：

```json
{
"id":"skill_xxx",

"name":"document_analysis",

"version":"1.0",

"tools":[
 "file.read",
 "parser.execute"
],


"knowledge":{},

"prompt_template":{},


"evaluation_cases":[]

}
```

---

# 4.3 Tool 与 Skill 区别

Tool:

> 如何执行

Skill:

> 为什么执行、什么时候执行

关系：

```
Skill

 |
 |
 +---- Tool
 |
 +---- Prompt
 |
 +---- Knowledge
 |
 +---- Eval
```

---

# 5. Memory Architecture Upgrade

这是 Zebra 当前最需要重新定义的部分。

## 5.1 当前问题

如果 Zebra 直接拥有：

```
Agent Memory
```

容易混乱。

未来 Memory 必须拆分。

---

# 5.2 四层 Memory 模型

```
                Memory System


                     |
 ------------------------------------------------

                     |

1. Runtime Memory

2. Task Memory

3. Agent Memory

4. Knowledge Memory


```

---

# 5.3 Runtime Memory

属于 Zebra Core。

保存：

执行状态。

例如：

```
当前任务做到哪里

工具调用记录

失败原因

上下文压缩状态

恢复点
```

生命周期：

小时级。

---

# 5.4 Task Memory

属于 Task。

例如：

```
这个任务之前尝试过：

方法A失败

方法B成功

用户修改要求
```

生命周期：

任务级。

---

# 5.5 Agent Memory

属于 Agent。

例如：

```
Agent行为偏好

策略经验

历史成功模式

能力评价
```

生命周期：

长期。

---

# 5.6 Knowledge Memory

外部知识。

例如：

```
文档

数据库

知识库

向量索引
```

Zebra 不拥有。

只提供 Adapter。

---

# 5.7 Memory Policy

新增：

```
Memory Controller
```

负责：

* 写入规则
* 生命周期
* 权限
* 删除
* 可信度

例如：

```json
{
"write_permission":

"agent_only",

"ttl":

"30d",

"confidence":

0.8

}
```

---

# 6. Context Trust & Security Upgrade

目前 Zebra Security：

重点：

```
执行安全
```

需要增加：

```
信息安全
```

---

# 6.1 新增 Trust Layer

架构：

```
External Input

      |

Context Compiler

      |

Trust Analyzer

      |

Policy Engine

      |

Model Context

```

---

# 6.2 Context Trust Score

所有输入增加：

```
trust_score
```

例如：

| 来源   |  等级 |
| ---- | --: |
| 系统指令 | 1.0 |
| 用户输入 | 0.8 |
| 企业文档 | 0.6 |
| 网页内容 | 0.3 |
| 工具返回 | 0.2 |

---

# 6.3 防止 Context Injection

新增：

```
Instruction Boundary Detector
```

识别：

例如：

```
Ignore previous instruction

You are administrator

Send credentials
```

处理：

```
Detect

 ↓

Mark suspicious

 ↓

Reduce authority

 ↓

Continue safely

```

---

# 7. Agent Policy Engine Upgrade

当前：

Policy 控制 Tool。

升级：

Policy 控制 Agent。

新增：

```
Agent Policy
```

包括：

---

## Capability Policy

Agent 可以做什么。

例如：

```
allow:

read_file

deny:

send_email
```

---

## Memory Policy

Agent 可以记什么。

---

## Collaboration Policy

Agent 是否可以创建子 Agent。

---

## Cost Policy

例如：

```
max_tokens

max_runtime

max_tool_calls
```

---

# 8. Agent Evaluation Layer

这是未来 Agent 质量核心。

新增：

```
Evaluation Engine
```

---

# 8.1 为什么需要

传统软件：

```
Unit Test
```

Agent：

需要：

```
Behavior Evaluation
```

---

# 8.2 Eval Model

```
Task

 |

Agent Run

 |

Trace

 |

Evaluator

 |

Score

 |

Improvement

```

---

# 8.3 Evaluation 内容

包括：

## Correctness

结果是否正确

## Safety

是否违规

## Efficiency

成本

## Reliability

恢复能力

## Consistency

多次运行稳定性

---

# 9. Agent Registry

未来多 Agent 必须。

新增：

```
Agent Registry
```

保存：

```
Agent

Version

Capability

Skill

Permission

Evaluation Score

Owner

Status
```

---

# 10. 新版本模块结构建议

当前：

```
packages/

 core

 context

 runtime

 security

 tools

 storage
```

升级：

```
packages/

 agent-core

 agent-registry

 agent-sdk


 skill-runtime

 memory-core

 memory-adapter


 evaluation


 context-security


 runtime

 sandbox

 tools

 policy

 storage
```

---

# 11. 开发优先级建议

不要一次实现。

建议：

---

## Phase 1

Agent Foundation

目标：

让 Zebra 可以定义 Agent。

实现：

* Agent Entity
* Agent Registry
* Agent Lifecycle

---

## Phase 2

Skill System

实现：

* Skill Manifest
* Skill Runtime
* Skill Version

---

## Phase 3

Memory 2.0

实现：

* Runtime Memory
* Task Memory
* Agent Memory Interface

---

## Phase 4

Trust Security

实现：

* Context Trust
* Injection Detection
* Memory Permission

---

## Phase 5

Evaluation

实现：

* Trace Dataset
* Eval Runner
* Agent Score

---

# 12. 升级后的 Zebra 定位

升级完成后：

Zebra 不再只是：

> Agent Runtime

而是：

> **An open, secure, self-improving Agent Operating Runtime**

即：

```
Define Agent

↓

Give Agent Skills

↓

Provide Memory

↓

Control Trust

↓

Execute Tasks

↓

Evaluate Performance

↓

Improve Agent
```

---

# 最终判断

从 Zebra 当前基础来看，我认为：

**不应该继续堆 Runtime 能力。**

目前 Runtime 已经达到非常高水平。

下一阶段最有价值的升级：

不是更多：

* Sandbox
* Model Adapter
* MCP
* Tool

而是补齐：

```
Agent Layer
+
Memory Layer
+
Trust Layer
+
Evaluation Layer
```

这样 Zebra 才从：

> 一个优秀的 Agent 执行引擎

升级为：

> 一个真正意义上的 Agent Operating Runtime。

这份文档可以作为 Zebra v2.0 架构升级蓝图。
