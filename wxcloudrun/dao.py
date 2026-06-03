import logging
from sqlalchemy.exc import OperationalError
from wxcloudrun import db
from wxcloudrun.model import Category, Product, Tag, Collection, Article, CompanyInfo, Admin

logger = logging.getLogger('log')


# ==================== 产品 ====================

def get_products(category_id=None, tag_id=None, keyword=None, page=1, page_size=20, include_inactive=False):
    try:
        q = Product.query
        if not include_inactive:
            q = q.filter(Product.is_active == True)
        if category_id:
            q = q.filter(Product.category_id == category_id)
        if tag_id:
            q = q.join(Product.tags).filter(Tag.id == tag_id)
        if keyword:
            like = f'%{keyword}%'
            q = q.filter(db.or_(
                Product.product_name.like(like),
                Product.product_model.like(like),
                Product.product_series.like(like),
            ))
        total = q.count()
        products = q.order_by(Product.sort_order.asc(), Product.id.desc())\
                    .offset((page - 1) * page_size).limit(page_size).all()
        return [p.to_dict() for p in products], total
    except OperationalError as e:
        logger.error(f"get_products error: {e}")
        return [], 0


def get_product_by_id(product_id):
    try:
        return Product.query.get(product_id)
    except OperationalError as e:
        logger.error(f"get_product_by_id error: {e}")
        return None


def get_product_by_model(model):
    try:
        return Product.query.filter(Product.product_model == model).first()
    except OperationalError as e:
        logger.error(f"get_product_by_model error: {e}")
        return None


# ==================== 分类 ====================

def get_categories():
    try:
        return [c.to_dict() for c in Category.query.order_by(Category.sort_order.asc()).all()]
    except OperationalError as e:
        logger.error(f"get_categories error: {e}")
        return []


def get_or_create_category(name):
    try:
        cat = Category.query.filter(Category.name == name).first()
        if not cat:
            cat = Category(name=name)
            db.session.add(cat)
            db.session.flush()
        return cat
    except OperationalError as e:
        logger.error(f"get_or_create_category error: {e}")
        return None


# ==================== 标签 ====================

def get_tags(category=None):
    try:
        q = Tag.query
        if category:
            q = q.filter(Tag.category == category)
        return [t.to_dict() for t in q.order_by(Tag.sort_order.asc()).all()]
    except OperationalError as e:
        logger.error(f"get_tags error: {e}")
        return []


def get_or_create_tag(name, category='适用产品', sort_order=0):
    try:
        tag = Tag.query.filter(Tag.name == name).first()
        if not tag:
            tag = Tag(name=name, category=category, sort_order=sort_order)
            db.session.add(tag)
            db.session.flush()
        return tag
    except OperationalError as e:
        logger.error(f"get_or_create_tag error: {e}")
        return None


# ==================== 合集 ====================

def get_collections(carousel_only=False):
    try:
        q = Collection.query
        if carousel_only:
            q = q.filter(Collection.is_carousel == True)
        return [c.to_dict() for c in q.order_by(Collection.sort_order.asc()).all()]
    except OperationalError as e:
        logger.error(f"get_collections error: {e}")
        return []


# ==================== 文章 ====================

def get_articles(page=1, page_size=10, published_only=True):
    try:
        q = Article.query
        if published_only:
            q = q.filter(Article.is_published == True)
        total = q.count()
        articles = q.order_by(Article.published_at.desc(), Article.sort_order.asc())\
                    .offset((page - 1) * page_size).limit(page_size).all()
        return [a.to_dict() for a in articles], total
    except OperationalError as e:
        logger.error(f"get_articles error: {e}")
        return [], 0


def get_article_by_id(article_id):
    try:
        return Article.query.get(article_id)
    except OperationalError as e:
        logger.error(f"get_article_by_id error: {e}")
        return None


# ==================== 公司信息 ====================

def get_company_info():
    try:
        return CompanyInfo.query.first()
    except OperationalError as e:
        logger.error(f"get_company_info error: {e}")
        return None


# ==================== 管理员 ====================

def get_admin_by_username(username):
    try:
        return Admin.query.filter(Admin.username == username, Admin.is_active == True).first()
    except OperationalError as e:
        logger.error(f"get_admin_by_username error: {e}")
        return None
