"""Public mini-program API and authenticated administration API."""

from __future__ import annotations

import json
import threading
import time
import uuid
from collections import defaultdict, deque
from datetime import datetime

import bcrypt
from flask import g, render_template, request
from sqlalchemy.exc import IntegrityError

from wxcloudrun import app, db
from wxcloudrun.admin.auth import generate_token, require_admin, require_roles
from wxcloudrun.dao import (
    get_article_by_id,
    get_articles,
    get_categories,
    get_collections,
    get_company_info,
    get_product_by_id,
    get_products,
    get_tags,
)
from wxcloudrun.importer import ImportRejected, execute_import, preflight_import
from wxcloudrun.model import (
    Admin,
    Article,
    Category,
    Collection,
    CompanyInfo,
    Product,
    ProductImage,
    Tag,
    collection_products,
)
from wxcloudrun.response import make_err_response, make_succ_empty_response, make_succ_response
from wxcloudrun.storage import delete_files as storage_delete
from wxcloudrun.storage import upload as storage_upload
from wxcloudrun.validation import (
    ValidationError,
    clean_int,
    clean_text,
    pagination_args,
    sanitize_rich_text,
    validate_image_upload,
)

_login_attempts = defaultdict(deque)
_login_lock = threading.Lock()
_dummy_password_hash = bcrypt.hashpw(b"invalid-password", bcrypt.gensalt(rounds=12))
_ROLE_EDITOR = ("admin", "editor")


@app.errorhandler(ValidationError)
def handle_validation_error(error):
    db.session.rollback()
    return make_err_response(str(error), 422, error_code="validation_error")


@app.errorhandler(IntegrityError)
def handle_integrity_error(error):
    db.session.rollback()
    app.logger.info("database constraint rejected request: %s", error.orig)
    return make_err_response("数据冲突，请检查名称、型号等唯一字段", 409, error_code="conflict")


def _json_body():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ValidationError("请求体必须是JSON对象")
    return data


