"""Explicit one-time administrator creation utility."""

import os

import bcrypt

from wxcloudrun import app, db
from wxcloudrun.model import Admin


def main():
    if os.environ.get("ALLOW_ADMIN_SEED", "").lower() not in {"1", "true", "yes"}:
        raise SystemExit("拒绝执行：请显式设置 ALLOW_ADMIN_SEED=1")
    username = os.environ.get("INITIAL_ADMIN_USERNAME", "admin").strip()
    password = os.environ.get("INITIAL_ADMIN_PASSWORD", "")
    if not username or len(username) > 50:
        raise SystemExit("INITIAL_ADMIN_USERNAME 不合法")
    if not 12 <= len(password) <= 72:
        raise SystemExit("INITIAL_ADMIN_PASSWORD 必须为12到72个字符")
    with app.app_context():
        if Admin.query.filter_by(username=username).first():
            raise SystemExit("管理员账号已存在，未做修改")
        admin = Admin(
            username=username,
            passwd=bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode(),
            real_name=os.environ.get("INITIAL_ADMIN_REAL_NAME", "管理员")[:50],
            role="admin",
            is_active=True,
        )
        db.session.add(admin)
        db.session.commit()
        print(f"管理员账号 {username} 已创建；密码未输出")


if __name__ == "__main__":
    main()
