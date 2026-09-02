# Fallback A: chrome-devtools initScript 注头

仅当 byted-lane 不可用时才用这个。byted-lane 在每个 byted Mac 开发机上理论上都装得上，遇到问题先想办法修它。

## 完整模板

```ts
mcp__chrome-devtools__navigate_page({
  type: "url",
  url: "https://<your-host>/<subapp>/<path>",
  initScript: `(() => {
    const PPE_ENV = '<lane>';        // 例：ppe_7246098749
    const TARGET_HOST = '<your-host>'; // 例：douyin.bytedance.net
    const HEADERS = {
      'x-tt-env': PPE_ENV,
      'x-use-ppe': '1',  // ppe_* 才设；boe_* 应去掉
    };

    const shouldInject = (urlInput) => {
      try {
        const raw = typeof urlInput === 'string'
          ? urlInput
          : urlInput && (urlInput.url || urlInput.href);
        if (!raw) return false;
        const u = new URL(raw, location.href);
        return u.host === TARGET_HOST;
      } catch (_) {
        return false;
      }
    };

    // patch fetch
    const origFetch = window.fetch;
    window.fetch = function (input, init) {
      const url = typeof input === 'string' ? input : input && input.url;
      if (!shouldInject(url)) return origFetch(input, init);
      const next = init || {};
      const headers = new Headers(
        next.headers || (input instanceof Request ? input.headers : undefined)
      );
      headers.set('x-tt-env', HEADERS['x-tt-env']);
      headers.set('x-use-ppe', HEADERS['x-use-ppe']);
      return origFetch(input, { ...next, headers });
    };

    // patch XHR
    const origOpen = XMLHttpRequest.prototype.open;
    const origSend = XMLHttpRequest.prototype.send;
    XMLHttpRequest.prototype.open = function (method, url, ...rest) {
      this.__ppeUrl = url;
      return origOpen.call(this, method, url, ...rest);
    };
    XMLHttpRequest.prototype.send = function (...args) {
      if (shouldInject(this.__ppeUrl)) {
        try {
          this.setRequestHeader('x-tt-env', HEADERS['x-tt-env']);
          this.setRequestHeader('x-use-ppe', HEADERS['x-use-ppe']);
        } catch (_) {}
      }
      return origSend.apply(this, args);
    };

    console.log('[PPE] same-origin only header injected', TARGET_HOST, HEADERS);
  })();`
})
```

## ⚠️ 三个**必须**

1. **必须 same-origin 过滤**（`u.host === TARGET_HOST`）。如果 inject 给所有 url，CDN 资源（`*.bytegoofy.com` / `cdn-tos-cn.bytedance.net`）的 preflight 会被拒（CORS `x-tt-env not allowed`），结果 egrowth bundle 这种动态加载脚本会 `net::ERR_FAILED`，整个页面白屏。这是真踩过的坑。
2. **必须每次 navigate 都重传 `initScript`** — chrome-devtools 的 initScript 只对该次 navigation 后的 document 生效，刷新页面 / SPA 路由跳转后失效。
3. **BOE 不要设 x-use-ppe** — `boe_*` 泳道走 BOE 路由，加 x-use-ppe 反而错。BOE 把上面 `'x-use-ppe': '1'` 那行去掉。

## 缺点

- 每次 `navigate_page` 都要重写 30+ 行 JS
- 改泳道号要重新 navigate（不能热更）
- 用户在浏览器里手动 reload 后头就丢了
- 每次都要小心 same-origin 过滤

byted-lane 的 declarativeNetRequest 支持 **Environment Profile 域名过滤 + 实时热更 + 首次导航注头**，所以能用 byted-lane 就别走这个 fallback。

## 何时不得不用 fallback

- 环境尚未配置 byted-lane（Windows 或未完成环境配置的 Linux）
- byted-lane daemon 反复起不来 / 扩展反复 disconnect 修不好
- 临时 sanity check（不想创建 byted-lane Environment Profile）

最后一种情况下也可以考虑：先 `byted-lane lane clear` 把当前配置摘掉，做完再恢复。
