#================================================
# request_functions.py
#================================================

import uuid

from taskcontroller import work_regist, tasks
from request_board import build_request, STATUSES
from functions.data_functions import db_call   # DB 호출은 예외처리까지 묶여 있다
from functions.notification_functions import notify

#────────────────────────────────────────────────┌> 실제 태스크
#
# 기능 개선 요청 게시판. payload 에 사용자 정보가 없어서 토큰으로 사용자와 권한을 가린다.
# 권한은 DB 함수도 한 번 더 검증한다 — 여기서 먼저 보는 건 토스트에 띄울 이유를 정확히 주기 위해서다.

tasks["FEATURE_REQUEST_LIST"]   = ["request_user_input", "list_db_requests", "request_list_output"]

tasks["FEATURE_REQUEST_SAVE"]   = ["request_save_input", "save_db_request", "request_output"]

tasks["FEATURE_REQUEST_DELETE"] = ["request_delete_input", "delete_db_request", "request_delete_output"]

tasks["FEATURE_REQUEST_REPLY"]  = ["request_reply_input", "reply_db_request", "request_output"]

#────────────────────────────────────────────────


def _viewer(req):
    """요청 -> (user_id, 관리자 여부).

    login_output 이 지금 user_id 를 토큰으로 내보내고 있어서 그대로 쓴다. 토큰 발급 방식이
    바뀌면 여기서 토큰을 user_id 로 바꾸는 단계가 필요하다.

    role 은 토큰에 없으므로 사용자 목록에서 찾는다(user_set_role_input 과 같은 방식).
    """
    token = req.get("token") if isinstance(req, dict) else None
    try:
        user_id = str(uuid.UUID(str(token)))
    except (ValueError, AttributeError, TypeError):
        raise ValueError("로그인이 필요합니다.")

    user = next((u for u in (db_call("list_users") or [])
                 if str(u.get("user_id")) == user_id), None)
    if not user:
        raise ValueError("사용자를 알 수 없습니다. 다시 로그인해 주세요.")
    return user_id, user.get("role") == "admin"


def _payload(req):
    return (req.get("payload") or {}) if isinstance(req, dict) else {}


def _request_id(payload):
    """payload 의 id -> DB 가 받는 정수. 클라이언트는 문자열("12")로 보낸다."""
    try:
        return int(payload.get("id"))
    except (TypeError, ValueError):
        raise ValueError("요청 글 번호가 올바르지 않습니다.")


def _find(request_id):
    row = db_call("get_feature_request", id=request_id)
    if not row:
        raise ValueError("없는 요청이거나 이미 삭제된 요청입니다.")
    return row


def _iso(value):
    """DB 의 datetime -> ISO 8601 문자열. 클라이언트가 new Date() 로 읽는다."""
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def _to_client(request):
    """FeatureRequest -> 클라이언트가 읽는 모양(camelCase). id 들은 문자열로 보낸다."""
    return {
        "id": str(request.id),
        "title": request.title,
        "content": request.content,
        "isSecret": request.is_secret,
        "authorId": str(request.author_id),
        "authorName": request.author_name,
        "createdAt": _iso(request.created_at),
        "status": request.status,
        "answer": request.answer,
        "answeredAt": _iso(request.answered_at),
    }


#------------------------------------------------┌> FEATURE_REQUEST_LIST

@work_regist("request_user_input")
def request_user_input(*args, **kwargs):
    """요청 -> (user_id, 관리자 여부). payload 는 없다."""
    return _viewer(args[0] if args else None)


@work_regist("list_db_requests")
def list_db_requests(*args, **kwargs):
    """전체 요청 글. 누가 보는지는 출력에서 가리기 위해 같이 넘긴다."""
    user_id, is_admin = args[0]
    rows = db_call("list_feature_requests")
    if rows is None:
        raise ValueError("요청 목록을 불러오지 못했습니다.")
    return rows, user_id, is_admin


@work_regist("request_list_output")
def request_list_output(*args, **kwargs):
    """행 목록 -> {requests:[...]}.

    볼 수 없는 비밀글은 목록에 남기되 제목·내용·답변을 비운다. 화면에서만 가리면
    개발자도구에서 그대로 보이므로 반드시 여기서 가린다.
    """
    rows, user_id, is_admin = args[0]
    return {"requests": [_to_client(build_request(row).for_user(user_id, is_admin))
                         for row in rows]}


#------------------------------------------------┌> FEATURE_REQUEST_SAVE

