# 按操作系统选择项目虚拟环境中的 Python，可用 PYTHON 覆盖。
ifeq ($(OS),Windows_NT)
PYTHON ?= .venv/Scripts/python.exe
else
PYTHON ?= .venv/bin/python
endif

# 检索评测默认取前 5 条，可在运行时传入 TOP_K 覆盖。
TOP_K ?= 5

.PHONY: eval-validate eval-retrieval test-permissions test-prep

# 验证科目和发布权限，使用临时 SQLite 和模拟服务。
test-permissions:
	"$(PYTHON)" -m pytest -q tests/test_qa_permissions.py

# 验证讲义自动保存、拒绝重生成、审阅后导出和学生越权拦截。
test-prep:
	"$(PYTHON)" -m pytest -q tests/test_prep_workflow.py

# 核对评测集的依据短语是否存在于当前数据库的切分块中。
eval-validate:
	"$(PYTHON)" -m evals.retrieval --validate-only

# 跑纯向量检索基线，需要 Embedding 服务和 Milvus。
eval-retrieval:
	"$(PYTHON)" -m evals.retrieval --top-k $(TOP_K)
.PHONY: eval-qa
# 通过运行中的 CoursePilot API 评测检索、回答引用和意图路由。
eval-qa:
	"$(PYTHON)" -m evals.qa --top-k $(TOP_K)
