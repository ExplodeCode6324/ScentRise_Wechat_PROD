"""WeChat CloudBase object storage client with verified TLS and strict config."""

from __future__ import annotations

import logging
import time
import uuid
from urllib.parse import urlparse

import requests

import config

logger = logging.getLogger(__name__)
TIMEOUT = (10, 30)
_cached_token = None
_cached_token_expires = 0


def _verify_setting():
    return config.REQUESTS_CA_BUNDLE or True


def _storage_config():
    if not config.TCB_ENV_ID:
        raise RuntimeError("缺少 TCB_ENV_ID")
    if not config.CDN_BASE:
        raise RuntimeError("缺少 CDN_BASE")
    parsed = urlparse(config.CDN_BASE)
    if parsed.scheme != "https" or not parsed.netloc:
        raise RuntimeError("CDN_BASE必须是HTTPS地址")
    return config.TCB_ENV_ID, config.CDN_BASE.rstrip("/")


def _get_access_token():
    global _cached_token, _cached_token_expires
    if config.WECHAT_ACCESS_TOKEN:
        return config.WECHAT_ACCESS_TOKEN
    now = time.time()
    if _cached_token and now < _cached_token_expires - 300:
        return _cached_token
    if not config.WECHAT_APPID or not config.WECHAT_APPSECRET:
        raise RuntimeError("缺少 WECHAT_ACCESS_TOKEN 或 WECHAT_APPID/WECHAT_APPSECRET")
    response = requests.get(
        "https://api.weixin.qq.com/cgi-bin/token",
        params={
            "grant_type": "client_credential",
            "appid": config.WECHAT_APPID,
            "secret": config.WECHAT_APPSECRET,
        },
        timeout=TIMEOUT,
        verify=_verify_setting(),
    )
    response.raise_for_status()
    data = response.json()
    if data.get("errcode", 0) != 0:
        raise RuntimeError(
            f"获取access_token失败: [{data.get('errcode')}] {data.get('errmsg', '')}"
        )
    token = data.get("access_token")
    if not token:
        raise RuntimeError("获取access_token失败: 响应缺少access_token")
    _cached_token = token
    _cached_token_expires = now + int(data.get("expires_in", 7200))
    return token


def upload(file_data: bytes, cloud_path: str, content_type: str = "application/octet-stream"):
    try:
        env_id, cdn_base = _storage_config()
        access_token = _get_access_token()
        response = requests.post(
            "https://api.weixin.qq.com/tcb/uploadfile",
            params={"access_token": access_token},
            json={"env": env_id, "path": cloud_path},
            timeout=TIMEOUT,
            verify=_verify_setting(),
        )
        response.raise_for_status()
        info = response.json()
        if info.get("errcode", -1) != 0:
            return {
                "success": False,
                "error": f"获取上传链接失败: [{info.get('errcode')}] {info.get('errmsg', '')}",
            }
        required = ("url", "token", "authorization", "cos_file_id", "file_id")
        if any(not info.get(key) for key in required):
            return {"success": False, "error": "获取上传链接失败：响应字段不完整"}

        boundary = "----ScentRiseBoundary" + uuid.uuid4().hex

        def part(name, value, filename=None, mime=None):
            header = f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"'
            if filename:
                header += f'; filename="{filename}"'
            if mime:
                header += f"\r\nContent-Type: {mime}"
            header += "\r\n\r\n"
            payload = value if isinstance(value, bytes) else str(value).encode("utf-8")
            return header.encode("utf-8") + payload + b"\r\n"

        body = b"".join(
            [
                part("key", cloud_path),
                part("Signature", info["authorization"]),
                part("x-cos-security-token", info["token"]),
                part("x-cos-meta-fileid", info["cos_file_id"]),
                part(
                    "file",
                    file_data,
                    filename=cloud_path.rsplit("/", 1)[-1],
                    mime=content_type,
                ),
                f"--{boundary}--\r\n".encode(),
            ]
        )
        upload_response = requests.post(
            info["url"],
            data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            timeout=TIMEOUT,
            verify=_verify_setting(),
        )
        if upload_response.status_code not in (200, 204):
            logger.error("COS upload failed: HTTP %s", upload_response.status_code)
            return {"success": False, "error": f"文件上传失败: HTTP {upload_response.status_code}"}
        if upload_response.text and "<Error>" in upload_response.text:
            logger.error("COS upload returned an XML error")
            return {"success": False, "error": "文件上传失败：存储服务返回错误"}
        return {
            "success": True,
            "url": f"{cdn_base}/{cloud_path}",
            "fileId": info["file_id"],
            "cloudPath": cloud_path,
        }
    except (RuntimeError, requests.RequestException, ValueError) as exc:
        logger.error("storage upload failed: %s", exc)
        return {"success": False, "error": str(exc)}


def get_download_url(cloud_path_or_fileid: str):
    if cloud_path_or_fileid.startswith("cloud://"):
        return cloud_path_or_fileid
    _env_id, cdn_base = _storage_config()
    return f"{cdn_base}/{cloud_path_or_fileid.lstrip('/')}"


def _cdn_to_fileid(url: str):
    if not url:
        return None
    if url.startswith("cloud://"):
        return url
    try:
        env_id, cdn_base = _storage_config()
        parsed = urlparse(url)
        expected = urlparse(cdn_base)
        if parsed.scheme != "https" or parsed.netloc != expected.netloc:
            return None
        path = parsed.path.lstrip("/")
        if not path:
            return None
        bucket = parsed.netloc.split(".", 1)[0]
        return f"cloud://{env_id}.{bucket}/{path}"
    except (RuntimeError, ValueError):
        return None


def delete_files(urls):
    file_ids = list(dict.fromkeys(filter(None, (_cdn_to_fileid(url) for url in urls))))
    if not file_ids:
        return {"deleted": 0}
    try:
        env_id, _cdn_base = _storage_config()
        response = requests.post(
            "https://api.weixin.qq.com/tcb/batchdeletefile",
            params={"access_token": _get_access_token()},
            json={"env": env_id, "fileid_list": file_ids},
            timeout=TIMEOUT,
            verify=_verify_setting(),
        )
        response.raise_for_status()
        data = response.json()
        if data.get("errcode", -1) != 0:
            logger.error("storage delete API error: %s", data.get("errmsg", "unknown"))
            return {"deleted": 0, "error": data.get("errmsg", "unknown")}
        deleted = sum(1 for item in data.get("delete_list", []) if item.get("status") == 0)
        return {"deleted": deleted}
    except (RuntimeError, requests.RequestException, ValueError) as exc:
        logger.error("storage delete failed: %s", exc)
        return {"deleted": 0, "error": str(exc)}