@work_regist("request_save_input")
def request_save_input(*args, **kwargs):
    """payload {id?, title, content, isSecret} + 토큰 -> 저장할 값.

    id 가 있으면 수정이다. 수정은 작성자 본인만 할 수 있다(관리자도 안 된다).
    """
    req = args[0] if args else None
    user_id, is_admin = _viewer(req)
    payload = _payload(req)

    title = (payload.get("title") or "").strip()
    content = (payload.get("content") or "").strip()
    if not title:
        raise ValueError("제목을 입력해 주세요.")
    if not content:
        raise ValueError("내용을 입력해 주세요.")

    request_id = None
    if payload.get("id"):
        request_id = _request_id(payload)
        if str(_find(request_id)["author_id"]) != user_id:
            raise ValueError("본인이 작성한 요청만 수정할 수 있습니다.")

    return {
        "id": request_id,
        "user_id": user_id,
        "is_admin": is_admin,
        "title": title,
        "content": content,
        "is_secret": bool(payload.get("isSecret")),
    }


@work_regist("save_db_request")
def save_db_request(*args, **kwargs):
    """id 가 없으면 새로 넣고, 있으면 고친다."""
    item = args[0]
    if item["id"] is None:
        row = db_call("insert_feature_request", author_id=item["user_id"], title=item["title"],
                      content=item["content"], is_secret=item["is_secret"])
    else:
        row = db_call("update_feature_request", id=item["id"], user_id=item["user_id"],
                      title=item["title"], content=item["content"], is_secret=item["is_secret"])
    if not row:
        raise ValueError("요청을 저장하지 못했습니다.")
    return row, item["user_id"], item["is_admin"]


@work_regist("request_output")
def request_output(*args, **kwargs):
    """저장·답변된 행 하나 -> {request:{...}}. SAVE 와 REPLY 가 같이 쓴다."""
    row, user_id, is_admin = args[0]
    return {"request": _to_client(build_request(row).for_user(user_id, is_admin))}


#------------------------------------------------┌> FEATURE_REQUEST_DELETE

@work_regist("request_delete_input")
def request_delete_input(*args, **kwargs):
    """payload {id} + 토큰 -> (글 번호, user_id). 작성자 본인이나 관리자만 지울 수 있다."""
    req = args[0] if args else None
    user_id, is_admin = _viewer(req)
    request_id = _request_id(_payload(req))

    if not is_admin and str(_find(request_id)["author_id"]) != user_id:
        raise ValueError("본인이 작성한 요청만 삭제할 수 있습니다.")
    return request_id, user_id


@work_regist("delete_db_request")
def delete_db_request(*args, **kwargs):
    """지운다. 실패하면 클라이언트가 목록에 되돌리도록 예외로 올린다."""
    request_id, user_id = args[0]
    if not db_call("delete_feature_request", id=request_id, user_id=user_id):
        raise ValueError("요청을 삭제하지 못했습니다.")
    return True


@work_regist("request_delete_output")
def request_delete_output(*args, **kwargs):
    """클라이언트가 result 를 읽지 않는다. status 만 본다."""
    return {}


#------------------------------------------------┌> FEATURE_REQUEST_REPLY

@work_regist("request_reply_input")
def request_reply_input(*args, **kwargs):
    """payload {id, status, answer} + 토큰 -> 답변할 값. 관리자만 할 수 있다.

    answer 가 빈 문자열이면 상태만 바꾼다 — 기존 답변은 DB 함수가 그대로 둔다.
    """
    req = args[0] if args else None
    user_id, is_admin = _viewer(req)
    if not is_admin:
        raise ValueError("관리자만 처리 상태를 바꾸고 답변할 수 있습니다.")

    payload = _payload(req)
    request_id = _request_id(payload)
    status = payload.get("status")
    if status not in STATUSES:
        raise ValueError(f"처리 상태 값이 올바르지 않습니다: {status!r}")

    return {
        "id": request_id,
        "user_id": user_id,
        "status": status,
        "answer": (payload.get("answer") or "").strip(),
    }


@work_regist("reply_db_request")
def reply_db_request(*args, **kwargs):
    item = args[0]
    row = db_call("answer_feature_request", id=item["id"], admin_user_id=item["user_id"],
                  status=item["status"], answer=item["answer"])
    if not row:
        raise ValueError("답변을 저장하지 못했습니다. 이미 삭제된 요청일 수 있습니다.")
    # 작성자에게 알린다. 관리자가 자기 글에 답한 경우는 알릴 필요가 없다.
    if str(row["author_id"]) != item["user_id"]:
        notify(row["author_id"], f"기능 개선 요청 \"{row['title']}\"에 답변이 등록되었습니다.",
               "info", "/feature-requests")
    return row, item["user_id"], True
