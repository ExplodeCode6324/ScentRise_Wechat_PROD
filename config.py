import os

DEBUG = False

# MySQL 连接（生产环境必须通过CloudRun环境变量设置，无默认值）
username = os.environ.get("MYSQL_USERNAME")
password = os.environ.get("MYSQL_PASSWORD")
db_address = os.environ.get("MYSQL_ADDRESS")

# JWT 密钥（生产环境必须通过环境变量设置）
JWT_SECRET = os.environ.get('JWT_SECRET')
