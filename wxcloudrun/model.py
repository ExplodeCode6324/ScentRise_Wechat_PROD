from datetime import datetime
from wxcloudrun import db

# 产品-标签关联表（多对多中间表）
product_tags = db.Table(
    'product_tags',
    db.Column('product_id', db.Integer, db.ForeignKey('products.id', ondelete='CASCADE'), primary_key=True),
    db.Column('tag_id', db.Integer, db.ForeignKey('tags.id', ondelete='CASCADE'), primary_key=True)
)

# 合集-产品关联表（多对多中间表）
collection_products = db.Table(
    'collection_products',
    db.Column('collection_id', db.Integer, db.ForeignKey('collections.id', ondelete='CASCADE'), primary_key=True),
    db.Column('product_id', db.Integer, db.ForeignKey('products.id', ondelete='CASCADE'), primary_key=True),
    db.Column('sort_order', db.Integer, default=0)
)


class Category(db.Model):
    __tablename__ = 'categories'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    icon = db.Column(db.String(500))
    sort_order = db.Column(db.Integer, default=0)
    created_at = db.Column('created_at', db.TIMESTAMP, default=datetime.now)
    updated_at = db.Column('updated_at', db.TIMESTAMP, default=datetime.now, onupdate=datetime.now)
    products = db.relationship('Product', backref='category', lazy='dynamic')

    def to_dict(self):
        return {'id': self.id, 'name': self.name, 'icon': self.icon, 'sortOrder': self.sort_order}


class Tag(db.Model):
    __tablename__ = 'tags'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False, unique=True)
    category = db.Column(db.String(50))
    icon = db.Column(db.String(500))
    banner_image = db.Column(db.String(500))
    sort_order = db.Column(db.Integer, default=0)
    created_at = db.Column('created_at', db.TIMESTAMP, default=datetime.now)
    updated_at = db.Column('updated_at', db.TIMESTAMP, default=datetime.now, onupdate=datetime.now)

    def to_dict(self):
        return {'id': self.id, 'name': self.name, 'category': self.category,
                'icon': self.icon, 'bannerImage': self.banner_image, 'sortOrder': self.sort_order}


class Product(db.Model):
    __tablename__ = 'products'
    id = db.Column(db.Integer, primary_key=True)
    product_series = db.Column(db.String(50))
    product_name = db.Column(db.String(200), nullable=False)
    product_model = db.Column(db.String(100), nullable=False, unique=True)
    product_desc = db.Column(db.Text)
    product_image = db.Column(db.String(500))
    product_images = db.Column(db.Text)
    sort_order = db.Column(db.Integer, default=0)
    is_active = db.Column(db.Boolean, default=True)
    category_id = db.Column(db.Integer, db.ForeignKey('categories.id', ondelete='SET NULL'))
    created_at = db.Column('created_at', db.TIMESTAMP, default=datetime.now)
    updated_at = db.Column('updated_at', db.TIMESTAMP, default=datetime.now, onupdate=datetime.now)

    tags = db.relationship('Tag', secondary=product_tags, lazy='joined',
                           backref=db.backref('products', lazy='dynamic'))

    def to_dict(self):
        import json
        return {
            'id': self.id,
            'productSeries': self.product_series,
            'productName': self.product_name,
            'productModel': self.product_model,
            'productDesc': self.product_desc,
            'productImage': self.product_image,
            'productImages': json.loads(self.product_images) if self.product_images else [],
            'sortOrder': self.sort_order,
            'isActive': self.is_active,
            'categoryId': self.category_id,
            'tags': [t.to_dict() for t in self.tags] if self.tags else [],
        }


