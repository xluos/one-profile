# APaaS 错误码诊断决策树

错误码来自 server response body 的 `code` + `msg`。byted 多个业务底层用 APaaS / Apaas Core 框架，错误码语义在多业务通用。

## 决策树

```
拿到 error code
    │
    ├── 0  →  通过 ✅
    │
    ├── 12000xxx  →  字段校验失败（消息会指明 VO / BO）
    │      ├── 12000001 :select field not found in **VO model**  →  SelectFields 缺
    │      └── 12000102 :condition field not found in **BO model**  →  Conditions 缺
    │           处理：走 Argos 查 image / pod，给后端
    │
    ├── 14000xxx  →  数据/驱动错（多半临时）
    │      └── 14000004 :exec driver query failed  →  DB driver 错，重试
    │
    ├── 101001 访问下游异常  →  下游 RPC 失败
    │      ├── BO key 错（ViewScene 写错） →  spec / FE 代码核对 ViewScene
    │      ├── 下游服务挂  →  Argos 看下游 PSM 健康
    │      └── 临时网络  →  重试
    │
    └── 其它  →  Argos 看具体报错
```

## VO vs BO 速查

| 概念 | 框架名 | 在请求里的位置 | 校验失败错误码 |
|---|---|---|---|
| VO（View Object） | 输出投影模型 | `SelectFields: [...]` | `12000001 :select field not found in VO model` |
| BO（Business Object） | 业务对象模型 | `Conditions: [{ Field, Operator, ... }]` | `12000102 :condition field not found in BO model` |

VO 决定能选什么字段返回；BO 决定能用什么字段过滤。两者**注册路径不一样**，后端可能各自配在不同地方（TCC、代码、配置中心）。

报告给后端时**分清楚是 VO 还是 BO**：
- 「`training_group_id` SelectField 报 `12000001 VO model`」→ 检查 VO 注册
- 「`group_status` Condition 报 `12000102 BO model`」→ 检查 BO 注册

## bizKey

Argos 日志里看到 `... bizKey: <name>` 是 BO 校验时用的真实 key。**注意它可能和 ViewScene 不同名**：
- 例：FE 发 ViewScene `scale_ops_author_list_new` → server 内部映射到 bizKey `scale_ops_author_list`（无 `_new` 后缀）
- 后端写 BO 配置时按 bizKey 注册，不按 ViewScene

排错时，**bizKey 才是后端 BO 配置的索引**。spec 里写「BO key: xxx」一般指 bizKey。

## 完整错误码（节选，遇到再补）

| code | 含义 |
|---|---|
| `0` | 成功 |
| `12000001` | SelectField 不在 VO model |
| `12000002` | SelectField 类型不匹配 |
| `12000101` | Condition 操作符不支持 |
| `12000102` | Condition Field 不在 BO model |
| `12000103` | Condition 值类型错 |
| `14000001` | 通用 DB 错 |
| `14000004` | DB driver query 失败 |
| `101001` | 下游 RPC 异常 |
| `101002` | 下游 RPC timeout |
| `403xxx` | 权限校验失败 |

如果遇到没见过的错误码，直接拿 logid 让后端看，大多数业务的错误码在他们那边有内部文档。
