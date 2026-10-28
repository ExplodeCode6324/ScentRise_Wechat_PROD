import json

from flask import Response


def _json_response(payload, status=200):
    return Response(
        json.dumps(payload, ensure_ascii=False, default=str),
        status=status,
        mimetype="application/json",
    )


def make_succ_empty_response(status=200):
    return _json_response({"code": 0, "data": {}}, status)


def make_succ_response(data, status=200):
    return _json_response({"code": 0, "data": data}, status)


def make_err_response(err_msg, status=400, *, details=None, error_code=None):
    payload = {"code": -1, "errorMsg": str(err_msg)}
    if error_code:
        payload["errorCode"] = error_code
    if details is not None:
        payload["details"] = details
    return _json_response(payload, status)
