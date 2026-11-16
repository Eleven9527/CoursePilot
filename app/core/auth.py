from secrets import compare_digest

from fastapi import HTTPException, Request

ACCOUNTS = {"teacher": "teacher", "student": "student"}


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
