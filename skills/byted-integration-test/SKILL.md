---
name: byted-integration-test
metadata:
  version: "1.0.1"
description: byted 范围内做 PPE/BOE 泳道联调的通用 playbook — 给 Chrome 注 x-tt-env 头、起本地 dev、打 API 验证后端字段、用 Argos 反查日志定位 FE 还是 BE 问题。**主动触发**：用户说"联调"、"调一下"、"拉个 PPE 跑下"、"走一遍泳道"、"接管浏览器看下"、"测下接口"，或在任何 byted 内部工程上下文里要把请求路由到 PPE/BOE 服务做联调时。编排 byted-lane / chrome-cdp-manager / chrome-devtools / bytedcli / devtools-site-playbook 协作，对每个能力做兜底检测和 fallback。
---

# byted 联调 playbook

byted 范围内做 PPE / BOE 联调的通用流程。从能力检测到出报告一条线。

> 本指南举例使用 `douyin_admin_fe / egrowth / douyin.bytedance.net` 作为典型抖运前端工程的形态；其它 byted 内部项目（author-app、dx-app、tiktok 系列、各种 admin web）整体流程一致，**只有项目主域名、本地 dev 端口、bam.config.json 路径这些**会变。看到 `<your-host>` `<subapp>` `<lane>` 这种占位符替换成你的实际值。

## TL;DR — happy path

```bash
# 0. ⚠️ 联调第一步：检查泳道配置（不要跳过，跳过可能命中错误环境）
byted-lane status                                 # daemon 健康
byted-lane config show                            # 确认 lane.enabled、lane.headers、proxy.mode
#  → proxy.mode 按任务选择：纯 PPE/BOE 后端联调用 direct；本地 dev URLRewrite 用 system；固定上游用 fixed
#  → lane.headers.x-tt-env 应跟当前分支匹配（或主干分支 enabled:false）

# 1. byted-lane 注头 + 选择代理模式
byted-lane lane set ppe_<lane> --env              # 设泳道（x-use-ppe 自动跟）
byted-lane proxy direct                           # 纯 PPE/BOE 后端联调，避免额外代理干扰
# byted-lane proxy system                         # 本地 dev 依赖 OS 代理 URLRewrite 时使用
# byted-lane proxy fixed http://127.0.0.1:8899    # 明确需要固定上游时使用

# 2. 起本地 dev（仅当需要看 UI 改动；纯验后端字段可跳过）
cd <repo>/<subapp> && pnpm dev                    # 端口看项目，常见 7890

# 3. chrome-cdp-manager 确保 Chrome 9222 可连，chrome-devtools 打开 prod URL
#    必须从 https://<your-host>/<subapp>/... 域名进，不能直接打 localhost
#    （Garfish / EdenX 子应用缺主应用 shell + 登录态，localhost 会 404 / 白屏）
#    新请求会立即使用最新配置；若要让页面资源和路由整体重走，再 reload 当前 tab

# 4. evaluate_script fetch API 验字段
# 5. 报错 → bytedcli log get-logid-log 查 Argos
```

## 何时使用

- 用户说"联调"、"拉个 PPE 跑下"、"测下接口"、"走一遍泳道"、"接管浏览器"
- 后端发了新泳道（`ppe_xxx` / `boe_xxx`），FE 要验证字段是否到位、UI 是否对、报错是 FE 问题还是 BE 问题
- 用户给了 logid 让你查 Argos / image / pod
- 修了 FE 代码，要在本地 dev × PPE backend 跑一遍

## 何时**不**使用

- 用户只是写 FE 代码、不接管浏览器
- 当前分支是 `master` / `main` — 多数 byted 项目约定**禁止注 PPE 头**（直连线上）；具体看仓库 AGENTS.md / CONTRIBUTING

---

## Phase 0: 能力检查（每次联调先跑一遍）

按下面顺序检查，缺什么告诉用户什么。能跑到 byted-lane 就走主路径，否则走 fallback。

### byted-lane（主路径，macOS 或已配置的 Linux 服务端 Chrome）

**这一步是联调最关键的第一步，跳过 = 后续全白调。**

