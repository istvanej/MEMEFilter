#本意是想写一个smart money的过滤器，奈何sol上近期都是扬威盘......祝有缘人顺利！
#V2增加了链识别模块，兼容EVM链过滤，按需在.env文件添加链RPC即可；
#本人纯新人，借用Chatgpt的Vibe Coding，不好用勿喷，鼓励是最重要的！

---

# Meme Filter System

## 🧩 实现逻辑

本系统用于多链（Solana / BSC / Base）代币合约地址的投机用户分析与筛选，核心流程如下：

1. **入口层 (holders / early)**
   - `holders`：抓取某合约的持仓前 N 个地址  
   - `early`：扫描合约初期的交易日志，识别早期买家  

2. **评分层 (score-watch / score-white)**
   - 为候选地址打分，包括：  
     - **胜率 (win rate)**  
     - **交易回合数 (rounds)**  
     - **平均 PnL**  
     - **SOL / BNB / ETH 余额过滤**  

3. **筛选层 (gmgn_filter / score-select)**
   - 按条件过滤：
     - `min-win-rate`
     - `min-rounds`
     - `min-sol`, `max-sol`
   - 输出最终白名单地址

4. **导出层**
   - 统一导出 `CSV` 和 `TXT`  
   - 支持自动记录日志（每个环节都有 `[INFO]`, `[OK]`, `[ERR]` 提示）

---

## 📂 模块框架
app/
├── cli.py           # 主入口 CLI
├── gmgn_filter.py   # GMGN API 筛选模块
├── evm_rpc.py       # EVM 链 RPC 工具（支持分片 getLogs）
├── evm_scan.py      # EVM 持仓 & early 买家扫描
├── detect_chain.py  # 自动识别合约属于哪条链
scripts/
├── onekey.sh        # 一键执行脚本（从 Mint/Token -> 导出地址）
data/
├── exports/         # 所有导出结果 (CSV/TXT)
logs/                # 各环节日志


---

## ⚡ 执行命令

### 1. Solana
```bash
./scripts/onekey.sh <MINT_ADDRESS>

### 2. BSC
./scripts/onekey.sh <TOKEN_ADDRESS> bsc

### 3. Base
./scripts/onekey.sh <TOKEN_ADDRESS> base
### 4. 导出结果
ls -lt data/exports/
导出文件格式：
	•	final_<chain>_<prefix>_YYYYMMDD_HHMMSS.csv
	•	final_<chain>_<prefix>_YYYYMMDD_HHMMSS.txt
### 5. 清理数据库
make clean
