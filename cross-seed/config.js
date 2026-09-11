// =====================================================================
// cross-seed 配置  ——  单种保种（按内容从其它站点匹配单种）
// ---------------------------------------------------------------------
// ⚠️ 版本免责声明（务必读）：
//   cross-seed 各大版本之间，配置键的名字/取值改过多次，例如：
//     - v5 用 linkDir(单个字符串)，v6 改为 linkDirs(数组)；
//     - matchMode 取值集在 v5(safe/risky) 与 v6(strict/flexible/partial) 不同；
//     - webhook 路径/参数、apiKey 生成方式也随版本变化。
//   本文件按"较新版本(v6.x)"书写，且尽量从环境变量取值（见 docker-compose）。
//   部署后请以你实际镜像的官方文档为准：
//     容器内 `cross-seed --help` / `cross-seed gen-config` / 官方 docs 站。
//   若启动报"unknown option"之类，多半是键名随版本变了，按提示改这里即可。
// ---------------------------------------------------------------------
// 值来源：docker-compose.yml 把 .env 的变量注入为环境变量，这里读取它们，
// 以便与编排器 config.yml / .env 单点维护同一批参数（IP、路径、apikey…）。
// =====================================================================

const csv = (s) => (s || "").split(",").map((x) => x.trim()).filter(Boolean);
const bool = (s) => String(s).toLowerCase() === "true";

module.exports = {
  // --- 站点来源：Prowlarr 的 Torznab feeds（含各站 apikey）---
  torznab: csv(process.env.TORZNAB_URLS),

  // --- 用"我已有的数据"去搜对应单种 ---
  // dataDirs：其"子目录"被当作 searchee。指向大包根目录 → 每部电影=一个 searchee。
  dataDirs: csv(process.env.DATA_DIRS),

  // 命中后在这里按"单种发布名/结构"建链接（做种数据），零磁盘开销。
  // v6：linkDirs 为数组；若你的镜像是 v5，改成  linkDir: csv(...)[0]
  linkDirs: csv(process.env.LINK_DIR),
  linkType: process.env.LINK_TYPE || "hardlink", // hardlink | symlink | reflink

  // 匹配严格度（取值随版本，见顶部说明）。内容匹配偏保守可用 partial/flexible。
  matchMode: process.env.MATCH_MODE || "partial",

  // --- 命中后的动作：注入 qBittorrent ---
  action: "inject",
  // 免密白名单模式：直接给 URL；密码模式：改成 http://user:pass@NAS_IP:3060
  qbittorrentUrl: process.env.QBIT_URL || "http://qbittorrent-reseed:3060",
  // 注入到统一分类，便于隔离/汇报/清理（cross-seed 会自动创建该分类）
  linkCategory: process.env.QBIT_CATEGORY || "reseed-singles",
  duplicateCategories: false,

  // 内容匹配（名称+大小，非哈希）→ 注入后务必让 qB 校验(recheck)确认数据一致，
  // 校验通过才做种，避免喂错数据被 H&R。true 仅适用于哈希已保证一致的场景。
  skipRecheck: bool(process.env.SKIP_RECHECK || "false"),

  // --- 守护进程 / API ---
  // 编排器通过 http://cross-seed:2468 调 webhook，用下面的 apiKey 鉴权。
  apiKey: process.env.CROSSSEED_API_KEY || undefined,
  port: 2468,
  host: "0.0.0.0",
  delay: 30, // 每次搜索之间的间隔(秒)，对站点友好、降低被限流风险

  // --- 电影场景的稳妥默认 ---
  includeNonVideos: true,      // 电影目录常含 nfo/字幕/海报，需一并纳入匹配
  includeSingleEpisodes: false, // 电影非剧集
  seasonFromEpisodes: undefined,

  // 中文站过 Cloudflare 时，Prowlarr 侧配置 FlareSolverr 即可，这里通常无需改。

  // 其余高级项（rssCadence、searchCadence、excludeRecentSearch、snatchTimeout…）
  // 按需在官方文档基础上补充。
};
