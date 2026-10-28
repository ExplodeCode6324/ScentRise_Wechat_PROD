from io import BytesIO

from wxcloudrun import db
from wxcloudrun.model import Article, Category, Product, Tag


def test_login_uses_http_only_cookie_and_role_blocks_import(client, login):
    response = login(username="editor", role="editor")
    assert "token" not in response.get_json()["data"]
    cookie = response.headers["Set-Cookie"]
    assert "HttpOnly" in cookie and "SameSite=Strict" in cookie
    denied = client.post("/api/admin/import/preflight", json={"rows": []})
    assert denied.status_code == 403


def test_admin_import_preflight_accepts_name_model_aliases(client, login):
    login()
    response = client.post(
        "/api/admin/import/preflight",
        json={"rows": [{"产品系列": "水质系列", "名称": "测试香精", "型号": "T-100"}]},
    )
    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["valid"] is True
    assert data["summary"]["wouldCreate"] == 1
    assert data["planHash"]


def test_public_api_hides_inactive_products_and_draft_articles(client, app_context):
    category = Category(name="水质系列")
    product = Product(
        product_series="水质系列",
        product_name="下架",
        product_model="OFF-1",
        category=category,
        is_active=False,
    )
    draft = Article(title="草稿", content="<p>draft</p>", is_published=False)
    db.session.add_all([product, draft])
    db.session.commit()
    assert client.get(f"/api/products/{product.id}").status_code == 404
    assert client.get(f"/api/articles/{draft.id}").status_code == 404
    assert client.get("/api/products").get_json()["data"]["total"] == 0
    assert client.get("/api/articles").get_json()["data"]["total"] == 0


def test_article_html_is_sanitized_for_new_and_legacy_content(client, login, app_context):
    login()
    response = client.post(
        "/api/admin/articles",
        json={
            "title": "安全测试",
            "content": '<p onclick="evil()">ok</p><script>alert(1)</script><img src="javascript:evil()">',
            "isPublished": True,
        },
    )
    assert response.status_code == 201, response.get_json()
    content = response.get_json()["data"]["content"]
    assert "script" not in content and "onclick" not in content and "javascript" not in content


def test_product_crud_derives_series_and_rejects_missing_tag(client, login, app_context):
    login()
    category = Category(name="油质系列")
    usage = Tag(name="烘培", category="适用产品")
    db.session.add_all([category, usage])
    db.session.commit()
    response = client.post(
        "/api/admin/products",
        json={
            "categoryId": category.id,
            "productSeries": "伪造系列",
            "productName": "葱油",
            "productModel": "OIL-1",
            "tagIds": [usage.id],
            "collectionIds": [],
        },
    )
    assert response.status_code == 201, response.get_json()
    data = response.get_json()["data"]
    assert data["productSeries"] == "油质系列"
    assert sorted(tag["name"] for tag in data["tags"]) == ["油质系列", "烘培"]
    bad = client.post(
        "/api/admin/products",
        json={
            "categoryId": category.id,
            "productName": "坏",
            "productModel": "OIL-2",
            "tagIds": [99999],
        },
    )
    assert bad.status_code == 422


def test_invalid_image_is_rejected_before_storage_call(client, login, app_context):
    login()
    category = Category(name="水质系列")
    product = Product(
        product_series=category.name,
        product_name="测试",
        product_model="IMG-1",
        category=category,
    )
    db.session.add(product)
    db.session.commit()
    response = client.post(
        f"/api/admin/products/{product.id}/images",
        data={"image_type": "main", "file": (BytesIO(b"not-an-image"), "fake.jpg")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 422
    assert "有效图片" in response.get_json()["errorMsg"]


def test_http_method_errors_keep_real_status(client):
    assert client.post("/api/categories").status_code == 405
    assert client.get("/api/products?page=0").status_code == 422
