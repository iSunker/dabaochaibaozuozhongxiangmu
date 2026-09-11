"""cross-seed 守护进程 HTTP API 客户端（触发"按数据(data-based)搜索"）。

⚠️ 版本差异提醒：cross-seed 的 API 路径/参数/鉴权方式随版本有变化，部署时
请对照你实际安装版本的官方文档 https://www.cross-seed.org/ 核对以下几点：
  - 触发 data 搜索的端点：多为 POST /api/webhook，body 传 {"path": "<目录>"}；
    也有版本用表单字段 data-dirs / infoHash 等。
  - 鉴权：apiKey 可能走 HTTP 头 X-Api-Key，或查询串 ?apikey=xxx。
  - 传入的 path 通常必须落在 config.js 里 dataDirs 允许的范围内。
本客户端两种鉴权方式都带上（头 + 查询串），端点用 /api/webhook；若你的版本
不同，改这里一处即可。
"""
from __future__ import annotations

import logging
from urllib.parse import urlencode

log = logging.getLogger("reseed.crossseed")


class CrossSeedError(Exception):
    pass


class CrossSeedClient:
    def __init__(self, base_url: str, *, api_key: str = "", timeout: float = 60.0):
        self.base = base_url.rstrip("/")
        self.api_key = api_key
        self.http = HttpClient(timeout=timeout)

    def _headers(self) -> dict[str, str]:
        return {"X-Api-Key": self.api_key} if self.api_key else {}

    def _q(self, path: str) -> str:
        url = f"{self.base}{path}"
        if self.api_key:
            sep = "&" if "?" in url else "?"
            url = f"{url}{sep}{urlencode({'apikey': self.api_key})}"
        return url

    def ping(self) -> bool:
        """确认守护进程返回成功响应。"""
        try:
            response = self.http.get(self.base, headers=self._headers())
        except HttpError as e:
            log.warning("cross-seed 不可达 @ %s: %s", self.base, e)
            return False
        if not response.ok:
            log.warning("cross-seed 返回 HTTP %s @ %s", response.status, self.base)
            return False
        return True

    def search_data_path(self, path: str) -> Response:
        """对某个数据目录（一部单片）触发按内容搜索/匹配/注入。"""
        try:
            r = self.http.post_json(self._q("/api/webhook"), {"path": path}, headers=self._headers())
        except HttpError as e:
            raise CrossSeedError(f"触发 cross-seed 搜索失败（path={path}）: {e}") from e
        if not r.ok:
            raise CrossSeedError(
                f"cross-seed 搜索失败（HTTP {r.status}, path={path}, body={r.text[:200]!r}）"
            )
        log.info("已触发 cross-seed 搜索: %s", path)
        return r
