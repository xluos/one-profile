# Argos 排错 tips

详细 bytedcli log 命令见 `bytedcli` skill 的 log GUIDE。这里只记联调常踩的细节。

## 同步延迟（最常见）

Argos 写入到可查询有 **30s ~ 3min 延迟**。第一次查不到日志**不代表没**，要 poll：

```bash
until NPM_CONFIG_REGISTRY=http://bnpm.byted.org npx -y @bytedance-dev/bytedcli@latest \
      log get-logid-log "<logid>" --psm "<psm>" --vregion "China-North" \
      --output file --output-file /tmp/logid.log >/dev/null 2>&1 \
      && [ "$(wc -l < /tmp/logid.log)" -gt 5 ]; do
  sleep 20
done
echo "ready"
```

5 行是阈值（小于这个数字基本是「Logid trace fetched. \n LogID: xxx」的空响应）。

如果 poll 5 分钟还没数据，**不是延迟问题**，去查 PSM。

## vregion 选择

| 区域 | --site | 默认 vregion | 备注 |
|---|---|---|---|
| 中国大陆 prod | `cn`（默认） | `China-North` | 抖音 / 抖运 / 飞书国内 |
| 中国大陆 BOE | `boe` | `China-BOE` | BOE 联调 |
| 中国大陆 BOE i18n 分区 | `boe` | `US-BOE` | 显式传 |
| 国际化 SaaS | `i18n` / `i18n-bd` | `Singapore-SaaS` | |
| 国际化 Central | `i18n-tt` | `Singapore-Central` | |
| TikTok US | `us-ttp` | `US-TTP` | |
| TikTok US v2 | `us-ttp` | `US-TTP2` | 显式传，独立泳道 |
| EU TTP | `eu-ttp` / `i18n-tt` | `EU-Compliance2` 等 | 5 个 vregion 都在 tiktok-eu.org |

⚠️ **vregion 错查不到日志且不报错**（返回空），不是命令失败，是路由到错的存储分片。如果用户的服务在 i18n 而你默认查 cn，永远查不到。

不确定时**先问用户服务部署在哪个区域**，或看 PSM 命名约定（i18n / global / us 等前缀通常是非 cn）。

## get-logid-log 没数据时确认 PSM 是否对

step 1: 拿 logid 直接查 → 没数据。

step 2: 用 search-psm-log 大窗口 + 通用关键词扫，看 PSM 在该时段有没有任何活动：

```bash
bytedcli log search-psm-log --psm "<psm>" --vregion "China-North" \
  --start "2026-05-07T17:00:00+08:00" \
  --end   "2026-05-07T18:00:00+08:00" \
  --max-logs 50 --limit 50 \
  --output file --output-file /tmp/psm-scan.log
```

- 50+ 条返回 → PSM 对，是 logid 没同步上 / vregion 错
- 0 条 → PSM 错，回 `bam.config.json` 重查

step 3: 也可以按泳道过滤：

```bash
bytedcli log search-psm-log --psm "<psm>" --vregion "China-North" \
  --start ... --end ... --kv-filter "_stage=ppe_<lane>" \
  --max-logs 20 --limit 20 ...
```

如果该 PSM 在该泳道**完全没活动**，说明：
- 后端没把服务部署到这个泳道
- 或部署了但实例没启动 / 起来后立刻挂

这时候报告给后端：「PSM `<psm>` 在 ppe_`<lane>` 泳道无活动日志（过去 1h），是不是部署没上来？」

## 提取 logid 关键字段（一键 grep）

拿到 logid 日志文件后，下面这条 grep 把关键字段抽出来：

```bash
grep -oE "_image_version=[^ ]+|_pod_name=[^ ]+|_env=[^ ]+|_env_type=[^ ]+|_tce_physical_cluster=[^ ]+|condition field not found.{0,200}|select field not found.{0,200}|bizKey: [^ ,\"]+|StatusCode:[0-9]+|StatusMessage:\"[^\"]*\"" /tmp/logid.log | sort -u
```

输出包括：
- pod / image / env：定位是哪个泳道哪个 image 处理的请求
- 错误码 + 报错原文：直接给后端
- bizKey：后端 BO 配置的真实 key

## 常见 PSM × bizKey 别名

抖运：
- ViewScene `scale_ops_author_list_new` (FE 发) → bizKey `scale_ops_author_list` (BO 校验)

具体业务里看 server 日志的 `bizKey: <name>` 字段才是真名。

## "已发但还没生效" 的常见原因

后端说"已发"但你查 PPE 仍报缺字段，可能：

1. **新 image 没含他改的 BO 配置文件** — 给 image_version，让他对比 git commit
2. **BO 走 TCC 配置中心拉，PPE 泳道 TCC namespace 没推** — 给 image_version + pod，让他查 TCC
3. **注册到了别的 bizKey** — 给 bizKey，对比 spec 里写的
4. **CDN / 代理缓存** — 偶发，可能不是这种问题（BO 注册不走 CDN）
5. **改了 IDL 没改 server** — 给 image_version 对比代码

这些都需要后端自己去 argos 查，FE 提供 logid + image + pod + bizKey 即可。
