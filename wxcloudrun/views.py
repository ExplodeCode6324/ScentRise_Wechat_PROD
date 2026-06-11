import json
from datetime import datetime
from flask import render_template, request
from wxcloudrun import app, db
from wxcloudrun.dao import (
    get_products, get_product_by_id, get_product_by_model,
    get_categories, get_or_create_category,
    get_tags, get_or_create_tag,
    get_collections, get_articles, get_article_by_id,
    get_company_info, get_admin_by_username,
)
from wxcloudrun.model import Product, Article, Category, CompanyInfo, Admin
from wxcloudrun.response import make_succ_empty_response, make_succ_response, make_err_response
from wxcloudrun.storage import upload as storage_upload
from wxcloudrun.storage import delete_files as storage_delete
from wxcloudrun.admin.auth import require_admin


@app.route('/')
def index():
    return render_template('index.html')


# ==================== 小程序 API ====================

@app.route('/api/products', methods=['GET'])
def api_products():
    category_id = request.args.get('category_id', type=int)
    tag_id = request.args.get('tag_id', type=int)
    keyword = request.args.get('keyword')
    page = request.args.get('page', 1, type=int)
    page_size = request.args.get('page_size', 20, type=int)
    products, total = get_products(category_id=category_id, tag_id=tag_id, keyword=keyword, page=page, page_size=page_size)
    return make_succ_response({'list': products, 'total': total, 'page': page, 'pageSize': page_size})


@app.route('/api/products/<int:product_id>', methods=['GET'])
def api_product_detail(product_id):
    product = get_product_by_id(product_id)
    if not product:
        return make_err_response('产品不存在')
    return make_succ_response(product.to_dict())


@app.route('/api/categories', methods=['GET'])
def api_categories():
    return make_succ_response(get_categories())


@app.route('/api/tags', methods=['GET'])
def api_tags():
    tag_category = request.args.get('category')
    return make_succ_response(get_tags(category=tag_category))


@app.route('/api/collections', methods=['GET'])
def api_collections():
    carousel_only = bool(request.args.get('carousel', type=int))
    return make_succ_response(get_collections(carousel_only=carousel_only))


@app.route('/api/articles', methods=['GET'])
def api_articles():
    page = request.args.get('page', 1, type=int)
    page_size = request.args.get('page_size', 10, type=int)
    articles, total = get_articles(page=page, page_size=page_size, published_only=True)
    return make_succ_response({'list': articles, 'total': total, 'page': page, 'pageSize': page_size})


@app.route('/api/articles/<int:article_id>', methods=['GET'])
def api_article_detail(article_id):
    article = get_article_by_id(article_id)
    if not article:
        return make_err_response('文章不存在')
    return make_succ_response(article.to_dict())


@app.route('/api/company', methods=['GET'])
def api_company_info():
    info = get_company_info()
    return make_succ_response(info.to_dict() if info else {})


# ==================== 后管 API ====================

@app.route('/api/admin/login', methods=['POST'])
def admin_login():
    data = request.get_json()
    admin = get_admin_by_username(data.get('username'))
    if not admin:
        return make_err_response('账号或密码错误')
    import bcrypt
    if not bcrypt.checkpw(data.get('password', '').encode(), admin.passwd.encode()):
        return make_err_response('账号或密码错误')
    admin.last_login = datetime.now()
    db.session.commit()
    from wxcloudrun.admin.auth import generate_token
    token = generate_token(admin.id, admin.username, admin.role or 'editor')
    return make_succ_response({'token': token, 'admin': admin.to_dict()})


@app.route('/api/admin/verify', methods=['GET'])
@require_admin
def admin_verify():
    """验证 token 有效性，返回当前管理员信息"""
    from flask import g
    return make_succ_response({
        'admin_id': g.admin_id,
        'username': g.admin_username,
        'role': g.admin_role,
    })


# --- 产品 CRUD ---

@app.route('/api/admin/products', methods=['POST'])
@require_admin
def admin_create_product():
    data = request.get_json()
    product = Product(
        product_series=data.get('productSeries'),
        product_name=data.get('productName'),
        product_model=data.get('productModel'),
        product_desc=data.get('productDesc'),
        product_image=data.get('productImage'),
        product_images=json.dumps(data.get('productImages', []), ensure_ascii=False),
        category_id=data.get('categoryId'),
    )
    db.session.add(product)
    # 关联标签
    if data.get('tagIds'):
        from wxcloudrun.model import Tag
        tags = Tag.query.filter(Tag.id.in_(data['tagIds'])).all()
        product.tags = tags
    db.session.commit()
    return make_succ_response(product.to_dict())


