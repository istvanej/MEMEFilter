# ====== 配置（可以按需改）======
BASE_TOPN ?= 300
EARLY_TOPN ?= 100
WINDOW_H ?= 2.0
SLEEP_MS ?= 60
WHITE_LIMIT ?= 800
WATCH_LIMIT ?= 1200
WHITE_MIN_ROUNDS ?= 3
WATCH_MIN_ROUNDS ?= 1
WHITE_TOPK ?= 100
WATCH_TOPK ?= 200

# ====== 帮助 ======
help:
	@echo "用法："
	@echo "  make holders MINT=<mint>      抓当前持有人（入口一）"
	@echo "  make early   MINT=<mint>      抓早期买家（入口二，时间窗优化）"
	@echo "  make filter                   过滤（软+硬）"
	@echo "  make score   MINT=<mint>      评分并导出（white + watch + 合并）"
	@echo "  make view                     查看当前状态快照"
	@echo "  make export                   导出三类名单 + 全表"
	@echo "  make final                    合并最新 white_top + watch_top → final_top.txt"

# ====== 目录准备 ======
.PHONY: prep
prep:
	@mkdir -p logs data/exports

# ====== 入口层 ======
holders: prep
	@echo ">>> holders: MINT=$(MINT) TOPN=$(BASE_TOPN)"
	@python -u -m app.logscan holders --mint $(MINT) --topn $(BASE_TOPN) | tee logs/holders_$$(date +%H%M%S).log

early: prep
	@echo ">>> early: MINT=$(MINT) base_topn=$(BASE_TOPN) out_topn=$(EARLY_TOPN) window_h=$(WINDOW_H) sleep_ms=$(SLEEP_MS)"
	@python -u -m app.logscan early --mint $(MINT) --base_topn $(BASE_TOPN) --out_topn $(EARLY_TOPN) --window_h $(WINDOW_H) --sleep_ms $(SLEEP_MS) | tee logs/early_$$(date +%H%M%S).log

# ====== 过滤层 ======
filter: prep
	@echo ">>> soft-filter"
	@python -u -m app.cli soft-filter --limit 2000 --verbose | tee logs/soft_$$(date +%H%M%S).log
	@echo ">>> hard-verify"
	@python -u -m app.cli hard-verify --limit 2000 --verbose --sleep-ms 75 | tee logs/hard_$$(date +%H%M%S).log

# ====== 查看 & 导出 ======
view:
	@python -m app.cli view --limit 120

export: prep
	@python -m app.cli export --kind WHITE
	@python -m app.cli export --kind WATCH
	@python -m app.cli export --kind BLACK

# ====== 评分（white + watch）并导出 top & 合并 ======
score: prep
	@echo ">>> score-white"
	@python -u -m app.cli score-white --mint $(MINT) \
	  --limit $(WHITE_LIMIT) --min-rounds $(WHITE_MIN_ROUNDS) --pos-expect \
	  --topk $(WHITE_TOPK) --sleep-ms 20 | tee logs/score_white_$$(date +%H%M%S).log
	@echo ">>> score-watch"
	@python -u -m app.cli score-watch --mint $(MINT) \
	  --limit $(WATCH_LIMIT) --min-rounds $(WATCH_MIN_ROUNDS) --require-activity \
	  --sort-by sol --topk $(WATCH_TOPK) --sleep-ms 10 | tee logs/score_watch_$$(date +%H%M%S).log
	@$(MAKE) final

final:
	@w_top=$$(ls -t data/exports/white_top_*.txt 2>/dev/null | head -n1); \
	wt_top=$$(ls -t data/exports/watch_top_*.txt 2>/dev/null | head -n1); \
	if [ -z "$$w_top" ] && [ -z "$$wt_top" ]; then echo "没有找到 top 文件"; exit 1; fi; \
	cat $$w_top $$wt_top | sort | uniq > data/exports/final_top.txt; \
	echo "[OK] Final -> data/exports/final_top.txt"