```bash
byted-lane status         # daemon 健康
byted-lane config show    # 关键：lane.enabled / lane.headers / proxy.mode
```

期望 `daemon ... up`、`extension connected`、`last apply ... ✓`。

**`config show` 必须 review 的 3 项**：

| 字段 | 期望 | 不符合的症状 |
|---|---|---|
| `lane.enabled` + `lane.headers.x-tt-env` | 跟当前分支期望的泳道一致（如 `ppe_feat_xxx`）；主干分支多数项目要 `enabled:false` | 请求命中错误环境的 pod，BE 字段对不上 |
| `proxy.mode` | 纯 PPE/BOE 后端联调为 `direct`；本地 dev URLRewrite 为 `system`；固定上游为 `fixed` | 模式与任务不匹配会造成 localhost 重写失效、额外代理干扰或页面 404 |
| `proxy.server` | 仅 `fixed` 时存在，且必须是明确的 `<scheme>://<host>:<port>` | 固定代理目标错误或无法连接 |

新版 byted-lane 不维护 `lane.domains`，泳道开启后会给 Chrome 请求注入配置头；不要再执行 `lane domain add`。
若使用 `system`，再用 `scutil --proxy` 或 `networksetup -getautoproxyurl Wi-Fi` 核对 OS 代理；`direct` 不要求系统 PAC 开启。

**典型坑**（eco-fe-infra/bravo-node 真实踩过）：
- byted-lane rev N 时是 `system`，rev N+m 被其它任务切成 `direct` 或 `fixed`，导致本地 URLRewrite 失效或请求走错上游
- UI 看到推荐结果但本地 backend log **完全没 invoker 调用** —— 直接说明 chrome 没走代理，请求直连线上 prod cache。继续怀疑代码就是浪费时间
- **任何“前端有结果但本地 backend log 安静”的情况，第一反应是检查 `proxy.mode` 是否与本次任务匹配，不是改代码**

泳道头和代理配置会通过扩展立即应用到新请求；如果修复的是页面加载、bundle 重写或路由问题，再对已打开的 tab 执行 reload（必要时 `ignoreCache: true`），确保整页请求按新模式重走。

| 失败现象 | 处理 |
|---|---|
| `command not found` | 提示安装；或走 **Fallback A**（chrome-devtools initScript） |
| `cannot reach daemon` | `byted-lane start` |
| `extension not connected` | 让用户去 `chrome://extensions` reload byted-lane 扩展 |
| 本地 dev URLRewrite 不生效且 `proxy.mode=direct` | `byted-lane proxy system`，然后 reload chrome tab |
| 纯 PPE 页面在 `fixed` 下 404/网络异常 | `byted-lane proxy direct`，然后 reload chrome tab |
| `proxy.mode=fixed` 但目标错误 | `byted-lane proxy fixed <scheme>://<host>:<port>` 设置正确上游 |
| Linux 服务端缺少 byted-lane 组件 | 按统一环境配置指南安装 byted-lane，再复查 status |
| 其它环境无法修复 | 走 **Fallback A** |

byted-lane 详细见 `byted-lane` skill。

### chrome-cdp-manager（必须）

调用 `chrome-cdp-manager` skill 拿 Chrome 9222 endpoint。`reused: true | false` 都算 OK。失败说明 Chrome 没装或 9222 被占，让用户处理。

### chrome-devtools MCP（必须）

如果工具没加载，用 `ToolSearch` 拉：

```
ToolSearch(query="chrome-devtools", max_results=30)
```

替代方案：playwright MCP（`mcp__playwright__*`）。多数情况 chrome-devtools 够用。

### bytedcli（诊断阶段需要）

```bash
NPM_CONFIG_REGISTRY=http://bnpm.byted.org npx -y @bytedance-dev/bytedcli@latest --json auth status
```

如果未授权，跑 `bytedcli auth login --begin`，把 SSO URL + usercode 给用户，等他授权完跑 `--complete <token>`。

---

## Phase 1: 注头 + 选择代理模式

### byted-lane 路径