@app.route('/api/admin/products/<int:product_id>', methods=['PUT'])
@require_admin
def admin_update_product(product_id):
    product = get_product_by_id(product_id)
    if not product:
        return make_err_response('产品不存在')
    data = request.get_json()
    # 字段映射：前端 camelCase → 后端 snake_case
    _field_map = {
        'productSeries': 'product_series', 'productName': 'product_name',
        'productModel': 'product_model', 'productDesc': 'product_desc',
        'productImage': 'product_image', 'categoryId': 'category_id',
        'sortOrder': 'sort_order',
    }
    for js_field, py_field in _field_map.items():
        if js_field in data:
            setattr(product, py_field, data[js_field])
    if 'productImages' in data:
        product.product_images = json.dumps(data['productImages'], ensure_ascii=False)
    if 'isActive' in data:
        product.is_active = data['isActive']
    if 'tagIds' in data:
        from wxcloudrun.model import Tag
        product.tags = Tag.query.filter(Tag.id.in_(data['tagIds'])).all()
    db.session.commit()
    return make_succ_response(product.to_dict())


@app.route('/api/admin/products/<int:product_id>', methods=['DELETE'])
@require_admin
def admin_delete_product(product_id):
    product = get_product_by_id(product_id)
    if not product:
        return make_err_response('产品不存在')

    # 收集所有关联的云存储文件
    storage_urls = []
    if product.product_image:
        storage_urls.append(product.product_image)
    from wxcloudrun.model import ProductImage
    images = ProductImage.query.filter_by(product_id=product_id).all()
    for img in images:
        if img.image_url:
            storage_urls.append(img.image_url)

    # 先删云存储（失败不阻塞）
    if storage_urls:
        result = storage_delete(storage_urls)
        app.logger.info('Product %d: cleaned %d storage files', product_id, result.get('deleted', 0))

    db.session.delete(product)
    db.session.commit()
    return make_succ_empty_response()


# --- Excel 导入 ---

@app.route('/api/admin/import', methods=['POST'])
@require_admin
def admin_import_excel():
    """Excel 导入：遇新产品系列/标签自动创建，重复型号自动 UPDATE"""
    data = request.get_json()
    rows = data.get('rows', [])
    imported = {'created': 0, 'updated': 0, 'errors': []}

    for i, row in enumerate(rows):
        try:
            series_name = row.get('productSeries', '').strip()
            tag_names = row.get('tags', [])  # 前端传来的标签列表

            if not series_name or not row.get('productModel'):
                imported['errors'].append(f'第{i+2}行: 缺少产品系列或型号')
                continue

            # 自动创建/匹配产品系列（作为分类）
            cat = get_or_create_category(series_name)

            # 产品：按型号查重，存在则更新
            existing = get_product_by_model(row['productModel'])
            if existing:
                existing.product_name = row.get('productName', existing.product_name)
                existing.product_series = series_name
                existing.product_desc = row.get('productDesc')
                existing.category_id = cat.id
                imported['updated'] += 1
                product = existing
            else:
                product = Product(
                    product_series=series_name,
                    product_name=row.get('productName'),
                    product_model=row['productModel'],
                    product_desc=row.get('productDesc'),
                    category_id=cat.id,
                )
                db.session.add(product)
                db.session.flush()
                imported['created'] += 1

            # 标签关联：产品系列作为标签(category='产品系列',sortOrder=1)
            all_tags = []
            series_tag = get_or_create_tag(series_name, category='产品系列', sort_order=1)
            if series_tag:
                all_tags.append(series_tag)

            # 适用产品标签(category='适用产品',sortOrder=2)
            if tag_names:
                for name in tag_names:
                    name = name.strip()
                    if name and name != series_name:  # 去重：如果和系列同名只保留一个
                        t = get_or_create_tag(name, category='适用产品', sort_order=2)
                        if t:
                            all_tags.append(t)

            product.tags = all_tags

        except Exception as e:
            imported['errors'].append(f'第{i+2}行: {str(e)}')

    db.session.commit()
    return make_succ_response(imported)


# --- 文章管理 ---

