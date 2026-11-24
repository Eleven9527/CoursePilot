"""为当前教师请求创建讲义工具，复用接口中的授权和任务逻辑。"""

from uuid import uuid4

from fastapi import HTTPException, Request
from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, ConfigDict, Field

from app.api.v1.endpoints import prep
from app.api.v1.endpoints.qa import LessonScope
from app.core.auth import current_role, require_subject, require_teacher


class EmptyInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ResourceInput(EmptyInput):
    resource_id: str = Field(min_length=1, max_length=64, description="草稿或任务的标识")


class GenerateInput(EmptyInput):
    human_feedback: str = Field(default="", max_length=2000, description="教师对原稿的修改要求")
    original_draft_id: str | None = Field(default=None, description="反馈对应的原稿标识")


def create_prep_tools(request: Request, scope: LessonScope, *,
                      request_id: str | None = None) -> list[BaseTool]:
    """每个请求独立创建工具，身份、课程范围和幂等标识均由后端绑定。"""
    scope = scope.model_copy(deep=True)
    operation_id = request_id or uuid4().hex

    def authorize() -> None:
        require_teacher(request)
        require_subject(current_role(request), scope.subject)

    def check_scope(resource: dict) -> None:
        if any(resource[key] != getattr(scope, key)
               for key in ("subject", "grade", "unit_start", "unit_end")):
            raise HTTPException(403, "只能访问当前所选范围的讲义和任务")

    @tool(args_schema=EmptyInput)
    def list_teaching_drafts() -> dict:
        """列出当前所选科目、年级和单元范围内的讲义草稿及审批状态。"""
        authorize()
        drafts = prep.list_drafts(request)
        return {"drafts": [row for row in drafts if all(
            row[key] == getattr(scope, key)
            for key in ("subject", "grade", "unit_start", "unit_end")
        )]}

    @tool(args_schema=ResourceInput)
    def open_teaching_draft(resource_id: str) -> dict:
        """读取当前范围内的讲义草稿正文，用于回答教师问题或准备修改。"""
        authorize()
        draft = prep.open_draft(resource_id, request)
        check_scope(draft)
        return draft

    @tool(args_schema=GenerateInput)
    def queue_teaching_handout(human_feedback: str = "", original_draft_id: str | None = None) -> dict:
        """提交当前范围的讲义生成任务。修改讲义时提供原稿标识和教师反馈，返回任务标识供查询进度。"""
        authorize()
        if original_draft_id:
            check_scope(prep.open_draft(original_draft_id, request))
        body = prep.GenerationRequest(
            **scope.model_dump(), human_feedback=human_feedback,
            original_draft_id=original_draft_id,
        )
        return prep.queue_job(body, request, operation_id)

    @tool(args_schema=ResourceInput)
    def get_teaching_job(resource_id: str) -> dict:
        """查询当前范围内的讲义任务状态、执行阶段和错误，成功后可用任务标识打开草稿。"""
        authorize()
        job = prep.get_job(resource_id, request)
        check_scope(job)
        return job

    return [list_teaching_drafts, open_teaching_draft, queue_teaching_handout, get_teaching_job]
