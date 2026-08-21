"""JWT authentication and role authorization decorators."""

from __future__ import annotations

import datetime
from functools import wraps

import jwt
from flask import current_app, g, request

from wxcloudrun.response import make_err_response

JWT_ALGORITHM = "HS256"


def generate_token(admin_id, username, role="editor"):
    now = datetime.datetime.now(datetime.UTC)
    payload = {
        "admin_id": admin_id,
        "username": username,
        "role": role,
        "exp": now + datetime.timedelta(hours=current_app.config["JWT_EXP_HOURS"]),
        "iat": now,
    }
    return jwt.encode(
        payload,
        current_app.config["JWT_SECRET"],
        algorithm=JWT_ALGORITHM,
    )


def _authenticate_request():
    auth_header = request.headers.get("Authorization", "")
    token = (
        auth_header[7:].strip()
        if auth_header.startswith("Bearer ")
        else request.cookies.get("admin_session", "")
    )
    if not token:
        return None, make_err_response("未登录或 token 无效", 401)
    try:
        payload = jwt.decode(
            token,
            current_app.config["JWT_SECRET"],
            algorithms=[JWT_ALGORITHM],
            options={"require": ["exp", "iat", "admin_id", "username"]},
        )
    except jwt.ExpiredSignatureError:
        return None, make_err_response("登录已过期，请重新登录", 401)
    except (jwt.InvalidTokenError, KeyError, TypeError):
        return None, make_err_response("token 无效", 401)

    from wxcloudrun import db
    from wxcloudrun.model import Admin

    admin = db.session.get(Admin, payload["admin_id"])
    if not admin or not admin.is_active or admin.username != payload["username"]:
        return None, make_err_response("管理员已停用或不存在", 401)
    issued_at = datetime.datetime.fromtimestamp(payload["iat"], datetime.UTC)
    if admin.updated_at:
        changed_at = admin.updated_at
        if changed_at.tzinfo is None:
            # MySQL TIMESTAMP values are returned without tzinfo in the process
            # timezone; convert that wall-clock value to UTC before comparing.
            changed_at = changed_at.astimezone(datetime.UTC)
        else:
            changed_at = changed_at.astimezone(datetime.UTC)
        if issued_at.replace(microsecond=0) < changed_at.replace(microsecond=0):
            return None, make_err_response("登录状态已失效，请重新登录", 401)
    g.admin_id = admin.id
    g.admin_username = admin.username
    g.admin_role = admin.role or "editor"
    g.admin = admin
    return admin, None


def require_admin(func):
    @wraps(func)
    def decorated(*args, **kwargs):
        _admin, error = _authenticate_request()
        if error:
            return error
        return func(*args, **kwargs)

    return decorated


def require_roles(*allowed_roles):
    allowed = set(allowed_roles)

    def decorator(func):
        @wraps(func)
        def decorated(*args, **kwargs):
            _admin, error = _authenticate_request()
            if error:
                return error
            if g.admin_role not in allowed:
                return make_err_response("权限不足", 403)
            return func(*args, **kwargs)

        return decorated

    return decorator