class Collection(db.Model):
    __tablename__ = 'collections'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    cover_image = db.Column(db.String(500))
    is_carousel = db.Column(db.Boolean, default=False)
    sort_order = db.Column(db.Integer, default=0)
    carousel_sort = db.Column(db.Integer, default=0)
    created_at = db.Column('created_at', db.TIMESTAMP, default=datetime.now)
    updated_at = db.Column('updated_at', db.TIMESTAMP, default=datetime.now, onupdate=datetime.now)

    products = db.relationship('Product', secondary=collection_products, lazy='dynamic')

    def to_dict(self):
        return {
            'id': self.id, 'name': self.name, 'description': self.description,
            'coverImage': self.cover_image, 'isCarousel': self.is_carousel,
            'sortOrder': self.sort_order, 'carouselSort': self.carousel_sort,
            'products': [p.to_dict() for p in self.products],
        }


class Article(db.Model):
    __tablename__ = 'articles'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    author = db.Column(db.String(50))
    content = db.Column(db.Text, nullable=False)
    cover_image = db.Column(db.String(500))
    is_published = db.Column(db.Boolean, default=False)
    published_at = db.Column('published_at', db.TIMESTAMP, nullable=True)
    sort_order = db.Column(db.Integer, default=0)
    created_at = db.Column('created_at', db.TIMESTAMP, default=datetime.now)
    updated_at = db.Column('updated_at', db.TIMESTAMP, default=datetime.now, onupdate=datetime.now)

    def to_dict(self):
        return {
            'id': self.id, 'title': self.title, 'author': self.author,
            'content': self.content, 'coverImage': self.cover_image,
            'isPublished': self.is_published, 'publishedAt': str(self.published_at) if self.published_at else None,
            'sortOrder': self.sort_order,
            'createdAt': str(self.created_at),
        }


class CompanyInfo(db.Model):
    __tablename__ = 'company_info'
    id = db.Column(db.Integer, primary_key=True)
    logo = db.Column(db.String(500))
    company_image = db.Column(db.String(500))
    name = db.Column(db.String(200))
    intro = db.Column(db.Text)
    phone = db.Column(db.String(20))
    wechat_qr = db.Column(db.String(500))
    wechat_id = db.Column(db.String(50))
    email = db.Column(db.String(100))
    address = db.Column(db.String(500))
    business_hours = db.Column(db.String(200))
    created_at = db.Column('created_at', db.TIMESTAMP, default=datetime.now)
    updated_at = db.Column('updated_at', db.TIMESTAMP, default=datetime.now, onupdate=datetime.now)

    def to_dict(self):
        return {
            'id': self.id, 'logo': self.logo, 'companyImage': self.company_image,
            'name': self.name, 'intro': self.intro,
            'phone': self.phone, 'wechatQr': self.wechat_qr, 'wechatId': self.wechat_id,
            'email': self.email, 'address': self.address, 'businessHours': self.business_hours,
        }


class Admin(db.Model):
    __tablename__ = 'admins'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), nullable=False, unique=True)
    passwd = db.Column(db.String(255), nullable=False)
    real_name = db.Column(db.String(50))
    role = db.Column(db.String(20), default='editor')
    is_active = db.Column(db.Boolean, default=True)
    last_login = db.Column('last_login', db.TIMESTAMP, nullable=True)
    created_at = db.Column('created_at', db.TIMESTAMP, default=datetime.now)
    updated_at = db.Column('updated_at', db.TIMESTAMP, default=datetime.now, onupdate=datetime.now)

    def to_dict(self):
        return {
            'id': self.id, 'username': self.username, 'realName': self.real_name,
            'role': self.role, 'isActive': self.is_active,
            'lastLogin': str(self.last_login) if self.last_login else None,
        }


class ProductImage(db.Model):
    __tablename__ = 'product_images'
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id', ondelete='CASCADE'), nullable=False)
    image_url = db.Column(db.String(500), nullable=False)
    sort_order = db.Column(db.Integer, default=0)
    is_primary = db.Column(db.Boolean, default=False)
    created_at = db.Column('created_at', db.TIMESTAMP, default=datetime.now)

    def to_dict(self):
        return {
            'id': self.id,
            'productId': self.product_id,
            'imageUrl': self.image_url,
            'sortOrder': self.sort_order,
            'isPrimary': self.is_primary,
        }