@app.route('/api/admin/articles', methods=['POST'])
@require_admin
def admin_create_article():
    data = request.get_json()
    article = Article(
        title=data['title'], author=data.get('author'),
        content=data['content'], cover_image=data.get('coverImage'),
        is_published=data.get('isPublished', False),
        published_at=datetime.now() if data.get('isPublished') else None,
        sort_order=data.get('sortOrder', 0),
    )
    db.session.add(article)
    db.session.commit()
    return make_succ_response(article.to_dict())


@app.route('/api/admin/articles/<int:article_id>', methods=['PUT'])
@require_admin
def admin_update_article(article_id):
    article = get_article_by_id(article_id)
    if not article:
        return make_err_response('文章不存在')
    data = request.get_json()
    for field in ['title', 'author', 'content', 'cover_image', 'sort_order']:
        if field in data:
            setattr(article, field, data[field])
    if 'isPublished' in data:
        article.is_published = data['isPublished']
        if data['isPublished'] and not article.published_at:
            article.published_at = datetime.now()
    db.session.commit()
    return make_succ_response(article.to_dict())


@app.route('/api/admin/articles/<int:article_id>', methods=['DELETE'])
@require_admin
def admin_delete_article(article_id):
    article = get_article_by_id(article_id)
    if not article:
        return make_err_response('文章不存在')
    db.session.delete(article)
    db.session.commit()
    return make_succ_empty_response()


# --- 后管 产品列表/详情（分页、搜索） ---

@app.route('/api/admin/products', methods=['GET'])
@require_admin
def admin_get_products():
    category_id = request.args.get('category_id', type=int)
    keyword = request.args.get('keyword')
    page = request.args.get('page', 1, type=int)
    page_size = request.args.get('page_size', 20, type=int)
    products, total = get_products(category_id=category_id, keyword=keyword, page=page, page_size=page_size, include_inactive=True)
    return make_succ_response({'list': products, 'total': total, 'page': page, 'pageSize': page_size})


@app.route('/api/admin/products/<int:product_id>', methods=['GET'])
@require_admin
def admin_get_product(product_id):
    product = get_product_by_id(product_id)
    if not product:
        return make_err_response('产品不存在')
    from wxcloudrun.model import ProductImage
    images = ProductImage.query.filter_by(product_id=product_id).order_by(ProductImage.sort_order).all()
    data = product.to_dict()
    data['images'] = [img.to_dict() for img in images]
    return make_succ_response(data)


# --- 后管 产品图片上传 ---

@app.route('/api/admin/products/<int:product_id>/images', methods=['POST'])
@require_admin
def admin_upload_product_image(product_id):
    product = get_product_by_id(product_id)
    if not product:
        return make_err_response('产品不存在')
    from wxcloudrun.model import ProductImage
    image_type = request.form.get('image_type', 'detail')
    file = request.files.get('file')
    if not file:
        return make_err_response('请选择文件')
    # 生成云存储路径
    import time
    ext = file.filename.rsplit('.', 1)[-1] if '.' in file.filename else 'jpg'
    if image_type == 'main':
        cloud_path = 'product_image/{}/main.{}'.format(product_id, ext)
    else:
        cloud_path = 'product_image/{}/detail_{}.{}'.format(product_id, int(time.time()), ext)
    # 上传到云存储
    result = storage_upload(file.read(), cloud_path)
    if not result['success']:
        return make_err_response(result.get('error', '上传失败'))
    storage_url = result['url']
    if image_type == 'main':
        ProductImage.query.filter_by(product_id=product_id, is_primary=True).update({'is_primary': False})
        product.product_image = storage_url
    img = ProductImage(product_id=product_id, image_url=storage_url, is_primary=(image_type == 'main'))
    db.session.add(img)
    db.session.commit()
    return make_succ_response(img.to_dict())


@app.route('/api/admin/products/<int:product_id>/images/<int:image_id>', methods=['DELETE'])
@require_admin
def admin_delete_product_image(product_id, image_id):
    from wxcloudrun.model import ProductImage
    img = ProductImage.query.filter_by(id=image_id, product_id=product_id).first()
    if not img:
        return make_err_response('图片不存在')
    was_primary = img.is_primary
    db.session.delete(img)
    if was_primary:
        next_img = ProductImage.query.filter_by(product_id=product_id).order_by(ProductImage.sort_order).first()
        if next_img:
            next_img.is_primary = True
            from wxcloudrun.model import Product
            Product.query.filter_by(id=product_id).update({'product_image': next_img.image_url})
        else:
            from wxcloudrun.model import Product
            Product.query.filter_by(id=product_id).update({'product_image': None})
    db.session.commit()
    return make_succ_empty_response()


