---
name: byted-lane
metadata:
  version: "0.2.3"
description: byted-lane CLI + Chrome 扩展的使用指南。控制泳道头（x-tt-env / x-use-ppe）和 Chrome 代理模式（direct / system / fixed 三态），支持 macOS 和 Linux 服务端的受管 Chrome。当用户说"设置泳道"、"切到 ppe/boe 环境"、"走系统代理"、"代理走 127.0.0.1:8899"，或者要排查"为什么我的请求没带泳道头"、"插件没连上"、"daemon 跑没跑起来"时使用。
---

# byted-lane

byted-lane 是一个本地 daemon + Chrome MV3 扩展 + CLI 的小工具，专门做两件事：

1. **泳道头注入**：按 Environment Profile 的 include/exclude 范围注入 `x-tt-env`（以及自动派生的 `x-use-ppe`）
2. **Chrome 代理模式开关**：三态切换 — `direct`（强制直连）/ `system`（跟 OS 代理走）/ `fixed`（指向具体的 `<scheme>://<host>:<port>`）

替代 ModHeader + SwitchyOmega，但配置通过本地 HTTP/WS 桥暴露出来，方便 agent 控制。

**项目位置**：`/Users/bytedance/Documents/AIWorkspace/byted-lane`

## 用户的实际工作流

用户是 ByteDance 抖运前端。典型一次联调：

1. 跑开发服务器 → 它自动启动调试代理并把自己注册成 macOS 系统代理（带智能 URL 拦截规则）
2. 让 Chrome 把所有流量交给 OS 代理 → `byted-lane proxy system`
3. 或者绕开 OS、直接指 → `byted-lane proxy fixed http://127.0.0.1:8899`
4. 后端泳道路由需要请求头 → `byted-lane lane set ppe_xxx --env`
5. 完事，daemon 通过 WS 推送配置给扩展，扩展立即生效（无需 reload 页面）

按 URL 分流（哪些走代理、哪些直连）依然是 OS 代理工具 / `fixed` 模式上游 PAC 的事。Environment Profile 的 include/exclude 只控制泳道头注入范围，不改变代理路由。

## 任何操作前先做的事：健康检查

```bash
byted-lane status
```

期望输出：

```
daemon       v0.1.0  pid 12345  up 60s
config       /Users/bytedance/.byted-lane/config.json  rev 3
extension    connected  v0.1.0  proto 0.1.0
last apply   rev 3 ✓
```

每行的含义：
- `daemon ... up Xs` — daemon 在跑，能接命令
- `config ... rev N` — 当前配置版本号，每次变更 +1
- `extension connected` — Chrome 扩展 WS 连上 daemon 了
- `last apply ... ✓` — 扩展成功 apply 了最新配置

### 如果 `byted-lane: command not found`

CLI 没装到全局。装一下：
```bash
chmod +x /Users/bytedance/Documents/AIWorkspace/byted-lane/cli/index.ts
ln -sfn /Users/bytedance/Documents/AIWorkspace/byted-lane/cli/index.ts ~/.bun/bin/byted-lane
```

验证：`which byted-lane` 应该输出路径。

### 如果 "cannot reach daemon at http://127.0.0.1:38999"

Daemon 没跑。启动：
```bash
byted-lane start
```

启动失败查日志：
```bash
byted-lane logs
```

### 如果 `extension not connected`

可能是扩展没加载、被禁用、或 service worker 挂了。

1. 打开 `chrome://extensions`
2. 确认 byted-lane 在列表里且开关打开
3. 点卡片右下角 🔄 reload
4. 重跑 `byted-lane status` —— 应该是 connected

如果还不连：在 `chrome://extensions` 里点 byted-lane 的 "service worker" 链接打开扩展 DevTools 看报错。最常见的是 daemon 重启过、扩展 WS 断了；reload 扩展拿一个新连接就行。

或者可视化看一眼：点 Chrome 工具栏的 byted-lane 图标，popup 里 `daemon` 应该显示 "connected"。

## 设置泳道

优先使用带 `include` 的 Environment Profile，只给业务入口/API 域名加头。不要默认开启无 include
条件的全局环境：全局 `x-tt-env` 会污染跨域 CDN 请求，触发 CORS preflight，造成 JS/CSS 加载失败。

```bash
# PPE 泳道（x-use-ppe: 1 自动加上）
byted-lane lane set ppe_<lane-name> --env

# BOE 泳道（自动把 x-use-ppe 摘掉，避免污染请求）
byted-lane lane set boe_<lane-name> --env

# 关闭泳道但保留配置
byted-lane lane off
byted-lane lane on

# 全清
byted-lane lane clear

# 任意自定义头
byted-lane lane set some-value --header x-custom-header
```