```bash
# 推荐：建立域名限定环境，只给业务 HTML/API host 注头
byted-lane env add ppe_<lane> --on
byted-lane env filter add ppe_<lane> --include <business-host>,<api-host>
byted-lane proxy direct                          # 纯 PPE/BOE 后端联调默认直连
# byted-lane proxy system                        # 本地 dev 依赖 OS 代理 URLRewrite 时使用
# byted-lane proxy fixed http://127.0.0.1:8899   # 明确需要固定上游时使用
byted-lane config show                           # 验证 rev / lane / proxy.mode
```

**关键约定**（byted 通用）：
- 当前分支非主干 → 默认注泳道头
- 主干分支（`master` / `main`） → 多数项目禁止注（直连线上），看仓库 AGENTS.md
- `x-use-ppe` 由 byted-lane 按 `x-tt-env` 前缀自动派生（`ppe_*` → 1，`boe_*` → 移除），**不要手动设**
- BOE 同理：`byted-lane lane set boe_<lane> --env`，`x-use-ppe` 会自动剥掉
- 不要启用无 include 的全局环境。它会把 `x-tt-env` 带到 CDN，触发跨域预检并导致 JS/CSS 白屏
- `env filter add --include` 只控制泳道头范围，不改变代理路由；先从 Network 确认业务 host 和 API host
- `proxy.mode` 为 `direct / system / fixed`，必须结合项目路由实测选择，不能把 `system` 当作所有联调的默认值

### Fallback A: chrome-devtools initScript（仅 byted-lane 不可用）

详见 `references/initscript-fallback.md`。要点：
- **必须 same-origin 过滤**，否则给 CDN 加 header 触发 CORS preflight，bundle 加载失败
- 每次 `navigate_page` 都要重传 `initScript`
- reload 页面失效，用法笨重但兜底用

---

## Phase 2: 本地 dev（按需）

只验后端字段不需要起本地 — 直接打 API 就行。要看 UI 改动才起。

```bash
cd <repo>/<subapp> && pnpm dev   # 端口看项目，常见 7890
```

**关键约束**（byted 微前端 / Garfish / EdenX 通用规律）：
- **必须从主 host 域名访问**（如 `https://<your-host>/<subapp>/...`），**不能直接打 `localhost:<port>`**。子应用缺主应用 shell + 登录态，会 404 / 白屏。
- 多数 byted 前端工程的 dev proxy（eden-proxy / 自定义 proxy）会配 URLRewrite 把 CDN bundle 转到本地端口。此时使用 **`byted-lane proxy system`** 让 Chrome 跟随 OS 代理；如果项目要求固定上游，则使用 `proxy fixed <server>`。纯 PPE 后端联调通常保持 `proxy direct`。
- 注意区分 **proxy 控制台 UI 端口**（如 eden-proxy 控制台 15323） vs **proxy 实际监听端口**（如 15320）vs **dev server 端口**（如 7890）。控制台 UI **不是应用入口**。

端口被占（典型：其他项目 dev server 占了同端口）→ `lsof -i :<port>` 查到进程，跟用户确认后 kill。

---

## Phase 3: 浏览器验证

> **先 consult `devtools-site-playbook`** — 它累积每个站点的页面结构 / URL 参数 / 常踩坑 / API 路径模式。在打开页面前看一下有没有 `<your-host>` 的现成 playbook 可复用；做完联调把本次新发现回写进去，下次别人再做同一站点的工作就有 baseline。byted-integration-test 是流程编排，devtools-site-playbook 是站点知识库，两者叠用。

### 打开页面

```ts
mcp__chrome-devtools__new_page({
  url: "https://<your-host>/<subapp>/<path>?<params>",
})
mcp__chrome-devtools__wait_for({ text: ["关键文案"], timeout: 15000 })
mcp__chrome-devtools__take_snapshot()
```

确认页面状态：
- 顶部 PPE banner 含 `配置泳道<lane>` 等字样 → header 注入到位 ✅
- ⚠️ 抖运系列前端 banner 后半句 **"实际访问服务-prod, 请检查服务" 不可信** — 是 FE 静态提示，请求实际可能命中 PPE pod。**以 Argos 日志为准**，不以 banner 为准（这是真踩过的坑）。其它项目可能有类似 FE 静态判断逻辑，别被它误导。

