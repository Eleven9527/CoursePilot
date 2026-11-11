ifeq ($(OS),Windows_NT)
PYTHON ?= .venv/Scripts/python.exe
else
PYTHON ?= .venv/bin/python
endif

TOP_K ?= 5

.PHONY: eval-validate eval-retrieval

eval-validate:
	"$(PYTHON)" -m evals.retrieval --validate-only

eval-retrieval:
	"$(PYTHON)" -m evals.retrieval --top-k $(TOP_K)
