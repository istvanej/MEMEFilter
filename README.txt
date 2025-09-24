# Meme 跟单简化版（Solana）

一套可落地的最小化流程：入口抓样本 → 过滤 → 评分 → 导出最终跟单名单。  
你只需要记住 **3 条命令 + 1 条清理**。

---

## 环境准备

```bash
# 1) 创建并激活虚拟环境（如已存在可跳过）
python3 -m venv .venv
source .venv/bin/activate

# 2) 安装依赖
pip install -r requirements.txt

# 3) 配置 .env（至少要有 SOLANA_RPC_URL）
cp .env.example .env  # 若没有 .env.example 就直接创建 .env
# 然后编辑 .env，设置：
# SOLANA_RPC_URL=你的RPC地址

每次开新终端记得：

source .venv/bin/activate
# 注入 .env，使 RPC 生效（或在 app/__init__.py 已自动加载）
set -a; source .env; set +a

一次性导入合约地址：

python -m app.cli import-token --mint <MINT地址>

抓地址（持有人+早期买家）
make holders early MINT=<MINT地址>

过滤（硬+软）
make filter

快照查看
python -m app.cli view --limit 100

评分+导入最终名单
make score MINT=<MINT地址>

清理：数据库/导出/日志
make clean

目录结构
app/
  rpc.py         # RPC 封装 + TOKEN_PROGRAM_ID
  solana_spl.py  # SPL 取持有人（jsonParsed 兼容）
  txscan.py      # 回放交易 + 窗口优化
  logscan.py     # 入口扫描（持有人/早期），实时日志
  filters.py     # 软/硬过滤
  t0.py          # 估算 T0
  rounds.py      # 回合重建 + USD 估值（有价源更准）
  score.py       # white/watch 评分 + 导出(含 SOL 余额)
  cli.py         # 统一命令入口
data/
  db.sqlite      # SQLite 数据库（自动生成）
  exports/       # 导出 TXT/CSV
logs/            # tee 的实时日志
Makefile         # 一键化命令
.env             # 你的RPC等环境变量


许可证
---

## `.gitignore`（建议加上）

在项目根目录创建 `.gitignore`：

```gitignore
# Python
__pycache__/
*.pyc
.venv/

# Local data
data/db.sqlite
data/exports/*
logs/*

# Env
.env
