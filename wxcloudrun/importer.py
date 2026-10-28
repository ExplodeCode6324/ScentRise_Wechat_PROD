"""Validated, idempotent and atomic product import service."""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict

from sqlalchemy.orm import joinedload

from wxcloudrun import db
from wxcloudrun.model import Category, Product, Tag

TAG_COLUMNS = ("烘培", "糖果", "饮料", "炒货", "乳品", "膨化", "电子烟")
TRUE_MARKERS = {"√", "✓", "v", "V", "1", "是", "true", "TRUE"}
SERIES_SUGGESTIONS = {"水油质": "水油系列"}

FIELD_KEYS = {
    "productSeries": ("productSeries", "产品系列"),
    "productName": ("productName", "产品名称", "名称"),
    "productEnglishName": ("productEnglishName", "英文名称"),
    "productModel": ("productModel", "产品型号", "型号"),
    "productDesc": ("productDesc", "产品简介", "产品描述"),
}


class ImportRejected(ValueError):
    def __init__(self, message, *, status=422, preflight=None):
        super().__init__(message)
        self.status = status
        self.preflight = preflight


def _first_value(row, keys):
    for key in keys:
        if key in row and row[key] is not None:
            return row[key]
    return ""


def _text(value):
    return "" if value is None else str(value).strip()


def _split_tags(value):
    if isinstance(value, (list, tuple, set)):
        values = value
    else:
        values = re.split(r"[,，;；]", _text(value))
    return [_text(item) for item in values if _text(item)]


def _marked(value):
    return value is True or value == 1 or _text(value) in TRUE_MARKERS


def normalize_rows(raw_rows, *, series_mappings=None):
    mappings = {
        str(key).strip(): str(value).strip() for key, value in (series_mappings or {}).items()
    }
    normalized = []
    for index, raw in enumerate(raw_rows):
        row = raw if isinstance(raw, dict) else {}
        try:
            excel_row = int(row.get("excelRow") or row.get("_excelRow") or index + 2)
        except (TypeError, ValueError):
            excel_row = index + 2
        series = _text(_first_value(row, FIELD_KEYS["productSeries"]))
        if series in mappings:
            series = mappings[series]
        tags = _split_tags(row.get("tags", row.get("标签", "")))
        tags.extend(column for column in TAG_COLUMNS if column in row and _marked(row[column]))
        tags = list(dict.fromkeys(tag for tag in tags if tag))
        tags_provided = bool(
            row.get("tagsProvided")
            if "tagsProvided" in row
            else ("tags" in row or "标签" in row or any(column in row for column in TAG_COLUMNS))
        )
        normalized.append(
            {
                "excelRow": excel_row,
                "productSeries": series,
                "productName": _text(_first_value(row, FIELD_KEYS["productName"])),
                "productEnglishName": _text(_first_value(row, FIELD_KEYS["productEnglishName"])),
                "productModel": _text(_first_value(row, FIELD_KEYS["productModel"])),
                "productDesc": _text(_first_value(row, FIELD_KEYS["productDesc"])),
                "tags": tags,
                "tagsProvided": tags_provided,
            }
        )
    return normalized


def _options(raw_options):
    options = raw_options if isinstance(raw_options, dict) else {}
    empty_tag_action = options.get("emptyTagAction", "preserve")
    if empty_tag_action not in {"preserve", "clear"}:
        empty_tag_action = "preserve"
    duplicate_model_action = options.get("duplicateModelAction", "ask")
    if duplicate_model_action not in {"ask", "last_wins", "skip"}:
        duplicate_model_action = "ask"
    existing_model_action = options.get("existingModelAction", "ask")
    if existing_model_action not in {"ask", "update", "skip"}:
        existing_model_action = "ask"
    mappings = options.get("seriesMappings")
    if not isinstance(mappings, dict):
        mappings = {}
    return {
        "emptyTagAction": empty_tag_action,
        "duplicateModelAction": duplicate_model_action,
        "existingModelAction": existing_model_action,
        "overwriteEmpty": bool(options.get("overwriteEmpty", False)),
        "seriesMappings": {
            str(k).strip(): str(v).strip() for k, v in mappings.items() if str(k).strip()
        },
    }