### 直接打 API 验字段

不要单纯靠 UI 渲染判断 — FE 列表常有客户端字段过滤（如 `filterColumnsByStrategyFields` 之类），列不显示**不一定**是字段没注册。直接 fetch：

```ts
mcp__chrome-devtools__evaluate_script({
  function: `async () => {
    const res = await fetch('/<api-path>', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ /* request body */ }),
    });
    const json = await res.json();
    return { code: json.code, msg: json.msg, logid: res.headers.get('x-tt-logid') };
  }`
})
```

记 logid，下一阶段诊断要用。

### ⚠️ 永远先看 raw 响应形态再写 FE 解析

打通后**完整把第一行原始数据 dump 出来**（`return { firstRaw: json.data?.Results?.[0], firstType: typeof json.data?.Results?.[0] }`），看清楚：

- `Results` 是 **`string[]`**（JSON 字符串）还是 `object[]`？APaaS / collection_query_open_api 等通用 BO 接口经常返回 `string[]` 需要 `JSON.parse`，pro-table-shared 在列表场景会自动 parse，但**抽屉 / 详情 / 自己直接调 BAM 的场景拿到的是 raw**。
- 嵌套字段层级是 `data.Results[0].xxx` 还是 `data.AuthorList[0].xxx`？
- 数字字段是 `number` 还是 `string`（int64 防精度通常返字符串）？
- Condition InValues 元素后端期望 `number` 还是 `string`？传错类型 BO 会 400 + 空 body 不告诉你为什么。

约定 PRD / 文档里写的字段名通常是对的，但 wire 格式（string vs object、嵌套层级）只能从 raw 响应看到。**省这一步会浪费一两轮联调**。

### 错误码速查（APaaS / Apaas Core 常见）

详细在 `references/error-codes.md`，常见的：

| code | msg 关键词 | 含义 | 处理 |
|---|---|---|---|
| `0` | — | 通过 ✅ | — |
| `12000001` | `select field not found in **VO model**` | SelectFields 字段没在 VO 注册 | 走 Phase 4 查 image/pod，给后端 |
| `12000102` | `condition field not found in **BO model**` | Condition 字段没在 BO 注册 | 同上 |
| `101001` | `访问下游异常` | 下游 RPC 失败（BO key 错 / 服务挂 / 临时网络） | 重试 + Argos 查 |
| `14000004` | `exec driver query failed` | DB driver 临时错 | 重试 |

VO = View Object（输出投影 / SelectFields），BO = Business Object（业务对象 / Conditions / 筛选）。错误码语义直接来自 server msg 字面词，APaaS 框架约定。**报告给后端时分清楚 VO 还是 BO**，他可能各自配在不同地方。

### ⚠️ 视觉细节必须截图，a11y snapshot 不靠谱

`mcp__chrome-devtools__take_snapshot` 拿到的是文本结构（a11y 树），**看不到**：

- Tag 实际颜色（绿色 / 灰色 / 红色 — 颜色 fallback 都渲染成同样的"已废弃"文本）
- 列宽是否够 / Tag 是否溢出 cell
- Spin tip 在窄容器里被压成"加 / 载 / 中"竖排
- 抽屉真实宽度（截图里看着占满屏可能是浏览器缩放问题，但也可能真的没生效）
- 间距 / 对齐 / hover 态

**主动截图验证**：每改完一个视觉相关的样式（新增列 / Tag / 弹层 / 加载态 / loading），用 `mcp__chrome-devtools__take_screenshot` 看一眼真实渲染，不要对着 snapshot 文本自我说服"应该没问题"。

如果工具不可用或视觉判断需要专业意见（设计稿对照），让用户截图发回来。

---

## Phase 4: Argos 诊断（API 报错时）

### Step 1 — 找对 PSM

⚠️ **关键陷阱**：BAM 自动生成代码目录名（如 `apps/<subapp>/src/services/<idl-package>/`）是 **IDL 包路径**，**不是 server PSM**。

正确找法（byted 通用）：在仓库根目录或 packages 下找 `bam.config.json`，里面 AppKey 关联了真实 PSM：

