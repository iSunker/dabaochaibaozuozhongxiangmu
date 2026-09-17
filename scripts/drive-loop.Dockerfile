# drive-loop 镜像（`#58` 容器化的第二步）
#
# ★★ 与 `orchestrator/Dockerfile` 的关键差别：**没有 pip install**。
#   理由（2026-09-17 本机实测，不是推断）：
#     `scripts/drive-loop.py` 的 import 闭包 = `orchestrator.state` + `notify`，
#     而这三处的顶层 import **全是标准库**
#     （`orchestrator/__init__.py` 只有 docstring、`state.py` 纯 stdlib）。
#     `yaml` 只在 `orchestrator/config.py`，drive-loop **不走那条路径**。
#   ⇒ 立 `python:3.12-slim` 跑得起来（实证：在没装任何 pip 包的镜像里
#     `from orchestrator import state` 与 `import notify` 均 OK）。
#   ★ 若哪天 drive-loop 开始用第三方库，**必须在这里补 pip**，
#     而判据是「import 闭包里非标准库的有没有」——`D:\tmp\check_imports.py` 就是查这个的。
#
# ★★ 迁容器的**顺带收益**：摆脱 DSM 的 python 3.8.15（见 `ERR-PY-01`：
#   那是整条链路的单点依赖，而 `from __future__ import annotations` 是为它加的）。
#   这里直接 3.12 ⇒ 那几个兼容性顾虑在容器里**消失**。
FROM python:3.12-slim

LABEL org.opencontainers.image.title="reseed-drive-loop" \
      org.opencontainers.image.description="大包拆包·单种保种 · drive-loop（一次性容器）"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONIOENCODING=utf-8 \
    TZ=Asia/Shanghai

WORKDIR /app

# ★ 代码是**挂进去**的（见 compose 的挂载清单），这里 COPY 只是为了让镜像**脱离挂载也能冒烟**。
#   本仓的形状：`scripts/` 与 `orchestrator/` 同级，
#   而 `drive-loop.py` 靠 `sys.path.insert(ROOT)`（ROOT = scripts/ 的上级）找 `orchestrator`。
#   ⇒ 镜像里必须**保持这个相对形状**：/app/scripts/ + /app/orchestrator/
COPY orchestrator/ /app/orchestrator/
COPY scripts/drive-loop.py   /app/scripts/drive-loop.py
COPY scripts/notify.py       /app/scripts/notify.py
COPY scripts/reseed-state.py /app/scripts/reseed-state.py
# ★ `_run_verify()` 会起子进程跑它 ⇒ **必须在镜像里**（2026-09-17 读代码发现，`#58` 记过）
COPY scripts/build-farm.sh   /app/scripts/build-farm.sh

# 默认只打印用法，不真跑（真跑用 `docker compose run --rm drive-loop …`）
ENTRYPOINT ["python", "/app/scripts/drive-loop.py"]
CMD ["--help"]
