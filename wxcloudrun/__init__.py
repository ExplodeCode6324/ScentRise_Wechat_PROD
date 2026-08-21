import logging
import re
from urllib.parse import quote_plus

import pymysql
from flask import Flask, request
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from werkzeug.exceptions import HTTPException

import config


def _mysql_uri():
    missing = [
        name
        for name, value in {
            "MYSQL_USERNAME": config.MYSQL_USERNAME,
            "MYSQL_PASSWORD": config.MYSQL_PASSWORD,
            "MYSQL_ADDRESS": config.MYSQL_ADDRESS,
        }.items()
        if not value
    ]
    if missing:
        raise RuntimeError("缺少必需环境变量: " + ", ".join(missing))
    return f"mysql+pymysql://{quote_plus(config.MYSQL_USERNAME)}:{quote_plus(config.MYSQL_PASSWORD)}@{config.MYSQL_ADDRESS}/{quote_plus(config.MYSQL_DBNAME)}?charset=utf8mb4"


def _create_database_if_requested():
    if not config.AUTO_CREATE_DATABASE or config.DATABASE_URL:
        return
    if not re.fullmatch(r"[A-Za-z0-9_]+", config.MYSQL_DBNAME):
        raise RuntimeError("MYSQL_DBNAME只能包含字母、数字和下划线")
    host, _, port_text = config.MYSQL_ADDRESS.partition(":")
    connection = pymysql.connect(
        host=host,
        port=int(port_text or 3306),
        user=config.MYSQL_USERNAME,
        password=config.MYSQL_PASSWORD,
        charset="utf8mb4",
        connect_timeout=10,
    )
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                f"CREATE DATABASE IF NOT EXISTS `{config.MYSQL_DBNAME}` "
                "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
        connection.commit()
    finally:
        connection.close()


if not config.JWT_SECRET:
    raise RuntimeError("缺少必需环境变量 JWT_SECRET，禁止使用固定兜底密钥")
if len(config.JWT_SECRET.encode("utf-8")) < 32:
    raise RuntimeError("JWT_SECRET至少需要32字节的随机值")
if not 1 <= config.JWT_EXP_HOURS <= 168:
    raise RuntimeError("JWT_EXP_HOURS必须在1到168之间")

_create_database_if_requested()

app = Flask(__name__, instance_relative_config=True)
app.config.update(
    DEBUG=config.DEBUG,
    TESTING=config.TESTING,
    SQLALCHEMY_DATABASE_URI=config.DATABASE_URL or _mysql_uri(),
    SQLALCHEMY_TRACK_MODIFICATIONS=False,
    MAX_CONTENT_LENGTH=config.MAX_CONTENT_LENGTH,
    MAX_IMAGE_BYTES=config.MAX_IMAGE_BYTES,
    MAX_IMPORT_ROWS=config.MAX_IMPORT_ROWS,
    JWT_SECRET=config.JWT_SECRET,
    JWT_EXP_HOURS=config.JWT_EXP_HOURS,
)
if not app.config["SQLALCHEMY_DATABASE_URI"].startswith("sqlite"):
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
        "pool_size": 3,
        "max_overflow": 5,
        "pool_recycle": 900,
        "pool_pre_ping": True,
        "pool_timeout": 10,
    }

db = SQLAlchemy(app)
migrate = Migrate(app, db, compare_type=True)

from wxcloudrun import views  # noqa: E402,F401
from wxcloudrun.admin import admin_bp  # noqa: E402
from wxcloudrun.response import make_err_response  # noqa: E402

app.register_blueprint(admin_bp)


@app.errorhandler(HTTPException)
def handle_http_exception(error):
    return make_err_response(error.description, error.code or 500)


@app.errorhandler(Exception)
def handle_exception(error):
    db.session.rollback()
    app.logger.error("Unhandled error: %s", error, exc_info=True)
    return make_err_response("服务器内部错误", 500)


@app.after_request
def add_security_headers(response):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://cdn.sheetjs.com; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: blob: https: cloud:; "
        "connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'",
    )
    if request.is_secure:
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
        )
    if request.path.startswith("/admin") or request.path.startswith("/api/admin"):
        response.headers.setdefault("Cache-Control", "no-store")
    return response


if config.AUTO_CREATE_TABLES:
    with app.app_context():
        db.create_all()
        logging.getLogger(__name__).warning(
            "AUTO_CREATE_TABLES is enabled; use database migrations in production"
        )
