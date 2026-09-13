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

  // ★★★ 2026-09-13：硬链接农场下这里**只能 strict**，不跟随 .env ★★★
  // 机理（已实证，见 README「源文件被写穿」）：
  //   matchMode=partial/flexible 会让 cross-seed 把「名称+大小匹配、但 piece 不一致」
  //   的单种也注入。qB 校验(recheck)发现 piece 对不上 → **就地重下那几个 piece**；
  //   而 linkDirs 是硬链接（与 reseed_farm、download/movies|TV 同一个 inode），
  //   于是这次重下**写穿到源文件**，无声改写库里的母本，且 Farm 侧仍显示 100%。
  //   官方文档对 partial 的描述恰好印证这一点：
  //     "Nearly all partial matches recheck to 99.9% rather than 100%"
  //   —— 上游把它当作预期行为；在硬链接农场里它就是事故。
  //   实证（2026-09-13）：
  //     · 哥谭.全5季 ih=04421b52 决策 MATCH_PARTIAL，完成 09-13 16:35，
  //       对应源文件 mtime 15:57/16:05/16:35 —— 分秒吻合；
  //     · 教父1972  ih=db7be3ac 决策 MATCH_PARTIAL，完成 09-12 09:49，
  //       对应源文件 mtime 09-12 09:49 —— 分秒吻合；
  //     · 同一份《致命魔术》被 5 条 MATCH 注入（完成 09-12 19:22）源毫发无伤，
  //       第 6 条 MATCH_PARTIAL 卡在 99.9996% 正在重下。
  // 故**硬编码 strict**：只注入完全匹配，源永不被重下。.env 的 MATCH_MODE 保留
  // 仅为兼容，非 strict 一律忽略并告警（绝不静默放行）。
  // 要恢复宽松匹配，前提是让做种数据与源脱离同一 inode（reflink / 独立副本），
  // 而不是把这里改回去。
  matchMode: (() => {
    const m = String(process.env.MATCH_MODE || "").trim().toLowerCase();
    if (m && m !== "strict") {
      console.warn(
        "[config] 忽略 MATCH_MODE=" + m + "：硬链接农场下非 strict 注入会写穿源文件，" +
          "已强制 strict。要放宽请先让做种数据与源脱离同一 inode（reflink/独立副本）。"
      );
    }
    return "strict";
  })(),

  // --- 命中后的动作：注入 qBittorrent ---
  action: "inject",
  // 免密白名单模式：直接给 URL；密码模式：改成 http://user:pass@NAS_IP:3060
  qbittorrentUrl: process.env.QBIT_URL || "http://qbittorrent-reseed:3060",
  // 注入到统一分类，便于隔离/汇报/清理（cross-seed 会自动创建该分类）
  linkCategory: process.env.QBIT_CATEGORY || "reseed-singles",
  duplicateCategories: false,

  // ★ 校验必开（false）。但**别把 recheck 当安全网** —— 2026-09-13 的教训：
  //   recheck 不通过时 qB 不会拒绝，而是**就地重下**缺失 piece，直接改写源文件。
  //   真正挡住事故的是上面的 matchMode: "strict"（不匹配的根本不注入）。
  //   这个键保持 false，只是为了让万一漏进来的不匹配尽早暴露出来，而不是"修好"它。
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
