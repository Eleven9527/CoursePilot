from secrets import compare_digest

from fastapi import HTTPException, Request

ACCOUNTS = {"teacher": "teacher", "student": "student"}
SUBJECTS = {"english": "英语", "math": "数学", "physics": "物理"}
SUBJECT_MEMBERSHIPS = {"teacher": frozenset(SUBJECTS), "student": frozenset({"english"})}


def require_subject(role: str | None, subject: str) -> None:
    if subject not in SUBJECT_MEMBERSHIPS.get(role, ()):
        raise HTTPException(403, "当前账号无权访问该科目")


def authenticate(account: str, password: str) -> bool:
    return account in ACCOUNTS and compare_digest(password.encode(), b"123")


def current_role(request: Request) -> str | None:
    return ACCOUNTS.get(request.session.get("account"))


def require_login(request: Request) -> None:
    if current_role(request) is None:
        raise HTTPException(401, "请先登录")


def require_teacher(request: Request) -> None:
    require_login(request)
    if current_role(request) != "teacher":
        raise HTTPException(403, "只有教师可以管理资料")