执行完命令后，**新请求立即生效，不需要 reload 扩展或刷新页面**。daemon 通过 WebSocket 推到扩展，扩展用 `chrome.declarativeNetRequest.updateDynamicRules` 改规则。

## 管理多个环境

扩展侧栏和 CLI 共用 `config.json.environments`，不是两份状态：

```bash
byted-lane env list
byted-lane env add ppe_creator_center --on
byted-lane env remove ppe_creator_center
byted-lane env on ppe_creator_center
byted-lane env off ppe_creator_center
byted-lane env rename ppe_creator_center ppe_creator_home

byted-lane env filter add ppe_creator_home --include creator.douyin.com,api.example.com
byted-lane env filter remove ppe_creator_home --include api.example.com
byted-lane env filter add ppe_creator_home --exclude static.creator.douyin.com
```

服务端或不熟悉站点域名时，先从 DevTools Network 里确认 HTML/API 的真实 host，再加入 include；CDN、
ImageX、监控和第三方域名保持不匹配。配置后用目标业务请求和一个 CDN 请求分别核验：前者应带泳道头，
后者不应带。不要回退到 CDP Fetch 拦截，拦截处理不完整会让资源长期 pending。

无启用 include 条件的环境是全局环境，同时最多启用一个；有 include 条件的环境是域名限定环境，可以同时启用多个。旧 `lane set/on/off/route` 命令仍兼容，并会反向同步到环境列表。

### x-use-ppe 自动派生规则

| `x-tt-env` 值 | `x-use-ppe` 处理 |
| --- | --- |
| `ppe_*` | 自动设为 `1` |
| `boe_*` | 自动移除 |
| 其它 | 不动（要的话用 `--ppe` 或 `--header` 显式设） |

所以日常**只需要切 `--env` 这一个值**，`x-use-ppe` 会跟着走。

### 验证头有没有发出去

Chrome DevTools → Network → 选择一个命中 include 的业务请求，其 Request Headers 应能看到 `x-tt-env` 和 `x-use-ppe`；再选择一个 CDN 请求，确认不带这两个头。

或者直接访问 https://httpbin.org/headers，response body 会回显你设置的头。

## Chrome 代理模式（三态）

```bash
byted-lane proxy direct                  # 强制直连，绕开任何 OS 代理
byted-lane proxy system                  # Chrome 走 OS 系统代理（chrome.proxy mode:'system'）
byted-lane proxy fixed http://127.0.0.1:8899   # Chrome 全量走指定上游

# 兼容历史用法（不要鼓励新用户使用）：
#   byted-lane proxy on   == proxy system
#   byted-lane proxy off  == proxy direct
```

**模式语义**：

| mode     | 行为                                               | 何时用                                          |
| -------- | -------------------------------------------------- | ----------------------------------------------- |
| `direct` | Chrome 显式 `mode:'direct'`，连 OS 代理都不走     | 想确认页面"裸"直连了                            |
| `system` | Chrome `mode:'system'`，跟 OS 走                  | 大多数日常联调（OS 代理工具已经在管 URL 分流）  |
| `fixed`  | Chrome `mode:'fixed_servers'`，所有流量打到 server | OS 那边没装代理工具、想直接指调试代理 host:port |

`fixed` 模式只接受 `<scheme>://<host>:<port>`（scheme 限 `http` / `https` / `socks4` / `socks5`，不写 scheme daemon 会自动补 `http://`）。**没有按 URL 分流的选项** —— 要分流就在 OS 代理工具或 `fixed` 上游的 PAC 里做。

### 验证当前模式

```bash
byted-lane config show
# direct:   "proxy": { "mode": "direct" }
# system:   "proxy": { "mode": "system" }
# fixed:    "proxy": { "mode": "fixed", "server": "http://127.0.0.1:8899" }
```

如果用户报"代理没生效"：先看 popup 工具栏图标颜色 —— 灰=direct、蓝=system、绿=fixed，颜色对了说明 byted-lane 已经把 Chrome 切过去了。剩下的问题大概率在 OS 代理工具或上游 fixed server 那边。验证 macOS 代理状态用 `scutil --proxy`。

## Daemon 生命周期

```bash
byted-lane start              # 后台启动，幂等（已经在跑就跳过）
byted-lane stop               # 停止（如果挂了 launchd 就 unload）
byted-lane restart
byted-lane logs               # 看最近 200 行
byted-lane logs -f            # tail -f
```