def _issue(row, field, code, message, **extra):
    value = {"row": row, "field": field, "code": code, "message": message}
    value.update(extra)
    return value


def _database_snapshot(products):
    return [
        {
            "id": product.id,
            "model": product.product_model,
            "updatedAt": product.updated_at.isoformat() if product.updated_at else None,
        }
        for product in sorted(products.values(), key=lambda item: item.product_model)
    ]


def _plan_hash(rows, options, snapshot):
    payload = json.dumps(
        {"rows": rows, "options": options, "snapshot": snapshot},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def preflight_import(raw_rows, raw_options=None, *, max_rows=5000):
    options = _options(raw_options)
    errors = []
    warnings = []
    skipped = []
    decisions = []
    if not isinstance(raw_rows, list):
        return {
            "valid": False,
            "errors": [_issue(None, "rows", "invalid_type", "rows必须是数组")],
            "warnings": [],
            "skipped": [],
            "decisions": [],
            "summary": {"total": 0, "validRows": 0},
            "planHash": None,
        }
    if not raw_rows:
        return {
            "valid": False,
            "errors": [_issue(None, "rows", "empty_file", "导入文件没有数据行")],
            "warnings": [],
            "skipped": [],
            "decisions": [],
            "summary": {"total": 0, "validRows": 0},
            "planHash": None,
        }
    if len(raw_rows) > max_rows:
        return {
            "valid": False,
            "errors": [_issue(None, "rows", "too_many_rows", f"单次最多导入{max_rows}行")],
            "warnings": [],
            "skipped": [],
            "decisions": [],
            "summary": {"total": len(raw_rows), "validRows": 0},
            "planHash": None,
        }

    normalized_rows = normalize_rows(raw_rows, series_mappings=options["seriesMappings"])
    unmapped_rows = normalize_rows(raw_rows)
    row_pairs = []
    for row, unmapped in zip(normalized_rows, unmapped_rows, strict=True):
        excel_row = row["excelRow"]
        row_issues = []
        required = (
            ("productSeries", "产品系列", 50),
            ("productName", "产品名称", 200),
            ("productModel", "产品型号", 100),
        )
        for field, label, max_length in required:
            if not row[field]:
                row_issues.append(
                    _issue(excel_row, field, "required", f"第{excel_row}行: 缺少{label}")
                )
            elif len(row[field]) > max_length:
                row_issues.append(
                    _issue(
                        excel_row,
                        field,
                        "too_long",
                        f"第{excel_row}行: {label}超过{max_length}字符",
                    )
                )
        if len(row["productEnglishName"]) > 200:
            row_issues.append(
                _issue(
                    excel_row,
                    "productEnglishName",
                    "too_long",
                    f"第{excel_row}行: 英文名称超过200字符",
                )
            )
        if len(row["productDesc"]) > 200_000:
            row_issues.append(
                _issue(excel_row, "productDesc", "too_long", f"第{excel_row}行: 产品描述过长")
            )
        for tag in row["tags"]:
            if len(tag) > 50:
                row_issues.append(
                    _issue(
                        excel_row,
                        "tags",
                        "too_long",
                        f"第{excel_row}行: 标签“{tag[:20]}”超过50字符",
                    )
                )
        if row_issues:
            errors.extend(row_issues)
        else:
            row_pairs.append((row, unmapped))

    model_positions = defaultdict(list)
    for position, (row, _) in enumerate(row_pairs):
        model_positions[row["productModel"]].append(position)
    duplicate_models = {
        model: positions for model, positions in model_positions.items() if len(positions) > 1
    }
    if duplicate_models:
        duplicate_details = [
            {
                "model": model,
                "rows": [row_pairs[position][0]["excelRow"] for position in positions],
                "winnerRow": row_pairs[positions[-1]][0]["excelRow"],
            }
            for model, positions in sorted(duplicate_models.items())
        ]
        action = options["duplicateModelAction"]
        if action == "ask":
            decisions.append(
                {
                    "code": "file_duplicate_models",
                    "message": f"文件内有{len(duplicate_models)}个重复型号，请选择覆盖或跳过",
                    "duplicateModelCount": len(duplicate_models),
                    "duplicates": duplicate_details[:100],
                }
            )
            ignored_positions = {
                position for positions in duplicate_models.values() for position in positions
            }
        elif action == "last_wins":
            ignored_positions = {
                position for positions in duplicate_models.values() for position in positions[:-1]
            }
            warnings.append(
                _issue(
                    None,
                    "productModel",
                    "duplicate_model_overwrite",
                    f"文件内{len(duplicate_models)}个型号重复；采用最后一行并忽略{len(ignored_positions)}行",
                    duplicateModelCount=len(duplicate_models),
                    ignoredRowCount=len(ignored_positions),
                    duplicates=duplicate_details[:100],
                )
            )
        else:
            ignored_positions = {
                position for positions in duplicate_models.values() for position in positions
            }
            warnings.append(
                _issue(
                    None,
                    "productModel",
                    "duplicate_model_skipped",
                    f"已跳过文件内{len(duplicate_models)}个重复型号的全部{len(ignored_positions)}行",
                    duplicateModelCount=len(duplicate_models),
                    ignoredRowCount=len(ignored_positions),
                    duplicates=duplicate_details[:100],
                )
            )
        if action != "ask":
            for position in sorted(ignored_positions):
                row = row_pairs[position][0]
                skipped.append(
                    _issue(
                        row["excelRow"],
                        "productModel",
                        "duplicate_model_overwritten"
                        if action == "last_wins"
                        else "duplicate_model_skipped",
                        f"第{row['excelRow']}行: 型号“{row['productModel']}”重复，已"
                        + ("由最后一行覆盖" if action == "last_wins" else "跳过"),
                        model=row["productModel"],
                    )
                )
        row_pairs = [
            pair for position, pair in enumerate(row_pairs) if position not in ignored_positions
        ]

    suggestion_rows = defaultdict(list)
    reverse_mappings = options["seriesMappings"]
    for _, original in row_pairs:
        if (
            original["productSeries"] in SERIES_SUGGESTIONS
            and original["productSeries"] not in reverse_mappings
        ):
            suggestion_rows[original["productSeries"]].append(original["excelRow"])
    for source, affected_rows in suggestion_rows.items():
        target = SERIES_SUGGESTIONS[source]
        warnings.append(
            _issue(
                None,
                "productSeries",
                "series_name_conflict",
                f"系列“{source}”可能与现有“{target}”同义；系统不会自动改名",
                source=source,
                suggested=target,
                count=len(affected_rows),
                sampleRows=affected_rows[:20],
            )
        )

    tag_roles = defaultdict(set)
    tag_positions = defaultdict(list)
    for position, (row, _) in enumerate(row_pairs):
        tag_roles[row["productSeries"]].add("产品系列")
        tag_positions[row["productSeries"]].append((position, "产品系列"))
        for tag in row["tags"]:
            tag_roles[tag].add("适用产品")
            tag_positions[tag].append((position, "适用产品"))
    invalid_role_positions = set()
    for tag_name, roles in tag_roles.items():
        if len(roles) <= 1:
            continue
        for position, _ in tag_positions[tag_name]:
            row = row_pairs[position][0]
            errors.append(
                _issue(
                    row["excelRow"],
                    "tags",
                    "tag_role_conflict",
                    f"第{row['excelRow']}行: “{tag_name}”同时被用作产品系列和适用标签",
                )
            )
            invalid_role_positions.add(position)
    if tag_roles:
        existing_tags = Tag.query.filter(Tag.name.in_(list(tag_roles))).all()
        for tag in existing_tags:
            if len(tag_roles[tag.name]) != 1:
                continue
            expected = next(iter(tag_roles[tag.name]))
            if tag.category != expected:
                for position, _ in tag_positions[tag.name]:
                    row = row_pairs[position][0]
                    errors.append(
                        _issue(
                            row["excelRow"],
                            "tags",
                            "existing_tag_role_conflict",
                            f"第{row['excelRow']}行: 标签“{tag.name}”现有分类为“{tag.category}”，导入要求为“{expected}”",
                        )
                    )
                    invalid_role_positions.add(position)
    row_pairs = [
        pair for position, pair in enumerate(row_pairs) if position not in invalid_role_positions
    ]

    models = sorted({row["productModel"] for row, _ in row_pairs})
    products = {}
    if models:
        product_list = (
            Product.query.options(joinedload(Product.tags))
            .filter(Product.product_model.in_(models))
            .all()
        )
        products = {product.product_model: product for product in product_list}

    if products and options["existingModelAction"] == "ask":
        existing_details = [
            {"model": row["productModel"], "row": row["excelRow"]}
            for row, _ in row_pairs
            if row["productModel"] in products
        ]
        decisions.append(
            {
                "code": "existing_models",
                "message": f"数据库中已有{len(products)}个相同型号，请选择覆盖或跳过",
                "existingModelCount": len(products),
                "items": existing_details[:100],
            }
        )
    elif products and options["existingModelAction"] == "skip":
        kept_pairs = []
        for row, unmapped in row_pairs:
            if row["productModel"] in products:
                skipped.append(
                    _issue(
                        row["excelRow"],
                        "productModel",
                        "existing_model_skipped",
                        f"第{row['excelRow']}行: 型号“{row['productModel']}”已存在，按选择跳过",
                        model=row["productModel"],
                    )
                )
            else:
                kept_pairs.append((row, unmapped))
        warnings.append(
            _issue(
                None,
                "productModel",
                "existing_models_skipped",
                f"已跳过数据库中存在的{len(products)}个型号，其余合格行继续导入",
                existingModelCount=len(products),
            )
        )
        row_pairs = kept_pairs
        products = {}

    rows = [row for row, _ in row_pairs]
    models = sorted({row["productModel"] for row in rows})
    products = {model: product for model, product in products.items() if model in models}

    would_create = 0
    would_update = 0
    no_change = 0
    for row in rows:
        product = products.get(row["productModel"])
        if not product:
            would_create += 1
            continue
        changed = (
            product.product_series != row["productSeries"]
            or product.product_name != row["productName"]
            or (
                (row["productEnglishName"] or options["overwriteEmpty"])
                and (product.product_english_name or "") != row["productEnglishName"]
            )
            or (
                (row["productDesc"] or options["overwriteEmpty"])
                and (product.product_desc or "") != row["productDesc"]
            )
        )
        current_usage = sorted(tag.name for tag in product.tags if tag.category != "产品系列")
        if row["tags"] or options["emptyTagAction"] == "clear":
            changed = changed or current_usage != sorted(row["tags"])
        if changed:
            would_update += 1
        else:
            no_change += 1

    snapshot = _database_snapshot(products)
    if not rows and not decisions:
        errors.append(
            _issue(None, "rows", "no_importable_rows", "没有可导入的合格行；数据库未写入")
        )
    invalid_rows = {issue["row"] for issue in errors if issue.get("row") is not None}
    skipped_rows = {issue["row"] for issue in skipped if issue.get("row") is not None}
    valid = bool(rows) and not decisions
    summary = {
        "total": len(raw_rows),
        "effectiveRows": len(rows),
        "validRows": len(rows),
        "invalidRows": len(invalid_rows),
        "skippedRows": len(skipped_rows),
        "errorCount": len(errors),
        "warningCount": len(warnings),
        "decisionCount": len(decisions),
        "wouldCreate": would_create,
        "wouldUpdate": would_update,
        "noChange": no_change,
        "uniqueModels": len(models),
    }
    return {
        "valid": valid,
        "errors": errors[:500],
        "warnings": warnings[:200],
        "skipped": skipped[:500],
        "decisions": decisions,
        "summary": summary,
        "planHash": _plan_hash(rows, options, snapshot) if valid else None,
        "_rows": rows,
        "_options": options,
        "_skipped": skipped,
    }


def execute_import(
    raw_rows, raw_options, expected_plan_hash, *, confirm_warnings=False, max_rows=5000
):
    preflight = preflight_import(raw_rows, raw_options, max_rows=max_rows)
    public_preflight = {key: value for key, value in preflight.items() if not key.startswith("_")}
    if not preflight["valid"]:
        raise ImportRejected("导入预检未通过", preflight=public_preflight)
    if not expected_plan_hash or expected_plan_hash != preflight["planHash"]:
        raise ImportRejected("预检结果已过期，请重新预检", status=409, preflight=public_preflight)
    if preflight["warnings"] and not confirm_warnings:
        raise ImportRejected("存在需要确认的警告", preflight=public_preflight)

    rows = preflight["_rows"]
    options = preflight["_options"]
    models = [row["productModel"] for row in rows]
    locked_products = (
        Product.query.options(joinedload(Product.tags))
        .filter(Product.product_model.in_(models))
        .with_for_update()
        .all()
    )
    products = {product.product_model: product for product in locked_products}
    locked_hash = _plan_hash(rows, options, _database_snapshot(products))
    if locked_hash != expected_plan_hash:
        raise ImportRejected(
            "导入期间数据已变化，请重新预检", status=409, preflight=public_preflight
        )

    series_names = sorted({row["productSeries"] for row in rows})
    categories = {
        category.name: category
        for category in Category.query.filter(Category.name.in_(series_names)).all()
    }
    for name in series_names:
        if name not in categories:
            categories[name] = Category(name=name)
            db.session.add(categories[name])

    usage_names = {tag for row in rows for tag in row["tags"]}
    all_tag_names = set(series_names) | usage_names
    tags = {tag.name: tag for tag in Tag.query.filter(Tag.name.in_(list(all_tag_names))).all()}
    for name in sorted(all_tag_names):
        if name not in tags:
            role = "产品系列" if name in series_names else "适用产品"
            tags[name] = Tag(name=name, category=role, sort_order=1 if role == "产品系列" else 2)
            db.session.add(tags[name])
    db.session.flush()

    created = 0
    updated = 0
    unchanged = 0
    for row in rows:
        product = products.get(row["productModel"])
        is_new = product is None
        if is_new:
            product = Product(product_model=row["productModel"], is_active=True)
            db.session.add(product)
            products[row["productModel"]] = product
            created += 1
        before = (
            None
            if is_new
            else (
                product.product_series,
                product.product_name,
                product.product_english_name or "",
                product.product_desc or "",
                product.category.name if product.category else None,
                tuple(sorted(tag.name for tag in product.tags)),
            )
        )

        product.product_series = row["productSeries"]
        product.category = categories[row["productSeries"]]
        product.product_name = row["productName"]
        if row["productEnglishName"] or options["overwriteEmpty"] or is_new:
            product.product_english_name = row["productEnglishName"]
        if row["productDesc"] or options["overwriteEmpty"] or is_new:
            product.product_desc = row["productDesc"]

        series_tag = tags[row["productSeries"]]
        if row["tags"] or options["emptyTagAction"] == "clear" or is_new:
            usage_tags = [tags[name] for name in row["tags"]]
        else:
            usage_tags = [tag for tag in product.tags if tag.category != "产品系列"]
        product.tags = list(dict.fromkeys([series_tag, *usage_tags]))

        if not is_new:
            after = (
                product.product_series,
                product.product_name,
                product.product_english_name or "",
                product.product_desc or "",
                product.category.name if product.category else None,
                tuple(sorted(tag.name for tag in product.tags)),
            )
            if before == after:
                unchanged += 1
            else:
                updated += 1

    db.session.commit()
    return {
        "created": created,
        "updated": updated,
        "unchanged": unchanged,
        "errors": preflight["errors"],
        "skipped": preflight["skipped"],
        "invalidRows": preflight["summary"]["invalidRows"],
        "skippedRows": preflight["summary"]["skippedRows"],
        "planHash": preflight["planHash"],
    }