# --- 后管 标签 CRUD ---

@app.route('/api/admin/tags', methods=['GET'])
@require_admin
def admin_get_tags():
    category = request.args.get('category')
    page = request.args.get('page', 1, type=int)
    page_size = request.args.get('page_size', 20, type=int)
    tags, total = get_tags(category=category, page=page, page_size=page_size)
    return make_succ_response({'list': tags, 'total': total, 'page': page, 'pageSize': page_size})


@app.route('/api/admin/tags/<int:tag_id>', methods=['GET'])
@require_admin
def admin_get_tag(tag_id):
    from wxcloudrun.model import Tag
    tag = Tag.query.get(tag_id)
    if not tag:
        return make_err_response('标签不存在')
    return make_succ_response(tag.to_dict())


@app.route('/api/admin/tags', methods=['POST'])
@require_admin
def admin_create_tag():
    from wxcloudrun.model import Tag
    data = request.get_json()
    tag = Tag(name=data['name'], category=data.get('category', ''),
              sort_order=data.get('sortOrder', 0))
    db.session.add(tag)
    db.session.commit()
    return make_succ_response(tag.to_dict())


@app.route('/api/admin/tags/<int:tag_id>', methods=['PUT'])
@require_admin
def admin_update_tag(tag_id):
    from wxcloudrun.model import Tag
    tag = Tag.query.get(tag_id)
    if not tag:
        return make_err_response('标签不存在')
    data = request.get_json()
    for field in ['name', 'category', 'icon', 'banner_image', 'sort_order']:
        if field in data:
            setattr(tag, field, data[field])
    if 'sortOrder' in data:
        tag.sort_order = data['sortOrder']
    db.session.commit()
    return make_succ_response(tag.to_dict())


@app.route('/api/admin/tags/<int:tag_id>', methods=['DELETE'])
@require_admin
def admin_delete_tag(tag_id):
    from wxcloudrun.model import Tag
    tag = Tag.query.get(tag_id)
    if not tag:
        return make_err_response('标签不存在')
    db.session.delete(tag)
    db.session.commit()
    return make_succ_empty_response()


@app.route('/api/admin/tags/<int:tag_id>/image', methods=['POST'])
@require_admin
def admin_upload_tag_image(tag_id):
    from wxcloudrun.model import Tag
    tag = Tag.query.get(tag_id)
    if not tag:
        return make_err_response('标签不存在')
    image_type = request.form.get('type', 'icon')
    file = request.files.get('file')
    if not file:
        return make_err_response('请选择文件')
    ext = file.filename.rsplit('.', 1)[-1] if '.' in file.filename else 'png'
    if image_type == 'banner':
        cloud_path = 'label_image/{}/banner.{}'.format(tag_id, ext)
    else:
        cloud_path = 'label_icon/{}/icon.{}'.format(tag_id, ext)
    result = storage_upload(file.read(), cloud_path)
    if not result['success']:
        return make_err_response(result.get('error', '上传失败'))
    storage_url = result['url']
    if image_type == 'banner':
        tag.banner_image = storage_url
    else:
        tag.icon = storage_url
    db.session.commit()
    return make_succ_response({'url': storage_url})


# --- 后管 合集 CRUD ---

@app.route('/api/admin/collections', methods=['GET'])
@require_admin
def admin_get_collections():
    page = request.args.get('page', 1, type=int)
    page_size = request.args.get('page_size', 20, type=int)
    cols, total = get_collections(carousel_only=False, page=page, page_size=page_size)
    return make_succ_response({'list': cols, 'total': total, 'page': page, 'pageSize': page_size})


@app.route('/api/admin/collections/<int:col_id>', methods=['GET'])
@require_admin
def admin_get_collection(col_id):
    from wxcloudrun.model import Collection
    col = Collection.query.get(col_id)
    if not col:
        return make_err_response('合集不存在')
    return make_succ_response(col.to_dict())


@app.route('/api/admin/collections', methods=['POST'])
@require_admin
def admin_create_collection():
    from wxcloudrun.model import Collection
    data = request.get_json()
    col = Collection(name=data['name'], description=data.get('description', ''),
                     is_carousel=data.get('isCarousel', False),
                     carousel_sort=data.get('carouselSort', 0),
                     sort_order=data.get('sortOrder', 0))
    db.session.add(col)
    db.session.commit()
    return make_succ_response(col.to_dict())


