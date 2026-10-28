"""Admin Blueprint — 后管 SPA 静态页面 + 文件服务"""

from flask import Blueprint, render_template

admin_bp = Blueprint(
    "admin",
    __name__,
    template_folder="templates",
    static_folder="static",
    static_url_path="/static",
    url_prefix="/admin",
)


@admin_bp.route("/")
def admin_index():
    """后管入口 — 返回 SPA admin.html"""
    return render_template("admin.html")
