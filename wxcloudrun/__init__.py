from flask import Flask
from flask_sqlalchemy import SQLAlchemy
import pymysql
import os
import config

# 因MySQLDB不支持Python3，使用pymysql扩展库代替MySQLDB库
pymysql.install_as_MySQLdb()

# 初始化web应用
app = Flask(__name__, instance_relative_config=True)
app.config['DEBUG'] = config.DEBUG

# 设定数据库链接
DB_NAME = os.environ.get('MYSQL_DBNAME', 'scentrise')
app.config['SQLALCHEMY_DATABASE_URI'] = 'mysql://{}:{}@{}/{}'.format(config.username, config.password,
                                                                     config.db_address, DB_NAME)

# 确保数据库存在（首次部署时 CynosDB 实例为空，只有 mysql/performance_schema 等系统库）
_host, _, _port = config.db_address.partition(':')
_port = int(_port) if _port else 3306
_conn = pymysql.connect(host=_host, port=_port, user=config.username, password=config.password,
                        charset='utf8mb4')
try:
    with _conn.cursor() as _cur:
        _cur.execute("CREATE DATABASE IF NOT EXISTS `{}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci".format(DB_NAME))
    _conn.commit()
finally:
    _conn.close()
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_size': 5,
    'max_overflow': 10,
    'pool_recycle': 1800,
    'pool_pre_ping': True,
    'pool_timeout': 10,
}

# 初始化DB操作对象
db = SQLAlchemy(app)

# 加载控制器
from wxcloudrun import views

# 加载后管 Blueprint
from wxcloudrun.admin import admin_bp
app.register_blueprint(admin_bp)

# 全局异常处理：确保所有错误都返回 JSON，防止 HTML 错误页导致前端 JSON 解析失败
from wxcloudrun.response import make_err_response

@app.errorhandler(Exception)
def handle_exception(e):
    app.logger.error(f'Unhandled error: {e}', exc_info=True)
    return make_err_response('服务器内部错误'), 500

@app.errorhandler(404)
def handle_404(e):
    return make_err_response('接口不存在'), 404

# 加载配置
app.config.from_object('config')

# 自动建表（云托管首次部署时数据库为空）
with app.app_context():
    db.create_all()

    # 自动创建默认管理员（首次部署无需 webshell 手动执行 seed_admin.py）
    from wxcloudrun.model import Admin
    if not Admin.query.first():
        import bcrypt
        pw_hash = bcrypt.hashpw('admin123'.encode(), bcrypt.gensalt()).decode()
        db.session.add(Admin(username='admin', passwd=pw_hash, real_name='管理员', role='admin', is_active=True))
        db.session.commit()
        app.logger.info('AUTO SEED: 管理员账号已创建 admin/admin123')

# 启动时打印关键环境变量状态，便于排查
import os as _os
for _var in ['WECHAT_APPID', 'WECHAT_APPSECRET', 'WECHAT_ACCESS_TOKEN',
             'TCB_ENV_ID', 'TCB_API_KEY', 'MYSQL_ADDRESS']:
    val = _os.environ.get(_var, '')
    _masked = val[:8] + '...' + val[-4:] if len(val) > 16 else (val[:4] + '***' if len(val) > 4 else val)
    app.logger.info('ENV %s = %s', _var, _masked if val else '(NOT SET)')
