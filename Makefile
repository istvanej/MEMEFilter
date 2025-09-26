BASE_TOPN ?= 800
EARLY_TOPN ?= 80
WINDOW_H ?= 1.0
SLEEP_MS ?= 120

WHITE_LIMIT ?= 300
WHITE_MIN_ROUNDS ?= 3
WHITE_TOPK ?= 100

WATCH_LIMIT ?= 600
WATCH_MIN_ROUNDS ?= 1
WATCH_TOPK ?= 200

HI_MIN_ROUNDS ?= 3
HI_MIN_WINRATE ?= 0.55
HI_MIN_AVGPNL ?= 0
HI_MIN_SOL ?= 0.5
HI_MAX_SOL ?= 15
HI_TOPK ?= 200

help:
	@echo "make holders early MINT=<mint>"
	@echo "make filter"
	@echo "make score MINT=<mint>"
	@echo "make clean"

.PHONY: prep
prep:
	@mkdir -p logs data/exports

holders: prep
	@echo ">>> holders: MINT=$(MINT) TOPN=$(BASE_TOPN)"
	@python -u -m app.logscan holders --mint $(MINT) --topn $(BASE_TOPN) | tee logs/holders_$$(date +%H%M%S).log

early: prep
	@echo ">>> early: MINT=$(MINT) base_topn=$(BASE_TOPN) out_topn=$(EARLY_TOPN) window_h=$(WINDOW_H) sleep_ms=$(SLEEP_MS)"
	@python -u -m app.logscan early --mint $(MINT) --base_topn $(BASE_TOPN) --out_topn $(EARLY_TOPN) --window_h $(WINDOW_H) --sleep-ms $(SLEEP_MS) | tee logs/early_$$(date +%H%M%S).log

filter: prep
	@python -u -m app.cli soft-filter --limit 2000 --verbose | tee logs/soft_$$(date +%H%M%S).log
	@python -u -m app.cli hard-verify --limit 2000 --verbose --sleep-ms 90 | tee logs/hard_$$(date +%H%M%S).log

score: prep
	@python -u -m app.cli score-white --mint $(MINT) --limit $(WHITE_LIMIT) --min-rounds $(WHITE_MIN_ROUNDS) --pos-expect --topk $(WHITE_TOPK) --sleep-ms 20 | tee logs/score_white_$$(date +%H%M%S).log
	@python -u -m app.cli score-watch --mint $(MINT) --limit $(WATCH_LIMIT) --min-rounds $(WATCH_MIN_ROUNDS) --require-activity --sort-by sol --topk $(WATCH_TOPK) --sleep-ms 10 | tee logs/score_watch_$$(date +%H%M%S).log
	@python -u -m app.cli score-select --mint $(MINT) --sources white,watch --min-rounds $(HI_MIN_ROUNDS) --min-win-rate $(HI_MIN_WINRATE) --min-avg-pnl $(HI_MIN_AVGPNL) --min-sol $(HI_MIN_SOL) --max-sol $(HI_MAX_SOL) --topk $(HI_TOPK) | tee logs/highwin_$$(date +%H%M%S).log
	@$(MAKE) final

final:
	@w_top=$$(ls -t data/exports/white_top_*.txt 2>/dev/null | head -n1); \
	wt_top=$$(ls -t data/exports/watch_top_*.txt 2>/dev/null | head -n1); \
	if [ -z "$$w_top" ] && [ -z "$$wt_top" ]; then echo "没有找到 top 文件"; exit 1; fi; \
	cat $$w_top $$wt_top | sort | uniq > data/exports/final_top.txt; \
	echo "[OK] Final -> data/exports/final_top.txt"

clean:
	@rm -f data/*.sqlite
	@rm -f data/exports/*.txt data/exports/*.csv
	@rm -f logs/*.log
	@echo "[OK] Cleaned DB/exports/logs"

reset:
	@python -u -m app.cli reset-mint --mint $(MINT)

gmgn:
	@python -u -m app.gmgn_filter --mint $(MINT) --min-win $(or $(MIN_WIN),0.5) --min-sol $(or $(MIN_SOL),1) --max-sol $(or $(MAX_SOL),50) $(EXTRA)

