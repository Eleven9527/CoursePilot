"""按请求创建的课程资料检索工具。"""

from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, ConfigDict, Field

from app.core.auth import require_subject
from app.rag.retrieval.hybrid import retrieve


class SearchInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(
        min_length=1, max_length=1000,
        description="检索查询，保留题号、人名和英文短语",
    )


def create_search_tool(*, role: str | None, subject: str, grade: str,
                       unit_start: int, unit_end: int, question: str,
                       top_k: int = 5) -> BaseTool:
    """创建工具，并绑定后端确定的用户角色和课程范围。"""

    @tool(args_schema=SearchInput)
    def search_course_materials(query: str) -> dict:
        """检索当前账号在所选科目、年级和单元范围内可访问的课程资料。"""
        require_subject(role, subject)
        sources = retrieve(
            question, grade, unit_start, unit_end, top_k, query,
            subject=subject, include_drafts=role == "teacher",
        )
        return {"sources": sources}

    return search_course_materials
