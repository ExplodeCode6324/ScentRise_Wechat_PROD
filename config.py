import os

DEBUG = True

# MySQL 连接：云托管部署时自动注入环境变量，本地开发用下面的默认值
username = os.environ.get("MYSQL_USERNAME", 'root')
password = os.environ.get("MYSQL_PASSWORD", '9CPcksGG')
db_address = os.environ.get(
    "MYSQL_ADDRESS",
    'sh-cynosdbmysql-grp-3c7a1auu.sql.tencentcdb.com:20699'
)