```bash
# 在仓库根目录
find . -maxdepth 4 -name "bam.config.json" -not -path "*/node_modules/*"
grep -A2 "AppKey 名" packages/utils/bam.config.json | grep psm
# 例：AppKey "douyin_admin_platfrom"（注意 typo）→ psm: douyin.admin.platform
```

如果项目没用 BAM，去找 `package.json` 里和 backend 调用相关的 `psm` 字段、或源码里 `RPC` 调用配置。常见 PSM 见 `references/psm-lookup.md`。

### Step 2 — 查日志

```bash
bytedcli log get-logid-log "<logid>" \
  --psm "<psm>" \
  --vregion "China-North" \
  --output file --output-file /tmp/logid.log
```

**vregion 要选对** — `cn` 区域用 `China-North`；i18n 走 `Singapore-SaaS` / `Singapore-Central`；TTP 走 `US-TTP` / `US-TTP2`；详见 `references/argos-tips.md` 和 `bytedcli` skill 的 log GUIDE。

提取关键字段：

```bash
grep -oE "_image_version=[^ ]+|_pod_name=[^ ]+|_env=[^ ]+|_tce_physical_cluster=[^ ]+|condition field not found.{0,150}|select field not found.{0,150}|bizKey: [^ ,\"]+" /tmp/logid.log | sort -u
```

判断：
- `_env=ppe_<lane> _env_type=ppe` → 请求**确实命中 PPE 泳道**
- `_image_version=...` → 后端实际跑的镜像 hash，给后端去查这个 image 是否包含他改的 BO 配置
- `_pod_name=dp-...` → pod 名
- `bizKey: <name>` → BO 校验时用的 key（可能与 ViewScene 不同名，spec 里写的 BO key 才是真名）

### Step 3 — 没数据怎么办

```
Logid trace fetched.
LogID: xxx
```

只有这两行 = 日志没同步。Argos 同步延迟 30s~3min：

```bash
until <get-logid-log cmd> && [ "$(wc -l < /tmp/logid.log)" -gt 5 ]; do sleep 20; done
```

一直没数据 → PSM 错了，用 `search-psm-log` 大窗口扫确认 PSM 活动：

```bash
bytedcli log search-psm-log --psm "<psm>" --vregion "China-North" \
  --start "<-30min>" --end "<now>" --max-logs 50 --limit 50 --output file ...
```

连 PSM 大窗口都查不到 → PSM 真错，回 `bam.config.json` 重查。

详细 Argos 排错见 `references/argos-tips.md`。

### Step 4 — 区分 FE / BE 问题

读 Argos 日志：
- 报错指向**请求参数格式 / 字段类型 / 前端转换 / 请求头** → FE 修
- 报错指向**后端 / 上下游 / scene-handler / BO/VO 配置 / DB / 下游 RPC** → 整理给后端，**不闷头解决**

报告模板：

> 联调泳道 `<lane>`，PSM `<psm>`：
> - 字段 `<field>` 报 `<errcode> <errmsg>`
> - logid: `<logid>`，pod `<pod>`，image `<image_version>`
> - bizKey: `<bizKey>`（从 Argos `... bizKey: <name>` 找到）

---

## skill 协作图

```
联调请求
  │
  ├─▶ chrome-cdp-manager   确保 Chrome 9222 可连
  │
  ├─▶ byted-lane           注入 x-tt-env 头 + direct/system/fixed 代理模式
  │     │
  │     └─ 不可用 ─▶  chrome-devtools initScript fallback (Fallback A)
  │
  ├─▶ devtools-site-playbook  浏览页面前 consult 站点 playbook（复用 + 回写）
  │
  ├─▶ chrome-devtools MCP  打开 prod URL，evaluate_script 直接打 API
  │
  ├─▶ bytedcli log         (报错时) get-logid-log 查 Argos
  │
  └─▶ lark-doc             (要写对齐文档时) 创建对齐文档 @ 后端
```

---

## 常见 gotcha

