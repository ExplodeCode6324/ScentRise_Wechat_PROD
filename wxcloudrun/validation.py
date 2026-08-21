"""Shared request, rich-text, pagination and image validation helpers."""

from __future__ import annotations

from io import BytesIO
from typing import Any

import bleach
from PIL import Image, UnidentifiedImageError


class ValidationError(ValueError):
    pass


ALLOWED_RICH_TEXT_TAGS = {
    "p",
    "br",
    "strong",
    "b",
    "em",
    "i",
    "u",
    "s",
    "blockquote",
    "ol",
    "ul",
    "li",
    "h1",
    "h2",
    "h3",
    "h4",
    "a",
    "img",
    "span",
}
ALLOWED_RICH_TEXT_ATTRIBUTES = {
    "a": ["href", "title", "target", "rel"],
    "img": ["src", "alt", "title"],
    "span": ["class"],
    "p": ["class"],
}
ALLOWED_PROTOCOLS = {"http", "https", "mailto", "cloud"}

IMAGE_FORMATS = {
    "JPEG": ("jpg", "image/jpeg"),
    "PNG": ("png", "image/png"),
    "WEBP": ("webp", "image/webp"),
    "GIF": ("gif", "image/gif"),
}


def clean_text(
    value: Any,
    field: str,
    *,
    required: bool = False,
    max_length: int | None = None,
) -> str:
    text = "" if value is None else str(value).strip()
    if required and not text:
        raise ValidationError(f"{field}不能为空")
    if max_length is not None and len(text) > max_length:
        raise ValidationError(f"{field}不能超过{max_length}个字符")
    return text


def clean_int(
    value: Any,
    field: str,
    *,
    default: int = 0,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    if value is None or value == "":
        result = default
    else:
        try:
            result = int(value)
        except (TypeError, ValueError) as exc:
            raise ValidationError(f"{field}必须是整数") from exc
    if minimum is not None and result < minimum:
        raise ValidationError(f"{field}不能小于{minimum}")
    if maximum is not None and result > maximum:
        raise ValidationError(f"{field}不能大于{maximum}")
    return result


def pagination_args(args, *, default_size=20, max_size=100):
    page = args.get("page", 1, type=int)
    page_size = args.get("page_size", default_size, type=int)
    if page is None or page < 1:
        raise ValidationError("page必须大于等于1")
    if page_size is None or page_size < 1 or page_size > max_size:
        raise ValidationError(f"page_size必须在1到{max_size}之间")
    return page, page_size


def sanitize_rich_text(value: Any) -> str:
    raw = clean_text(value, "正文", required=True, max_length=500_000)
    cleaned = bleach.clean(
        raw,
        tags=ALLOWED_RICH_TEXT_TAGS,
        attributes=ALLOWED_RICH_TEXT_ATTRIBUTES,
        protocols=ALLOWED_PROTOCOLS,
        strip=True,
    )
    return bleach.linkify(cleaned)


def validate_image_upload(file_storage, *, max_bytes: int):
    if file_storage is None or not file_storage.filename:
        raise ValidationError("请选择图片文件")
    data = file_storage.stream.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValidationError(f"图片不能超过{max_bytes // (1024 * 1024)}MB")
    if not data:
        raise ValidationError("图片文件为空")
    try:
        with Image.open(BytesIO(data)) as image:
            image.verify()
            image_format = (image.format or "").upper()
        with Image.open(BytesIO(data)) as image:
            width, height = image.size
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ValidationError("文件内容不是有效图片") from exc
    if image_format not in IMAGE_FORMATS:
        raise ValidationError("仅支持 JPG、PNG、WEBP 或 GIF 图片")
    if width <= 0 or height <= 0 or width > 12000 or height > 12000:
        raise ValidationError("图片尺寸不合法或超过12000像素")
    extension, content_type = IMAGE_FORMATS[image_format]
    return data, extension, content_type
