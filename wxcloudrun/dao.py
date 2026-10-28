from sqlalchemy import or_

from wxcloudrun import db
from wxcloudrun.model import Admin, Article, Category, Collection, CompanyInfo, Product, Tag


def get_products(
    category_id=None,
    tag_id=None,
    keyword=None,
    page=1,
    page_size=20,
    include_inactive=False,
):
    query = Product.query
    if not include_inactive:
        query = query.filter(Product.is_active.is_(True))
    if category_id:
        query = query.filter(Product.category_id == category_id)
    if tag_id:
        query = query.join(Product.tags).filter(Tag.id == tag_id)
    if keyword:
        pattern = f"%{keyword}%"
        query = query.filter(
            or_(
                Product.product_name.like(pattern),
                Product.product_model.like(pattern),
                Product.product_series.like(pattern),
            )
        )
    total = query.count()
    products = (
        query.order_by(Product.sort_order.asc(), Product.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return [product.to_dict() for product in products], total


def get_product_by_id(product_id, *, include_inactive=True):
    product = db.session.get(Product, product_id)
    if product and (include_inactive or product.is_active):
        return product
    return None


def get_product_by_model(model):
    return Product.query.filter(Product.product_model == model).first()


def get_categories():
    return [
        category.to_dict() for category in Category.query.order_by(Category.sort_order.asc()).all()
    ]


def get_or_create_category(name):
    category = Category.query.filter(Category.name == name).first()
    if not category:
        category = Category(name=name)
        db.session.add(category)
        db.session.flush()
    return category


def get_tags(category=None, page=None, page_size=20):
    query = Tag.query
    if category:
        query = query.filter(Tag.category == category)
    if page is not None:
        total = query.count()
        tags = (
            query.order_by(Tag.sort_order.asc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        return [tag.to_dict() for tag in tags], total
    return [tag.to_dict() for tag in query.order_by(Tag.sort_order.asc()).all()]


def get_or_create_tag(name, category="适用产品", sort_order=0):
    tag = Tag.query.filter(Tag.name == name).first()
    if not tag:
        tag = Tag(name=name, category=category, sort_order=sort_order)
        db.session.add(tag)
        db.session.flush()
    return tag


def get_collections(
    carousel_only=False,
    page=None,
    page_size=20,
    *,
    include_inactive_products=False,
):
    query = Collection.query
    if carousel_only:
        query = query.filter(Collection.is_carousel.is_(True))
    if page is not None:
        total = query.count()
        collections = (
            query.order_by(Collection.sort_order.asc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        return [
            collection.to_dict(include_inactive_products=include_inactive_products)
            for collection in collections
        ], total
    return [
        collection.to_dict(include_inactive_products=include_inactive_products)
        for collection in query.order_by(Collection.sort_order.asc()).all()
    ]


def get_articles(page=1, page_size=10, published_only=True):
    query = Article.query
    if published_only is True:
        query = query.filter(Article.is_published.is_(True))
    elif published_only is False:
        query = query.filter(Article.is_published.is_(False))
    total = query.count()
    articles = (
        query.order_by(Article.published_at.desc(), Article.sort_order.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return [article.to_dict() for article in articles], total


def get_article_by_id(article_id, *, published_only=False):
    article = db.session.get(Article, article_id)
    if article and (not published_only or article.is_published):
        return article
    return None


def get_company_info():
    return CompanyInfo.query.first()


def get_admin_by_username(username):
    if not username:
        return None
    return Admin.query.filter(Admin.username == username, Admin.is_active.is_(True)).first()