0. **联调第一步永远是 `byted-lane status` + `byted-lane config show`，不是改代码** — 重点核对 `lane.enabled`、`lane.headers.x-tt-env` 和 `proxy.mode`。本地 dev URLRewrite 通常需要 `system`，纯 PPE/BOE 后端联调通常使用 `direct`，明确固定上游时才用 `fixed`。模式错误可能表现为本地 backend 无调用、额外代理干扰或页面 404。
1. **PPE banner 后半句"实际访问服务-prod"不可信** — 是 FE 静态提示，请求实际可能命中 PPE。Argos `_env=ppe_xxx` 才是真相。
2. **IDL 包名 ≠ server PSM** — IDL 在 `apps/<subapp>/src/services/<idl>/`，server PSM 在 `bam.config.json`。
3. **注意 CDN 的跨域预检** — 默认使用带 include 的 Environment Profile，只让业务 HTML/API host 命中；用一个业务请求和一个 CDN 请求做正反验证。InitScript 无法覆盖首次 HTML 导航，CDP Fetch 拦截处理不完整又会让资源 pending，都不是常规主路径。
4. **服务端 Chrome 的 LNA** — Chrome 151/152 可能把解析到内网地址的 CDN 判为 local network。必须通过 `chrome-cdp-manager` 复用同一个 headed Chrome，并确认真实主进程的 `launch_readiness.matched=true`；只在配置里写 flag、或连到另一 Chrome 实例都不算通过。
5. **localhost 直接打不通** — 必须从主 host 域名进，本地 proxy 才能重写 CDN bundle 到 localhost。
6. **Argos 30s~3min 延迟** — 第一次没数据 ≠ 没日志，要 poll。
7. **客户端字段过滤会隐藏 column** — UI 没列 ≠ FE 没写，可能是后端 `get_strategy_fields` / `get_columns` 没返回该 columnId。直接打 API 验。
8. **byted-lane daemon 重启后扩展可能 WS 断** — `byted-lane status` 看 `extension connected` 状态。
9. **多次 dev 之间端口冲突** — 常见端口（7890 等）容易被其他项目占。
10. **VO ≠ BO** — `12000001 VO model` 是 SelectFields 校验失败，`12000102 BO model` 是 Conditions 校验失败。给后端报告时分清楚。
11. **后端说"已发"但实测仍报缺字段** — 是常态，可能 image 没含 BO 配置 / TCC 没推 / 注册到了别的 bizKey。给他 logid + image_version 让他在 argos 自己查，不要跟他争。
12. **vregion 选错查不到日志** — i18n / TTP / EU 各有自己的 vregion，cn 默认 `China-North`。
13. **APaaS Results 是 `string[]` 不是 `object[]`** — 列表场景由 pro-table-shared 自动 parse，抽屉 / 详情自己调 BAM 拿到的是 raw 字符串，要 `JSON.parse(Results[0])` 才能拿对象。这条让我们多花了一轮联调才发现。
14. **BO Conditions InValues 类型敏感** — `[8]`（number）会 400 空 body 不报因，`["8"]`（string）通过。前端筛选项 value 直接落字符串源头，避免序列化链路里被恢复。
14. **a11y snapshot 看不见颜色 / 列宽 / 文字溢出** — 视觉相关验证必须截图，`take_screenshot` 或问用户要图，不要靠 snapshot 文本自我说服。
15. **联调里改 FE 代码先看现有组件库** — Semi UI / Arco / 业务自有组件（pro-table、TableCol 等）大多已经支持 ellipsis / tooltip / Tag 配色 / 表头底色 / size 紧凑等。手撸 grid 排版当时看着简单，调 4 个细节（列宽、表头底色、ellipsis、tag 溢出）下来比直接用 `<Table>` 慢。**写任何 list / table / drawer / spin / empty 之前先翻一下组件库**。

---

## 参考

- `references/psm-lookup.md` — 找后端 PSM 的方法 + byted 常见 PSM 列表
- `references/error-codes.md` — APaaS 错误码完整列表 + 诊断决策树
- `references/initscript-fallback.md` — chrome-devtools initScript fallback 完整模板（byted-lane 不可用时）
- `references/argos-tips.md` — Argos 同步延迟、PSM 寻址、`bam.config.json` 反查、search-psm-log 调参、vregion 选择
