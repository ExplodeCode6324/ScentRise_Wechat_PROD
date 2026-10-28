"""Application configuration loaded exclusively from environment variables."""

import os


def env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


DEBUG = env_bool("DEBUG", False)
TESTING = env_bool("TESTING", False)

DATABASE_URL = os.environ.get("DATABASE_URL")
MYSQL_USERNAME = os.environ.get("MYSQL_USERNAME")
MYSQL_PASSWORD = os.environ.get("MYSQL_PASSWORD")
MYSQL_ADDRESS = os.environ.get("MYSQL_ADDRESS")
MYSQL_DBNAME = os.environ.get("MYSQL_DBNAME", "scentrise")

JWT_SECRET = os.environ.get("JWT_SECRET")
JWT_EXP_HOURS = int(os.environ.get("JWT_EXP_HOURS", "8"))

AUTO_CREATE_DATABASE = env_bool("AUTO_CREATE_DATABASE", False)
AUTO_CREATE_TABLES = env_bool("AUTO_CREATE_TABLES", False)

MAX_CONTENT_LENGTH = int(os.environ.get("MAX_CONTENT_LENGTH", str(12 * 1024 * 1024)))
MAX_IMAGE_BYTES = int(os.environ.get("MAX_IMAGE_BYTES", str(10 * 1024 * 1024)))
MAX_IMPORT_ROWS = int(os.environ.get("MAX_IMPORT_ROWS", "5000"))

TCB_ENV_ID = os.environ.get("TCB_ENV_ID")
CDN_BASE = os.environ.get("CDN_BASE")
WECHAT_APPID = os.environ.get("WECHAT_APPID")
WECHAT_APPSECRET = os.environ.get("WECHAT_APPSECRET")
WECHAT_ACCESS_TOKEN = os.environ.get("WECHAT_ACCESS_TOKEN")
REQUESTS_CA_BUNDLE = os.environ.get("REQUESTS_CA_BUNDLE")
