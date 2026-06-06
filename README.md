# Chrome CDP Manager Skill Repo

这个仓库当前只包含一个 skill：

- `chrome-cdp-manager`

它的目标不是做一个“通用浏览器路由器”，而是稳定地管理一个可复用的 Chrome CDP 实例，让后续的 Agent/自动化流程能够：

- 复用同一个 Chrome 实例
- 复用同一个自定义 profile 目录
- 保留登录状态、Cookie 和本地浏览器数据
- 在端口失效或状态脏掉时自动恢复

## Skill 位置

```text
skills/chrome-cdp-manager/
```

## 适合的场景

- 你不想每次都启动一个全新的无状态浏览器
- 你需要先手动登录，再让后续 Agent 复用这个浏览器状态
- 你希望 Agent 通过 Chrome DevTools Protocol 连接到同一个浏览器实例
- 你希望把 profile 和端口状态放到固定目录统一管理

## 默认状态目录

默认使用：

```text
~/.agents-profile/main/
```

其中包含：

```text
~/.agents-profile/main/
├── chrome-profile/      # Chrome 用户数据目录
├── .cdp-port            # 当前有效端口
├── session.json         # 当前会话元信息
├── chrome-launch.log    # 启动日志
└── .launch.lock/        # 并发启动锁
```

## 手动登录初始化

如果你只是想先单独拉起浏览器，自己完成登录、授权、二次验证之类的操作，再把状态留给后续 Agent 复用，当前逻辑已经够用，不需要额外功能。

更短的入口是：

```bash
cdp-chrome
```

也可以顺手打开一个页面：

```bash
cdp-chrome http://localhost:8080
```

这个命令会复用同一个 profile 和固定 CDP 端口：

- profile: `~/.agents-profile/main/chrome-profile`
- CDP: `http://127.0.0.1:9222`

直接运行：

```bash
skills/chrome-cdp-manager/scripts/ensure_chrome_cdp.sh
```

或者显式指定状态目录：

```bash
CHROME_CDP_STATE_DIR="$HOME/.agents-profile/main" \
skills/chrome-cdp-manager/scripts/ensure_chrome_cdp.sh
```

执行后会发生这些事：

1. 如果状态目录和 `chrome-profile/` 不存在，会自动创建
2. 如果没有可复用的 CDP 实例，会启动一个新的 Chrome
3. Chrome 会把登录状态和本地数据写到 `chrome-profile/`
4. 脚本会把端口和会话信息写到 `.cdp-port` 与 `session.json`

你这时可以直接在弹出的 Chrome 窗口里完成登录。之后再次运行同一个脚本，或让 Agent 复用这个目录时，就会优先 attach 到已有实例，或者在浏览器关闭后用同一个 profile 重启。

注意：

- 不要把它改成你日常默认 Chrome 的 profile
- 如果浏览器异常退出，脚本会尝试清理 `SingletonLock` 等残留锁文件
- 启动失败时优先查看 `chrome-launch.log`

## 脚本输出

`ensure_chrome_cdp.sh` 会输出一段 JSON，调用方可以直接消费：

```json
{
  "port": 9222,
  "ws_url": "ws://127.0.0.1:9222/devtools/browser/...",
  "profile_dir": "/Users/you/.agents-profile/main/chrome-profile",
  "reused": true,
  "chrome_path": "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  "pid": 12345
}
```

## 恢复策略

当前实现已经覆盖这些恢复路径：

- `.cdp-port` 存在，但端口不可用
- `session.json` 残留，但对应 Chrome 已经退出
- `chrome-profile/` 下残留 `SingletonLock`、`SingletonCookie`、`SingletonSocket`
- 两个调用同时尝试拉起 Chrome 时，用 `.launch.lock` 做粗粒度互斥

## 用 `npx skills` 安装

这个仓库已经按标准 skill 仓库结构组织，不需要单独的安装脚本。

先查看仓库里有哪些 skill：

```bash
npx skills add xluos/one-profile --list
```

把 `chrome-cdp-manager` 安装到全局 skill 目录，并声明给 Codex 使用：

```bash
npx skills add xluos/one-profile --skill chrome-cdp-manager -a codex -g -y
```

如果你想把这个仓库里的所有 skill 一次性装进去，可以用：

```bash
npx skills add xluos/one-profile --all -g -y
```

安装完成后，重启你的 Agent / Codex 进程，让新的 skill 元数据被重新加载。

## 本地验证

当前仓库已经做过这些验证：

- shell 脚本语法检查
- 空 profile 目录首次启动
- 第二次调用复用已有实例
- 伪造失效 `session.json` 和残留锁文件后的恢复
