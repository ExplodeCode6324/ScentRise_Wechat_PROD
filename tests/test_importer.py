import pytest

from wxcloudrun import db
from wxcloudrun.importer import ImportRejected, execute_import, preflight_import
from wxcloudrun.model import Category, Product, Tag


def _seed_existing():
    category = Category(name="水质系列")
    series_tag = Tag(name="水质系列", category="产品系列")
    usage_tag = Tag(name="饮料", category="适用产品")
    product = Product(
        product_series="水质系列",
        product_name="草莓香精",
        product_english_name="Strawberry",
        product_model="AY224",
        product_desc="保留描述",
        category=category,
        tags=[series_tag, usage_tag],
    )
    db.session.add(product)
    db.session.commit()
    return product


def test_customer_aliases_and_blank_cells_preserve_existing(app_context):
    _seed_existing()
    rows = [
        {
            "产品系列": "水质系列",
            "名称": "草莓香精",
            "型号": "AY224",
            "英文名称": "",
            "产品描述": "",
            "tags": [],
            "tagsProvided": True,
            "excelRow": 2,
        }
    ]
    options = {
        "emptyTagAction": "preserve",
        "overwriteEmpty": False,
        "existingModelAction": "update",
    }
    preflight = preflight_import(rows, options)
    assert preflight["valid"] is True
    assert preflight["summary"]["noChange"] == 1
    result = execute_import(rows, options, preflight["planHash"])
    assert result == {
        "created": 0,
        "updated": 0,
        "unchanged": 1,
        "errors": [],
        "skipped": [],
        "invalidRows": 0,
        "skippedRows": 0,
        "planHash": preflight["planHash"],
    }
    product = Product.query.filter_by(product_model="AY224").one()
    assert product.product_english_name == "Strawberry"
    assert product.product_desc == "保留描述"
    assert sorted(tag.name for tag in product.tags) == ["水质系列", "饮料"]


def test_duplicate_choice_and_invalid_rows_do_not_block_other_rows(app_context):
    rows = [
        {"产品系列": "水质系列", "名称": "A", "型号": "DUP", "excelRow": 2},
        {"产品系列": "水质系列", "名称": "B", "型号": "DUP", "excelRow": 3},
        {"产品系列": "水质系列", "名称": "C", "型号": "", "excelRow": 4},
        {"产品系列": "水质系列", "名称": "D", "型号": "UNIQUE", "excelRow": 5},
    ]
    result = preflight_import(rows)
    assert result["valid"] is False
    assert result["planHash"] is None
    assert result["decisions"][0]["code"] == "file_duplicate_models"
    assert {error["code"] for error in result["errors"]} == {"required"}

    result = preflight_import(rows, {"duplicateModelAction": "skip"})
    assert result["valid"] is True
    assert result["summary"]["validRows"] == 1
    assert result["summary"]["invalidRows"] == 1
    assert result["summary"]["skippedRows"] == 2
    imported = execute_import(
        rows,
        {"duplicateModelAction": "skip"},
        result["planHash"],
        confirm_warnings=True,
    )
    assert imported["created"] == 1
    assert imported["invalidRows"] == 1
    assert imported["skippedRows"] == 2
    assert Product.query.filter_by(product_model="UNIQUE").one().product_name == "D"
    assert Product.query.filter_by(product_model="DUP").first() is None


def test_duplicate_last_row_wins_and_other_rows_continue(app_context):
    rows = [
        {"产品系列": "水质系列", "名称": "旧值", "型号": "DUP", "excelRow": 2},
        {"产品系列": "水质系列", "名称": "最后值", "型号": "DUP", "excelRow": 3},
        {"产品系列": "水质系列", "名称": "独立项", "型号": "UNIQUE", "excelRow": 4},
    ]
    options = {"duplicateModelAction": "last_wins"}
    result = preflight_import(rows, options)
    assert result["valid"] is True
    assert result["summary"]["validRows"] == 2
    assert result["summary"]["skippedRows"] == 1
    imported = execute_import(rows, options, result["planHash"], confirm_warnings=True)
    assert imported["created"] == 2
    assert Product.query.filter_by(product_model="DUP").one().product_name == "最后值"


def test_existing_model_can_be_skipped_while_new_rows_import(app_context):
    _seed_existing()
    rows = [
        {"产品系列": "水质系列", "名称": "不覆盖", "型号": "AY224", "excelRow": 2},
        {"产品系列": "水质系列", "名称": "新项目", "型号": "NEW-1", "excelRow": 3},
    ]
    ask = preflight_import(rows)
    assert ask["valid"] is False
    assert ask["decisions"][0]["code"] == "existing_models"

    options = {"existingModelAction": "skip"}
    plan = preflight_import(rows, options)
    assert plan["valid"] is True
    assert plan["summary"]["wouldCreate"] == 1
    assert plan["summary"]["skippedRows"] == 1
    imported = execute_import(rows, options, plan["planHash"], confirm_warnings=True)
    assert imported["created"] == 1
    assert Product.query.filter_by(product_model="AY224").one().product_name == "草莓香精"
    assert Product.query.filter_by(product_model="NEW-1").one().product_name == "新项目"
    assert Product.query.count() == 2


def test_ambiguous_series_warns_but_is_not_silently_mapped(app_context):
    rows = [{"产品系列": "水油质", "名称": "测试", "型号": "T-1"}]
    result = preflight_import(rows)
    assert result["valid"] is True
    assert result["warnings"][0]["code"] == "series_name_conflict"
    assert result["_rows"][0]["productSeries"] == "水油质"
    with pytest.raises(ImportRejected, match="警告"):
        execute_import(rows, {}, result["planHash"], confirm_warnings=False)


def test_plan_hash_rejects_concurrent_product_change(app_context):
    product = _seed_existing()
    rows = [{"产品系列": "水质系列", "名称": "草莓2", "型号": "AY224"}]
    options = {"existingModelAction": "update"}
    plan = preflight_import(rows, options)
    product.product_name = "并发修改"
    db.session.commit()
    with pytest.raises(ImportRejected) as caught:
        execute_import(rows, options, plan["planHash"])
    assert caught.value.status == 409


def test_commit_failure_rolls_back_every_row(app_context, monkeypatch):
    rows = [
        {"产品系列": "水质系列", "名称": "A", "型号": "A-1"},
        {"产品系列": "水质系列", "名称": "B", "型号": "B-1"},
    ]
    plan = preflight_import(rows)

    def fail_commit():
        raise RuntimeError("simulated commit failure")

    monkeypatch.setattr(db.session, "commit", fail_commit)
    with pytest.raises(RuntimeError, match="simulated"):
        execute_import(rows, {}, plan["planHash"])
    db.session.rollback()
    assert Product.query.count() == 0