@app.route('/api/admin/collections/<int:col_id>', methods=['PUT'])
@require_admin
def admin_update_collection(col_id):
    from wxcloudrun.model import Collection
    col = Collection.query.get(col_id)
    if not col:
        return make_err_response('合集不存在')
    data = request.get_json()
    for field in ['name', 'description', 'cover_image', 'is_carousel', 'carousel_sort', 'sort_order']:
        if field in data:
            setattr(col, field, data[field])
    if 'isCarousel' in data:
        col.is_carousel = data['isCarousel']
    if 'carouselSort' in data:
        col.carousel_sort = data['carouselSort']
    if 'sortOrder' in data:
        col.sort_order = data['sortOrder']
    db.session.commit()
    return make_succ_response(col.to_dict())


@app.route('/api/admin/collections/<int:col_id>', methods=['DELETE'])
@require_admin
def admin_delete_collection(col_id):
    from wxcloudrun.model import Collection
    col = Collection.query.get(col_id)
    if not col:
        return make_err_response('合集不存在')
    db.session.delete(col)
    db.session.commit()
    return make_succ_empty_response()


@app.route('/api/admin/collections/<int:col_id>/products', methods=['GET'])
@require_admin
def admin_get_collection_products(col_id):
    """获取合集已关联的产品列表 + 全部可选产品"""
    from wxcloudrun.model import Collection, collection_products
    col = Collection.query.get(col_id)
    if not col:
        return make_err_response('合集不存在')
    # 合集已关联产品（按 sort_order 排序）
    linked = db.session.query(Product, collection_products.c.sort_order)\
        .join(collection_products, Product.id == collection_products.c.product_id)\
        .filter(collection_products.c.collection_id == col_id)\
        .order_by(collection_products.c.sort_order)\
        .all()
    linked_products = []
    for p, so in linked:
        d = p.to_dict()
        d['_sortOrder'] = so
        linked_products.append(d)
    # 全部产品（供选择）
    all_products, _ = get_products(page=1, page_size=9999, include_inactive=True)
    return make_succ_response({
        'collection': col.to_dict(),
        'linkedProducts': linked_products,
        'allProducts': all_products,
    })


@app.route('/api/admin/collections/<int:col_id>/products', methods=['PUT'])
@require_admin
def admin_update_collection_products(col_id):
    from wxcloudrun.model import Collection, collection_products
    col = Collection.query.get(col_id)
    if not col:
        return make_err_response('合集不存在')
    data = request.get_json()
    product_ids = data.get('product_ids', [])
    # 清空旧关联
    db.session.execute(collection_products.delete().where(collection_products.c.collection_id == col_id))
    # 插入新关联
    for i, pid in enumerate(product_ids):
        db.session.execute(collection_products.insert().values(collection_id=col_id, product_id=pid, sort_order=i))
    db.session.commit()
    return make_succ_response(col.to_dict())


@app.route('/api/admin/collections/<int:col_id>/image', methods=['POST'])
@require_admin
def admin_upload_collection_image(col_id):
    from wxcloudrun.model import Collection
    col = Collection.query.get(col_id)
    if not col:
        return make_err_response('合集不存在')
    file = request.files.get('file')
    if not file:
        return make_err_response('请选择文件')
    ext = file.filename.rsplit('.', 1)[-1] if '.' in file.filename else 'jpg'
    cloud_path = 'collection_image/{}/cover.{}'.format(col_id, ext)
    result = storage_upload(file.read(), cloud_path)
    if not result['success']:
        return make_err_response(result.get('error', '上传失败'))
    storage_url = result['url']
    col.cover_image = storage_url
    db.session.commit()
    return make_succ_response({'url': storage_url})


# --- 后管 文章列表（含草稿） ---

@app.route('/api/admin/articles', methods=['GET'])
@require_admin
def admin_get_articles():
    page = request.args.get('page', 1, type=int)
    page_size = request.args.get('page_size', 20, type=int)
    status = request.args.get('status', 'all')
    published_only = True if status == 'published' else (False if status == 'draft' else None)
    articles, total = get_articles(page=page, page_size=page_size, published_only=published_only)
    return make_succ_response({'list': articles, 'total': total, 'page': page, 'pageSize': page_size})


