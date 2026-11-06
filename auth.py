#================================================
# auth.py
#================================================
"""
로그인 토큰 — 서버 비밀키로 서명한, 만료가 있는 토큰.

예전에는 사용자 UUID 를 그대로 토큰으로 썼다. 사용자 목록(USER_LIST)이 UUID 를 내보내므로
관리자 UUID 만 알면 관리자로 행세할 수 있었다(보안 점검 authentication.public-uuid-bearer).
이제 로그인할 때 서버가 토큰을 발급하고, 요청마다 서명과 만료를 확인한다.

    v1.<payload base64url>.<HMAC-SHA256 base64url>
    payload = {"sub": user_id, "role": "admin"|"user", "perm": [...], "exp": 만료 epoch 초}

DB 를 보지 않는다(요청마다 조회가 늘지 않게). 대신 역할·권한이 토큰에 실려 있어 바뀐 역할은
다시 로그인해야 반영된다 — 관리자 작업은 각 work 이 DB 역할을 한 번 더 본다(_require_admin).
로그아웃해도 토큰이 바로 무효가 되지는 않고 만료(RAG_TOKEN_HOURS)로 끝난다.

비밀키는 RAG_AUTH_SECRET(k8s secret)에서 읽는다. 없으면 기동할 때 임의 키를 만들어
os.environ 에 넣는다 — 실행부는 spawn 으로 뜨는 자식 프로세스라 환경변수를 물려받아 같은 키를
쓴다. 이 경우 서버가 재시작되면 모든 토큰이 무효가 되어 다시 로그인해야 한다.
"""

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import time

logger = logging.getLogger(__name__)

TOKEN_HOURS = float(os.environ.get("RAG_TOKEN_HOURS", "12"))
_PREFIX = "v1"

if not os.environ.get("RAG_AUTH_SECRET"):
    os.environ["RAG_AUTH_SECRET"] = secrets.token_urlsafe(48)
    logger.warning("RAG_AUTH_SECRET 이 없어 임의 키를 만들었습니다. 서버를 재시작하면 모두 다시 로그인해야 합니다 "
                   "— k8s secret 에 RAG_AUTH_SECRET 을 넣어 주세요.")
_SECRET = os.environ["RAG_AUTH_SECRET"].encode("utf-8")


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _sign(body: str) -> str:
    return _b64(hmac.new(_SECRET, f"{_PREFIX}.{body}".encode("ascii"), hashlib.sha256).digest())


def issue(user_id: str, role: str, permissions=()) -> str:
    """로그인한 사용자에게 줄 토큰."""
    payload = {"sub": str(user_id), "role": role or "user", "perm": sorted(permissions or ()),
               "exp": int(time.time() + TOKEN_HOURS * 3600)}
    body = _b64(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    return f"{_PREFIX}.{body}.{_sign(body)}"


def verify(token) -> dict | None:
    """토큰 -> payload. 서명이 틀리거나 만료됐거나 모양이 아니면 None."""
    if not isinstance(token, str) or token.count(".") != 2:
        return None
    prefix, body, signature = token.split(".")
    if prefix != _PREFIX or not hmac.compare_digest(signature, _sign(body)):
        return None
    try:
        payload = json.loads(_unb64(body))
    except (ValueError, TypeError):
        return None
    if not isinstance(payload, dict) or not payload.get("sub") or payload.get("exp", 0) < time.time():
        return None
    return payload