def _bool(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off", ""}:
        return False
    raise ValidationError("布尔字段格式不正确")


def _id_list(value, field, *, max_items=5000):
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValidationError(f"{field}必须是数组")
    if len(value) > max_items:
        raise ValidationError(f"{field}最多包含{max_items}项")
    result = []
    for item in value:
        item_id = clean_int(item, field, minimum=1)
        if item_id not in result:
            result.append(item_id)
    return result


def _all_product_urls(product):
    urls = [product.product_image]
    if product.product_images:
        try:
            parsed = json.loads(product.product_images)
            if isinstance(parsed, list):
                urls.extend(value for value in parsed if isinstance(value, str))
        except (TypeError, ValueError, json.JSONDecodeError):
            pass
    urls.extend(
        image.image_url for image in ProductImage.query.filter_by(product_id=product.id).all()
    )
    return list(dict.fromkeys(filter(None, urls)))


def _upload_image(file_storage, folder):
    data, extension, content_type = validate_image_upload(
        file_storage, max_bytes=app.config["MAX_IMAGE_BYTES"]
    )
    cloud_path = f"{folder}/{uuid.uuid4().hex}.{extension}"
    result = storage_upload(data, cloud_path, content_type)
    if not result.get("success"):
        raise ValidationError(result.get("error", "图片上传失败"))
    return result


def _replace_storage_url(record, attribute, result):
    old_url = getattr(record, attribute, None)
    setattr(record, attribute, result["url"])
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        storage_delete([result["url"]])
        raise
    if old_url and old_url != result["url"]:
        storage_delete([old_url])


def _login_key(username):
    return f"{request.remote_addr or 'unknown'}:{username}"


def _is_login_limited(key):
    now = time.monotonic()
    with _login_lock:
        attempts = _login_attempts[key]
        while attempts and attempts[0] < now - 900:
            attempts.popleft()
        return len(attempts) >= 5


def _record_login_failure(key):
    with _login_lock:
        _login_attempts[key].append(time.monotonic())


def _clear_login_failures(key):
    with _login_lock:
        _login_attempts.pop(key, None)


def _product_collections(product_id):
    rows = db.session.execute(
        db.select(collection_products.c.collection_id).where(
            collection_products.c.product_id == product_id
        )
    ).all()
    return [row[0] for row in rows]


def _apply_collection_ids(product_id, collection_ids):
    collections = (
        Collection.query.filter(Collection.id.in_(collection_ids)).all() if collection_ids else []
    )
    if len(collections) != len(collection_ids):
        raise ValidationError("合集ID中包含不存在的记录")
    db.session.execute(
        collection_products.delete().where(collection_products.c.product_id == product_id)
    )
    for collection_id in collection_ids:
        db.session.execute(
            collection_products.insert().values(
                collection_id=collection_id,
                product_id=product_id,
                sort_order=0,
            )
        )


def _apply_product_payload(product, data, *, creating=False):
    category_id = clean_int(data.get("categoryId", product.category_id), "产品系列", minimum=1)
    category = db.session.get(Category, category_id)
    if not category:
        raise ValidationError("产品系列不存在")
    product.product_name = clean_text(
        data.get("productName", product.product_name), "产品名称", required=True, max_length=200
    )
    product.product_model = clean_text(
        data.get("productModel", product.product_model), "产品型号", required=True, max_length=100
    )
    product.product_english_name = clean_text(
        data.get("productEnglishName", product.product_english_name), "英文名称", max_length=200
    )
    product.product_desc = clean_text(
        data.get("productDesc", product.product_desc), "产品描述", max_length=200_000
    )
    product.category = category
    product.product_series = category.name
    product.sort_order = clean_int(data.get("sortOrder", product.sort_order), "排序", default=0)
    product.is_active = _bool(data.get("isActive"), True if creating else product.is_active)
    with db.session.no_autoflush:
        duplicate = Product.query.filter(
            Product.product_model == product.product_model, Product.id != (product.id or 0)
        ).first()
    if duplicate:
        raise ValidationError(f"产品型号“{product.product_model}”已存在")
    if "productImages" in data:
        images = data["productImages"]
        if not isinstance(images, list) or len(images) > 100:
            raise ValidationError("产品图片列表格式不正确或数量超过100")
        product.product_images = json.dumps(
            [clean_text(url, "图片地址", max_length=500) for url in images], ensure_ascii=False
        )
    if "productImage" in data:
        product.product_image = clean_text(data["productImage"], "主图地址", max_length=500) or None
    if "tagIds" in data or creating:
        tag_ids = _id_list(data.get("tagIds", []), "标签ID", max_items=100)
        requested_tags = Tag.query.filter(Tag.id.in_(tag_ids)).all() if tag_ids else []
        if len(requested_tags) != len(tag_ids):
            raise ValidationError("标签ID中包含不存在的记录")
        requested_tags = [tag for tag in requested_tags if tag.category != "产品系列"]
        series_tag = Tag.query.filter_by(name=category.name).first()
        if series_tag and series_tag.category != "产品系列":
            raise ValidationError(f"标签“{category.name}”已被用于其它分类")
        if not series_tag:
            series_tag = Tag(name=category.name, category="产品系列", sort_order=1)
            db.session.add(series_tag)
        product.tags = [series_tag, *requested_tags]


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/healthz")
def healthz():
    return make_succ_response({"status": "ok"})


@app.route("/readyz")
def readyz():
    db.session.execute(db.select(1))
    return make_succ_response({"status": "ready"})


@app.route("/api/products", methods=["GET"])
def api_products():
    page, page_size = pagination_args(request.args)
    products, total = get_products(
        category_id=request.args.get("category_id", type=int),
        tag_id=request.args.get("tag_id", type=int),
        keyword=clean_text(request.args.get("keyword"), "关键词", max_length=100),
        page=page,
        page_size=page_size,
    )
    return make_succ_response(
        {"list": products, "total": total, "page": page, "pageSize": page_size}
    )


@app.route("/api/products/<int:product_id>", methods=["GET"])
def api_product_detail(product_id):
    product = get_product_by_id(product_id, include_inactive=False)
    return (
        make_succ_response(product.to_dict()) if product else make_err_response("产品不存在", 404)
    )


@app.route("/api/categories", methods=["GET"])
def api_categories():
    return make_succ_response(get_categories())


@app.route("/api/tags", methods=["GET"])
def api_tags():
    category = clean_text(request.args.get("category"), "标签分类", max_length=50)
    return make_succ_response(get_tags(category=category or None))


@app.route("/api/collections", methods=["GET"])
def api_collections():
    return make_succ_response(
        get_collections(carousel_only=_bool(request.args.get("carousel"), False))
    )


@app.route("/api/collections/<int:collection_id>", methods=["GET"])
def api_collection_detail(collection_id):
    collection = db.session.get(Collection, collection_id)
    return (
        make_succ_response(collection.to_dict())
        if collection
        else make_err_response("合集不存在", 404)
    )


@app.route("/api/articles", methods=["GET"])
def api_articles():
    page, page_size = pagination_args(request.args, default_size=10)
    articles, total = get_articles(page=page, page_size=page_size, published_only=True)
    return make_succ_response(
        {"list": articles, "total": total, "page": page, "pageSize": page_size}
    )


@app.route("/api/articles/<int:article_id>", methods=["GET"])
def api_article_detail(article_id):
    article = get_article_by_id(article_id, published_only=True)
    return (
        make_succ_response(article.to_dict()) if article else make_err_response("文章不存在", 404)
    )


@app.route("/api/company", methods=["GET"])
def api_company_info():
    info = get_company_info()
    return make_succ_response(info.to_dict() if info else {})


@app.route("/api/admin/login", methods=["POST"])
def admin_login():
    data = _json_body()
    username = clean_text(data.get("username"), "账号", required=True, max_length=50)
    password = clean_text(data.get("password"), "密码", required=True, max_length=200)
    key = _login_key(username)
    if _is_login_limited(key):
        return make_err_response("登录失败次数过多，请15分钟后再试", 429)
    admin = Admin.query.filter_by(username=username, is_active=True).first()
    password_hash = admin.passwd.encode("utf-8") if admin else _dummy_password_hash
    valid = bcrypt.checkpw(password.encode("utf-8"), password_hash)
    if not admin or not valid:
        _record_login_failure(key)
        return make_err_response("账号或密码错误", 401)
    _clear_login_failures(key)
    admin.last_login = datetime.now()
    db.session.commit()
    token = generate_token(admin.id, admin.username, admin.role or "editor")
    response = make_succ_response({"admin": admin.to_dict()})
    response.set_cookie(
        "admin_session",
        token,
        httponly=True,
        secure=not app.config["TESTING"],
        samesite="Strict",
        max_age=app.config["JWT_EXP_HOURS"] * 3600,
        path="/",
    )
    return response


@app.route("/api/admin/logout", methods=["POST"])
def admin_logout():
    response = make_succ_empty_response()
    response.delete_cookie("admin_session", path="/", samesite="Strict")
    return response


@app.route("/api/admin/verify", methods=["GET"])
@require_admin
def admin_verify():
    return make_succ_response(g.admin.to_dict())


@app.route("/api/admin/password", methods=["PUT"])
@require_admin
def admin_change_password():
    data = _json_body()
    current_password = clean_text(
        data.get("currentPassword"), "当前密码", required=True, max_length=200
    )
    new_password = clean_text(data.get("newPassword"), "新密码", required=True, max_length=72)
    if len(new_password) < 12:
        raise ValidationError("新密码至少12个字符")
    if not bcrypt.checkpw(current_password.encode(), g.admin.passwd.encode()):
        return make_err_response("当前密码错误", 401)
    g.admin.passwd = bcrypt.hashpw(new_password.encode(), bcrypt.gensalt()).decode()
    g.admin.updated_at = datetime.now()
    db.session.commit()
    response = make_succ_empty_response()
    response.delete_cookie("admin_session", path="/", samesite="Strict")
    return response


@app.route("/api/admin/products", methods=["GET"])
@require_admin
def admin_get_products():
    page, page_size = pagination_args(request.args)
    products, total = get_products(
        category_id=request.args.get("category_id", type=int),
        keyword=clean_text(request.args.get("keyword"), "关键词", max_length=100),
        page=page,
        page_size=page_size,
        include_inactive=True,
    )
    return make_succ_response(
        {"list": products, "total": total, "page": page, "pageSize": page_size}
    )


@app.route("/api/admin/products/<int:product_id>", methods=["GET"])
@require_admin
def admin_get_product(product_id):
    product = get_product_by_id(product_id)
    if not product:
        return make_err_response("产品不存在", 404)
    data = product.to_dict()
    data["images"] = [
        image.to_dict()
        for image in ProductImage.query.filter_by(product_id=product_id)
        .order_by(ProductImage.sort_order)
        .all()
    ]
    data["collectionIds"] = _product_collections(product_id)
    return make_succ_response(data)


@app.route("/api/admin/products", methods=["POST"])
@require_roles(*_ROLE_EDITOR)
def admin_create_product():
    data = _json_body()
    product = Product(is_active=True, sort_order=0)
    db.session.add(product)
    _apply_product_payload(product, data, creating=True)
    db.session.flush()
    if "collectionIds" in data:
        _apply_collection_ids(product.id, _id_list(data["collectionIds"], "合集ID"))
    db.session.commit()
    return make_succ_response(product.to_dict(), 201)


@app.route("/api/admin/products/<int:product_id>", methods=["PUT"])
@require_roles(*_ROLE_EDITOR)
def admin_update_product(product_id):
    product = get_product_by_id(product_id)
    if not product:
        return make_err_response("产品不存在", 404)
    data = _json_body()
    _apply_product_payload(product, data)
    if "collectionIds" in data:
        _apply_collection_ids(product.id, _id_list(data["collectionIds"], "合集ID"))
    db.session.commit()
    return make_succ_response(product.to_dict())


@app.route("/api/admin/products/<int:product_id>", methods=["DELETE"])
@require_roles("admin")
def admin_delete_product(product_id):
    product = get_product_by_id(product_id)
    if not product:
        return make_err_response("产品不存在", 404)
    urls = _all_product_urls(product)
    db.session.delete(product)
    db.session.commit()
    storage_delete(urls)
    return make_succ_empty_response()


@app.route("/api/admin/import/preflight", methods=["POST"])
@require_roles("admin")
def admin_import_preflight():
    data = _json_body()
    result = preflight_import(
        data.get("rows"), data.get("options"), max_rows=app.config["MAX_IMPORT_ROWS"]
    )
    return make_succ_response(
        {key: value for key, value in result.items() if not key.startswith("_")}
    )


@app.route("/api/admin/import", methods=["POST"])
@require_roles("admin")
def admin_import_excel():
    data = _json_body()
    try:
        result = execute_import(
            data.get("rows"),
            data.get("options"),
            data.get("planHash"),
            confirm_warnings=_bool(data.get("confirmWarnings"), False),
            max_rows=app.config["MAX_IMPORT_ROWS"],
        )
    except ImportRejected as error:
        db.session.rollback()
        return make_err_response(
            str(error), error.status, details=error.preflight, error_code="import_rejected"
        )
    return make_succ_response(result)


@app.route("/api/admin/products/<int:product_id>/images", methods=["POST"])
@require_roles(*_ROLE_EDITOR)
def admin_upload_product_image(product_id):
    product = get_product_by_id(product_id)
    if not product:
        return make_err_response("产品不存在", 404)
    image_type = request.form.get("image_type", "detail")
    if image_type not in {"main", "detail"}:
        raise ValidationError("图片类型只能是main或detail")
    result = _upload_image(request.files.get("file"), f"product_image/{product_id}")
    image = ProductImage(
        product_id=product_id,
        image_url=result["url"],
        is_primary=image_type == "main",
        sort_order=ProductImage.query.filter_by(product_id=product_id).count(),
    )
    old_main = None
    if image_type == "main":
        old_main = product.product_image
        ProductImage.query.filter_by(product_id=product_id, is_primary=True).update(
            {"is_primary": False}
        )
        product.product_image = result["url"]
    db.session.add(image)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        storage_delete([result["url"]])
        raise
    if old_main and old_main != result["url"]:
        storage_delete([old_main])
    return make_succ_response(image.to_dict(), 201)


@app.route("/api/admin/products/<int:product_id>/images/<int:image_id>", methods=["DELETE"])
@require_roles(*_ROLE_EDITOR)
def admin_delete_product_image(product_id, image_id):
    image = ProductImage.query.filter_by(id=image_id, product_id=product_id).first()
    if not image:
        return make_err_response("图片不存在", 404)
    image_url, was_primary = image.image_url, image.is_primary
    db.session.delete(image)
    db.session.flush()
    if was_primary:
        next_image = (
            ProductImage.query.filter_by(product_id=product_id)
            .order_by(ProductImage.sort_order)
            .first()
        )
        product = db.session.get(Product, product_id)
        if product:
            product.product_image = next_image.image_url if next_image else None
        if next_image:
            next_image.is_primary = True
    db.session.commit()
    storage_delete([image_url])
    return make_succ_empty_response()


@app.route("/api/admin/tags", methods=["GET"])
@require_admin
def admin_get_tags():
    page, page_size = pagination_args(request.args)
    category = clean_text(request.args.get("category"), "标签分类", max_length=50)
    tags, total = get_tags(category=category or None, page=page, page_size=page_size)
    return make_succ_response({"list": tags, "total": total, "page": page, "pageSize": page_size})


@app.route("/api/admin/tags/<int:tag_id>", methods=["GET"])
@require_admin
def admin_get_tag(tag_id):
    tag = db.session.get(Tag, tag_id)
    return make_succ_response(tag.to_dict()) if tag else make_err_response("标签不存在", 404)


def _apply_tag_payload(tag, data):
    tag.name = clean_text(data.get("name", tag.name), "标签名称", required=True, max_length=50)
    tag.category = clean_text(
        data.get("category", tag.category), "标签分类", required=True, max_length=50
    )
    tag.sort_order = clean_int(data.get("sortOrder", tag.sort_order), "排序", default=0)
    if "icon" in data:
        tag.icon = clean_text(data["icon"], "图标地址", max_length=500) or None
    if "bannerImage" in data:
        tag.banner_image = clean_text(data["bannerImage"], "横幅地址", max_length=500) or None


@app.route("/api/admin/tags", methods=["POST"])
@require_roles(*_ROLE_EDITOR)
def admin_create_tag():
    tag = Tag(sort_order=0)
    _apply_tag_payload(tag, _json_body())
    db.session.add(tag)
    db.session.commit()
    return make_succ_response(tag.to_dict(), 201)


@app.route("/api/admin/tags/<int:tag_id>", methods=["PUT"])
@require_roles(*_ROLE_EDITOR)
def admin_update_tag(tag_id):
    tag = db.session.get(Tag, tag_id)
    if not tag:
        return make_err_response("标签不存在", 404)
    _apply_tag_payload(tag, _json_body())
    db.session.commit()
    return make_succ_response(tag.to_dict())


@app.route("/api/admin/tags/<int:tag_id>", methods=["DELETE"])
@require_roles("admin")
def admin_delete_tag(tag_id):
    tag = db.session.get(Tag, tag_id)
    if not tag:
        return make_err_response("标签不存在", 404)
    if tag.products.count():
        return make_err_response("标签仍被产品使用，不能删除", 409)
    urls = [tag.icon, tag.banner_image]
    db.session.delete(tag)
    db.session.commit()
    storage_delete(urls)
    return make_succ_empty_response()


@app.route("/api/admin/tags/<int:tag_id>/image", methods=["POST"])
@require_roles(*_ROLE_EDITOR)
def admin_upload_tag_image(tag_id):
    tag = db.session.get(Tag, tag_id)
    if not tag:
        return make_err_response("标签不存在", 404)
    image_type = request.form.get("type", "icon")
    if image_type not in {"icon", "banner"}:
        raise ValidationError("图片类型只能是icon或banner")
    result = _upload_image(request.files.get("file"), f"label_image/{tag_id}/{image_type}")
    _replace_storage_url(tag, "banner_image" if image_type == "banner" else "icon", result)
    return make_succ_response({"url": result["url"]})


@app.route("/api/admin/collections", methods=["GET"])
@require_admin
def admin_get_collections():
    page, page_size = pagination_args(request.args)
    collections, total = get_collections(
        page=page, page_size=page_size, include_inactive_products=True
    )
    return make_succ_response(
        {"list": collections, "total": total, "page": page, "pageSize": page_size}
    )


@app.route("/api/admin/collections/<int:collection_id>", methods=["GET"])
@require_admin
def admin_get_collection(collection_id):
    collection = db.session.get(Collection, collection_id)
    return (
        make_succ_response(collection.to_dict(include_inactive_products=True))
        if collection
        else make_err_response("合集不存在", 404)
    )


def _apply_collection_payload(collection, data):
    collection.name = clean_text(
        data.get("name", collection.name), "合集名称", required=True, max_length=100
    )
    collection.description = clean_text(
        data.get("description", collection.description), "合集描述", max_length=200_000
    )
    collection.is_carousel = _bool(data.get("isCarousel"), collection.is_carousel)
    collection.carousel_sort = clean_int(
        data.get("carouselSort", collection.carousel_sort), "轮播排序", default=0
    )
    collection.sort_order = clean_int(
        data.get("sortOrder", collection.sort_order), "排序", default=0
    )
    if "coverImage" in data:
        collection.cover_image = clean_text(data["coverImage"], "封面地址", max_length=500) or None


@app.route("/api/admin/collections", methods=["POST"])
@require_roles(*_ROLE_EDITOR)
def admin_create_collection():
    collection = Collection(is_carousel=False, carousel_sort=0, sort_order=0)
    _apply_collection_payload(collection, _json_body())
    db.session.add(collection)
    db.session.commit()
    return make_succ_response(collection.to_dict(include_inactive_products=True), 201)


@app.route("/api/admin/collections/<int:collection_id>", methods=["PUT"])
@require_roles(*_ROLE_EDITOR)
def admin_update_collection(collection_id):
    collection = db.session.get(Collection, collection_id)
    if not collection:
        return make_err_response("合集不存在", 404)
    _apply_collection_payload(collection, _json_body())
    db.session.commit()
    return make_succ_response(collection.to_dict(include_inactive_products=True))


@app.route("/api/admin/collections/<int:collection_id>", methods=["DELETE"])
@require_roles("admin")
def admin_delete_collection(collection_id):
    collection = db.session.get(Collection, collection_id)
    if not collection:
        return make_err_response("合集不存在", 404)
    cover_url = collection.cover_image
    db.session.delete(collection)
    db.session.commit()
    storage_delete([cover_url])
    return make_succ_empty_response()


@app.route("/api/admin/collections/<int:collection_id>/products", methods=["GET"])
@require_admin
def admin_get_collection_products(collection_id):
    collection = db.session.get(Collection, collection_id)
    if not collection:
        return make_err_response("合集不存在", 404)
    linked = (
        db.session.query(Product, collection_products.c.sort_order)
        .join(collection_products, Product.id == collection_products.c.product_id)
        .filter(collection_products.c.collection_id == collection_id)
        .order_by(collection_products.c.sort_order)
        .all()
    )
    linked_products = []
    for product, sort_order in linked:
        value = product.to_dict()
        value["_sortOrder"] = sort_order
        linked_products.append(value)
    all_products, _ = get_products(page=1, page_size=5000, include_inactive=True)
    return make_succ_response(
        {
            "collection": collection.to_dict(include_inactive_products=True),
            "linkedProducts": linked_products,
            "allProducts": all_products,
        }
    )


@app.route("/api/admin/collections/<int:collection_id>/products", methods=["PUT"])
@require_roles(*_ROLE_EDITOR)
def admin_update_collection_products(collection_id):
    collection = db.session.get(Collection, collection_id)
    if not collection:
        return make_err_response("合集不存在", 404)
    data = _json_body()
    product_ids = _id_list(data.get("product_ids", data.get("productIds", [])), "产品ID")
    existing = Product.query.filter(Product.id.in_(product_ids)).count() if product_ids else 0
    if existing != len(product_ids):
        raise ValidationError("产品ID中包含不存在的记录")
    db.session.execute(
        collection_products.delete().where(collection_products.c.collection_id == collection_id)
    )
    for sort_order, product_id in enumerate(product_ids):
        db.session.execute(
            collection_products.insert().values(
                collection_id=collection_id,
                product_id=product_id,
                sort_order=sort_order,
            )
        )
    db.session.commit()
    return make_succ_response(collection.to_dict(include_inactive_products=True))


@app.route("/api/admin/collections/<int:collection_id>/image", methods=["POST"])
@require_roles(*_ROLE_EDITOR)
def admin_upload_collection_image(collection_id):
    collection = db.session.get(Collection, collection_id)
    if not collection:
        return make_err_response("合集不存在", 404)
    result = _upload_image(request.files.get("file"), f"collection_image/{collection_id}")
    _replace_storage_url(collection, "cover_image", result)
    return make_succ_response({"url": result["url"]})


@app.route("/api/admin/articles", methods=["GET"])
@require_admin
def admin_get_articles():
    page, page_size = pagination_args(request.args)
    status = request.args.get("status", "all")
    if status not in {"all", "published", "draft"}:
        raise ValidationError("status只能是all、published或draft")
    published_only = True if status == "published" else False if status == "draft" else None
    articles, total = get_articles(page=page, page_size=page_size, published_only=published_only)
    return make_succ_response(
        {"list": articles, "total": total, "page": page, "pageSize": page_size}
    )


@app.route("/api/admin/articles/<int:article_id>", methods=["GET"])
@require_admin
def admin_get_article(article_id):
    article = get_article_by_id(article_id)
    return (
        make_succ_response(article.to_dict()) if article else make_err_response("文章不存在", 404)
    )


def _apply_article_payload(article, data, *, creating=False):
    article.title = clean_text(
        data.get("title", article.title), "文章标题", required=True, max_length=200
    )
    article.author = clean_text(data.get("author", article.author), "作者", max_length=50)
    if "content" in data or creating:
        article.content = sanitize_rich_text(data.get("content", article.content))
    article.sort_order = clean_int(data.get("sortOrder", article.sort_order), "排序", default=0)
    if "coverImage" in data:
        article.cover_image = clean_text(data["coverImage"], "封面地址", max_length=500) or None
    if "isPublished" in data or creating:
        published = _bool(data.get("isPublished"), False)
        if published and not article.is_published:
            article.published_at = datetime.now()
        if not published:
            article.published_at = None
        article.is_published = published


@app.route("/api/admin/articles", methods=["POST"])
@require_roles(*_ROLE_EDITOR)
def admin_create_article():
    article = Article(is_published=False, sort_order=0)
    _apply_article_payload(article, _json_body(), creating=True)
    db.session.add(article)
    db.session.commit()
    return make_succ_response(article.to_dict(), 201)


@app.route("/api/admin/articles/<int:article_id>", methods=["PUT"])
@require_roles(*_ROLE_EDITOR)
def admin_update_article(article_id):
    article = get_article_by_id(article_id)
    if not article:
        return make_err_response("文章不存在", 404)
    _apply_article_payload(article, _json_body())
    db.session.commit()
    return make_succ_response(article.to_dict())


@app.route("/api/admin/articles/<int:article_id>", methods=["DELETE"])
@require_roles("admin")
def admin_delete_article(article_id):
    article = get_article_by_id(article_id)
    if not article:
        return make_err_response("文章不存在", 404)
    cover_url = article.cover_image
    db.session.delete(article)
    db.session.commit()
    storage_delete([cover_url])
    return make_succ_empty_response()


@app.route("/api/admin/articles/<int:article_id>/image", methods=["POST"])
@require_roles(*_ROLE_EDITOR)
def admin_upload_article_image(article_id):
    article = get_article_by_id(article_id)
    if not article:
        return make_err_response("文章不存在", 404)
    result = _upload_image(request.files.get("file"), f"article_image/{article_id}")
    _replace_storage_url(article, "cover_image", result)
    return make_succ_response({"url": result["url"]})


def _get_or_create_company_info():
    info = CompanyInfo.query.first()
    if not info:
        info = CompanyInfo()
        db.session.add(info)
        db.session.flush()
    return info


@app.route("/api/admin/company", methods=["GET"])
@require_admin
def admin_get_company():
    info = CompanyInfo.query.first()
    return make_succ_response(info.to_dict() if info else {})


@app.route("/api/admin/company", methods=["PUT"])
@require_roles(*_ROLE_EDITOR)
def admin_update_company():
    data = _json_body()
    info = _get_or_create_company_info()
    fields = {
        "name": ("name", 200),
        "intro": ("intro", 200_000),
        "phone": ("phone", 20),
        "wechatId": ("wechat_id", 50),
        "email": ("email", 100),
        "address": ("address", 500),
        "businessHours": ("business_hours", 200),
        "companyImage": ("company_image", 500),
    }
    for input_name, (attribute, max_length) in fields.items():
        if input_name in data:
            setattr(
                info,
                attribute,
                clean_text(data[input_name], input_name, max_length=max_length) or None,
            )
    db.session.commit()
    return make_succ_response(info.to_dict())


def _upload_company_image(attribute, name):
    info = _get_or_create_company_info()
    result = _upload_image(request.files.get("file"), f"company/{info.id}/{name}")
    _replace_storage_url(info, attribute, result)
    return make_succ_response({"url": result["url"], "id": info.id})


@app.route("/api/admin/company/logo", methods=["POST"])
@require_roles(*_ROLE_EDITOR)
def admin_upload_company_logo():
    return _upload_company_image("logo", "logo")


@app.route("/api/admin/company/qr", methods=["POST"])
@require_roles(*_ROLE_EDITOR)
def admin_upload_company_qr():
    return _upload_company_image("wechat_qr", "wechat_qr")


@app.route("/api/admin/company/image", methods=["POST"])
@require_roles(*_ROLE_EDITOR)
def admin_upload_company_image():
    return _upload_company_image("company_image", "image")


@app.route("/api/admin/sync-category-icons", methods=["POST"])
@require_roles("admin")
def admin_sync_category_icons():
    tags = Tag.query.filter(Tag.category == "产品系列", Tag.icon.isnot(None), Tag.icon != "").all()
    updated = []
    for tag in tags:
        category = Category.query.filter_by(name=tag.name).first()
        if category and not category.icon:
            category.icon = tag.icon
            updated.append(
                {
                    "categoryId": category.id,
                    "name": category.name,
                    "icon": category.icon,
                }
            )
    db.session.commit()
    return make_succ_response({"synced": len(updated), "details": updated})