@app.route('/api/admin/articles/<int:article_id>', methods=['GET'])
@require_admin
def admin_get_article(article_id):
    article = get_article_by_id(article_id)
    if not article:
        return make_err_response('文章不存在')
    return make_succ_response(article.to_dict())


@app.route('/api/admin/articles/<int:article_id>/image', methods=['POST'])
@require_admin
def admin_upload_article_image(article_id):
    article = get_article_by_id(article_id)
    if not article:
        return make_err_response('文章不存在')
    file = request.files.get('file')
    if not file:
        return make_err_response('请选择文件')
    ext = file.filename.rsplit('.', 1)[-1] if '.' in file.filename else 'jpg'
    cloud_path = 'article_image/{}/cover.{}'.format(article_id, ext)
    result = storage_upload(file.read(), cloud_path)
    if not result['success']:
        return make_err_response(result.get('error', '上传失败'))
    storage_url = result['url']
    article.cover_image = storage_url
    db.session.commit()
    return make_succ_response({'url': storage_url})


# --- 后管 公司信息 ---


def _get_or_create_company_info():
    """获取或创建 CompanyInfo 记录；新建时 flush 以获取自增 id"""
    from wxcloudrun.model import CompanyInfo
    info = CompanyInfo.query.first()
    if not info:
        info = CompanyInfo()
        db.session.add(info)
        db.session.flush()
    return info


@app.route('/api/admin/company', methods=['GET'])
@require_admin
def admin_get_company():
    from wxcloudrun.model import CompanyInfo
    info = CompanyInfo.query.first()
    return make_succ_response(info.to_dict() if info else {})


@app.route('/api/admin/company', methods=['PUT'])
@require_admin
def admin_update_company():
    from wxcloudrun.model import CompanyInfo
    data = request.get_json()
    info = CompanyInfo.query.first()
    if not info:
        info = CompanyInfo()
        db.session.add(info)
    for field in ['name', 'intro', 'phone', 'wechat_id', 'email', 'address', 'business_hours', 'company_image']:
        if field in data:
            setattr(info, field, data[field])
    if 'wechatId' in data:
        info.wechat_id = data['wechatId']
    if 'businessHours' in data:
        info.business_hours = data['businessHours']
    if 'companyImage' in data:
        info.company_image = data['companyImage']
    db.session.commit()
    return make_succ_response(info.to_dict())


@app.route('/api/admin/company/logo', methods=['POST'])
@require_admin
def admin_upload_company_logo():
    file = request.files.get('file')
    if not file:
        return make_err_response('请选择文件')
    info = _get_or_create_company_info()
    ext = file.filename.rsplit('.', 1)[-1] if '.' in file.filename else 'png'
    cloud_path = 'company/{}/logo.{}'.format(info.id, ext)
    result = storage_upload(file.read(), cloud_path)
    if not result['success']:
        return make_err_response(result.get('error', '上传失败'))
    storage_url = result['url']
    info.logo = storage_url
    db.session.commit()
    return make_succ_response({'url': storage_url, 'id': info.id})


@app.route('/api/admin/company/qr', methods=['POST'])
@require_admin
def admin_upload_company_qr():
    file = request.files.get('file')
    if not file:
        return make_err_response('请选择文件')
    info = _get_or_create_company_info()
    ext = file.filename.rsplit('.', 1)[-1] if '.' in file.filename else 'png'
    cloud_path = 'company/{}/wechat_qr.{}'.format(info.id, ext)
    result = storage_upload(file.read(), cloud_path)
    if not result['success']:
        return make_err_response(result.get('error', '上传失败'))
    storage_url = result['url']
    info.wechat_qr = storage_url
    db.session.commit()
    return make_succ_response({'url': storage_url, 'id': info.id})


@app.route('/api/admin/company/image', methods=['POST'])
@require_admin
def admin_upload_company_image():
    file = request.files.get('file')
    if not file:
        return make_err_response('请选择文件')
    info = _get_or_create_company_info()
    ext = file.filename.rsplit('.', 1)[-1] if '.' in file.filename else 'png'
    cloud_path = 'company/{}/image.{}'.format(info.id, ext)
    result = storage_upload(file.read(), cloud_path)
    if not result['success']:
        return make_err_response(result.get('error', '上传失败'))
    storage_url = result['url']
    info.company_image = storage_url
    db.session.commit()
    return make_succ_response({'url': storage_url, 'id': info.id})
