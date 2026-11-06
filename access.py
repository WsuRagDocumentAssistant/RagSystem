#================================================
# access.py
#================================================
"""
요청 하나를 실행부로 넘기기 전에 로그인·권한을 확인한다(main.to_controller 가 부른다).

예전에는 work 마다 따로 확인하거나 아예 확인하지 않아서, 로그인 없이도 문서를 지우거나
외부 API 키를 읽을 수 있었다(보안 점검 authorization.*). 여기서 한 번에 막는다.

  - 밖에서 부를 수 있는 task 는 아래 표에 있는 것뿐이다. 타이머·테스트용 이름(login,
    school_users_sync, api_insert ...)과 공개 회원가입(REGISTER)은 들어오지 못한다.
  - 토큰은 auth.verify 로 확인하고, 통과하면 요청의 token 자리를 검증된 user_id 로 바꾼다.
    work 들은 지금처럼 token 을 user_id 로 읽으면 된다 — 꾸며낸 값은 여기서 걸러진다.
  - 관리자 작업은 각 work 이 DB 역할을 한 번 더 본다(_require_admin 등). 이 표는 토큰에 실린
    역할로 먼저 거르는 첫 관문이다.
"""

import auth

LOGIN_REQUIRED = "로그인이 필요합니다. 다시 로그인해 주세요."
ADMIN_ONLY = "관리자만 사용할 수 있습니다."
NO_PERMISSION = "이 작업을 할 권한이 없습니다."

# 문서 등록·수정·삭제, 검색어 사전 수정 — 관리자 또는 "문서 정보 입력" 권한
DOCUMENT_PERMISSION = "document_input"

PUBLIC = {"LOGIN", "LOGOUT"}

MEMBER = {
    "USER_QUERY", "MERGE_RESULTS", "CHAT_ANSWER_SAVE", "SESSION_COMPACT_STATUS",
    "CHAT_SESSION_LIST", "CHAT_SESSION_MESSAGES", "CHAT_SESSION_DELETE",
    "FILE_LIST", "FILE_CONTENT", "FILE_DOWNLOAD", "FILE_IMAGE_LIST", "IMAGE_VECTORIZE", "JOB_STATUS",
    "DICTIONARY_LIST", "DOCUMENT_CATEGORY_LIST",
    "NOTIFICATION_LIST", "NOTIFICATION_READ", "NOTIFICATION_CREATE",
    "FEATURE_REQUEST_LIST", "FEATURE_REQUEST_SAVE", "FEATURE_REQUEST_DELETE",
}

DOCUMENT = {"FILE_UPLOAD", "FILE_DELETE", "FILE_IMAGE_SAVE", "FILE_IMAGE_UPLOAD", "DICTIONARY_SAVE"}

ADMIN = {
    "USER_LIST", "USER_SET_ROLE", "USER_SET_PERMISSION",
    "SCHOOL_USER_SEARCH", "SCHOOL_USER_STATUS", "SCHOOL_USER_SYNC",
    "EXTERNAL_API_LIST", "EXTERNAL_API_SAVE", "EXTERNAL_API_DELETE",
    "DOCUMENT_CATEGORY_SAVE", "DOCUMENT_CATEGORY_DELETE",
    "FEATURE_REQUEST_REPLY",
}

EXTERNAL = PUBLIC | MEMBER | DOCUMENT | ADMIN


def authorize(task_type: str, token, payload: dict | None) -> dict | None:
    """task 를 이 토큰으로 실행해도 되면 토큰 내용(payload)을, 공개 task 면 None 을 돌려준다.

    안 되면 ValueError — 라우터가 큐에 넣지 않고 그 메시지로 바로 error 응답한다.
    """
    if task_type not in EXTERNAL:
        raise ValueError(f"지원하지 않는 task_type 입니다: {task_type}")
    if task_type in PUBLIC:
        return None

    claims = auth.verify(token)
    if claims is None:
        raise ValueError(LOGIN_REQUIRED)

    is_admin = claims.get("role") == "admin"
    if task_type in ADMIN and not is_admin:
        raise ValueError(ADMIN_ONLY)
    if task_type in DOCUMENT and not (is_admin or DOCUMENT_PERMISSION in (claims.get("perm") or ())):
        raise ValueError(NO_PERMISSION)
    # 외부 문서 등록 화면은 관리자 전용이다(내부 문서는 "문서 정보 입력" 권한으로도 된다).
    if task_type == "FILE_UPLOAD" and (payload or {}).get("scope") == "external" and not is_admin:
        raise ValueError(ADMIN_ONLY)
    return claims