日志固定在 `~/.byted-lane/daemon.log`（前台 `bun run daemon`、`byted-lane start`、launchd 三种启动方式都写这个文件）。

### Linux 服务端

按照统一环境配置指南安装 Linux 组件，安装结果应包含：

- `~/.local/bin/bun` 与 `~/.local/bin/byted-lane`
- 用户级 `byted-lane.service`
- 受管 Chrome 的 checksum 固定 Linux external CRX
- 本 Skill 和 `byted-integration-test` Skill

服务端优先让 systemd 管理 daemon：

```bash
systemctl --user status byted-lane --no-pager
systemctl --user restart byted-lane
journalctl --user -u byted-lane -n 100 --no-pager
byted-lane status
```

初始配置是 lane 关闭、无环境、Chrome 直连。只有拿到具体泳道和目标业务 host 后才创建
带 include 的环境。Chrome 复用/重启由 `chrome-cdp-manager` 负责；不要另起 headless Chrome，也不要
手工用 InitScript 或 CDP request interception 代替首次导航的扩展注头。

## 开机自启（macOS only）

```bash
byted-lane autostart install      # 装 ~/Library/LaunchAgents/com.byted-lane.daemon.plist
byted-lane autostart status       # 安装/加载/运行状态
byted-lane autostart uninstall    # 完全卸载
```

装了自启后，`byted-lane stop` 会调 `launchctl unload`（因为 `KeepAlive: true` 会让普通 SIGTERM 立刻被 launchd 拉回来）。再启动用 `byted-lane start`（自动 reload launchd）。

## 直接编辑配置文件（agent 友好的批量修改）

如果你（agent）需要原子地改多个字段，可以直接写 JSON 文件 —— daemon 的目录 watcher 会在 ~100ms 内捕获并广播：

```bash
# 配置位置
~/.byted-lane/config.json
```

完整 schema（多余字段会被静默忽略）：

```json
{
  "lane": {
    "enabled": true,
    "headers": { "x-tt-env": "ppe_xxx" }
  },
  "environments": [
    {
      "id": "default",
      "env": "ppe_xxx",
      "enabled": true,
      "headers": {},
      "includeFilters": [],
      "excludeFilters": [],
      "source": "manual",
      "createdAt": 0,
      "updatedAt": 0
    }
  ],
  "proxy": { "mode": "fixed", "server": "http://127.0.0.1:8899" }
}
```

`proxy.mode` 取 `direct` / `system` / `fixed`；`fixed` 时必须带 `server`。旧文件用 `"proxy": { "enabled": true|false }` 也能读（daemon 会按 true→system / false→direct 归一），但写入新配置请直接用 `mode`。

`environments` 是权威数据，`lane` 是 daemon 编译出的兼容结构；直接编辑两者时以 `environments` 为准。`x-use-ppe` 不需要手动写，daemon 会按 `x-tt-env` 自动派生。

文件改完不用通知任何人，watcher + WS 自动同步到扩展。

## 状态文件位置一览

| 路径 | 是什么 |
| --- | --- |
| `~/.byted-lane/config.json` | 当前配置（唯一来源） |
| `~/.byted-lane/daemon.log` | daemon stdout + stderr（含扩展通过 WS 转发的 console 日志） |
| `~/.byted-lane/daemon.pid` | `byted-lane start` 启动时记的 pid |
| `~/.byted-lane/state.json` | 自启提示节流时间戳 |
| `~/Library/LaunchAgents/com.byted-lane.daemon.plist` | macOS 自启定义 |

## 项目结构（debug 时可能要看）

```
shared/protocol.ts          类型 + WS 消息 + 端口常量（daemon/extension/CLI 共享）
daemon/index.ts             Bun HTTP+WS 桥，端口 38999
daemon/config-store.ts      配置存储 + 目录 watcher + 校验/归一化（含 ppe/boe 规则）
cli/index.ts                CLI 入口
cli/daemon-ctrl.ts          start/stop/restart/logs 实现
cli/autostart.ts            macOS launchd 操作
extension/manifest.json     MV3 manifest
extension/src/background.ts service worker：WS 客户端 + DNR + chrome.proxy
extension/dist/             build 产物（Chrome 加载这里）
test/e2e.ts                 端到端测试
```

改完代码：
- daemon/cli 改了：`byted-lane restart`（脚本是直接读 .ts 跑，不用编译）
- extension 改了：`bun run build:ext`，然后 chrome://extensions 里 reload 扩展
