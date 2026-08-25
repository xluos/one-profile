# PSM 查找方法 + 抖运常见 PSM

## 为什么要单独讲 PSM

Argos 日志按 PSM 索引，PSM 错了就什么都查不到。**最常踩的坑**：拿 IDL 包路径当 PSM。

| 这个 ❌ | 不是 PSM | 这个 ✅ | 才是 PSM |
|---|---|---|---|
| `apps/egrowth/src/services/ies.uex.scale_operation_platform/` | IDL 包路径（thrift 命名空间） | `douyin.admin.platform` | server 真实 PSM |

byted 服务部署用 PSM 作为唯一标识，IDL 名只是接口定义的包路径。两者**经常不同名**。

## 三种找法

### 法 1（首选）：bam.config.json

byted 大多数前端工程用 BAM 自动生成 client 代码，配置里写了 AppKey ↔ PSM 映射：

```bash
find . -maxdepth 4 -name "bam.config.json" -not -path "*/node_modules/*"
```

打开看里面：

```json
{
  "services": [
    {
      "name": "douyinAdminPlatform",
      "appKey": "douyin_admin_platfrom",
      "psm": "douyin.admin.platform",
      "version": "1.0.1455"
    }
  ]
}
```

请求 body 里 `AppKey: 'douyin_admin_platfrom'` → 对应 `psm: douyin.admin.platform`。

### 法 2：搜源码 RPC 调用

如果项目没用 BAM（直接调 RPC）：

```bash
grep -rn "psm:\|PSM:\|@psm" --include="*.ts" --include="*.tsx" --include="*.go" .
```

找到调用处，看 PSM 字符串。

### 法 3：从错误消息反推下游 PSM

server 报错有时带下游 PSM 字面提示，例如：

```
E_RPC_WEBCAST_PLATFORM_APAAS_CORE_NETWORK:访问下游异常
```

`WEBCAST_PLATFORM_APAAS_CORE` → 下游 PSM 大概率是 `webcast.platform.apaas_core`。这种是诊断时副线索，不是主路径。

---

## 抖运 / 通用常见 PSM 速查

| 业务 | AppKey | PSM | 用途 |
|---|---|---|---|
| 抖运 admin platform（前端 BAM） | `douyin_admin_platfrom` (typo 真实) | `douyin.admin.platform` | 抖运后端主服务，处理 ScaleOps 系列接口 |
| 抖运创作者维护 | — | `douyin.creator_maintain.rpc` | 抖音 IM 群信息查询等 |
| 抖运 ScaleOps IDL 包名 | — | `ies.uex.scale_operation_platform` | ⚠️ 这是 **IDL 包名**，不是 server PSM |
| 抖运 creator elevate | — | `douyin.creator.elevate` | 培优相关 |
| Apaas Core（BO/VO 校验下游） | — | `webcast.platform.apaas_core` | 多个抖运服务的下游，VO/BO 校验在这里 |

实际数据来自 `packages/utils/bam.config.json`（douyin_admin_fe 仓库）。其它仓库各自有自己的 bam.config.json。

---

## 快速 fingerprint：URL → PSM

`/ops/api/...` 路径下的请求 → 多半是 `douyin.admin.platform`（抖运 ops 网关）。

但**不要硬猜**，读 bam.config.json 才稳。
