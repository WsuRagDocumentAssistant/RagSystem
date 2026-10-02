#================================================
# notification_functions.py
#================================================
"""
사용자 알림(상단 종 아이콘). 저장은 DB(notifications 테이블)에 한다.

알림이 생기는 곳은 두 가지다.
  - 서버에서 끝나는 일: 문서 색인 완료·실패(document_functions.file_upload_job),
    기능 개선 요청 답변(request_functions.reply_db_request). notify() 를 부른다.
  - 화면에서 끝나는 일: 검색어 저장, 외부 API 등록 같은 내 작업의 결과. 화면이
    NOTIFICATION_CREATE 로 남긴다.

토큰이 곧 user_id 인 임시 구조라 요청의 token 을 그대로 user_id 로 쓴다(login_output 참고).
"""

import logging

from taskcontroller import work_regist, tasks
from functions.data_functions import db_call   # DB 호출은 예외처리까지 묶여 있다

logger = logging.getLogger(__name__)

#────────────────────────────────────────────────┌> 실제 태스크

tasks["NOTIFICATION_LIST"]   = ["notification_list_input", "list_db_notifications",
                                "notification_list_output"]

# payload {ids?: [id, ...]} — ids 가 없으면 전부 읽음
tasks["NOTIFICATION_READ"]   = ["notification_read_input", "read_db_notifications",
                                "notification_read_output"]

# payload {message, type?, link?}
tasks["NOTIFICATION_CREATE"] = ["notification_create_input", "create_db_notification",
                                "notification_output"]

# 화면에 보여줄 개수. 사용자마다 이보다 많이 쌓이면 오래된 것부터 지운다(NOTIFICATION_KEEP).
NOTIFICATION_LIMIT = 50
NOTIFICATION_KEEP = 200

TYPES = {"success", "error", "info"}

#────────────────────────────────────────────────


def notify(user_id, message: str, type: str = "info", link: str | None = None) -> None:
    """알림 하나를 남긴다. 다른 work 이 일을 마친 뒤 부른다.

    실패해도 예외를 올리지 않는다 — 알림 때문에 색인·답변 저장이 실패로 보이면 안 된다.
    user_id 가 없으면(통신부를 거치지 않은 내부 작업) 아무것도 하지 않는다.
    """
    if not user_id:
        return
    if db_call("insert_notification", user_id=str(user_id), message=message,
               type=type if type in TYPES else "info", link=link) is None:
        logger.warning(f"[notify] 알림을 남기지 못했습니다: user={user_id} {message!r}")


def _user_id(req) -> str:
    user_id = req.get("token") if isinstance(req, dict) else None
    if not user_id:
        raise ValueError("사용자를 알 수 없습니다. 다시 로그인해 주세요.")
    return user_id


def _to_client(row: dict) -> dict:
    """DB 행 -> 화면이 읽는 {id, message, type, link, createdAt(ms), read}"""
    return {
        "id": str(row["id"]),
        "message": row["message"],
        "type": row["type"],
        "link": row.get("link"),
        "createdAt": int(row["created_at"].timestamp() * 1000),
        "read": row.get("read_at") is not None,
    }


#------------------------------------------------┌> NOTIFICATION_LIST

@work_regist("notification_list_input")
def notification_list_input(*args, **kwargs):
    return _user_id(args[0])


@work_regist("list_db_notifications")
def list_db_notifications(*args, **kwargs):
    """user_id -> 알림 행 목록. 실패면 이유를 알린다(테이블이 없는 등)."""
    rows = db_call("list_notifications", user_id=args[0], limit=NOTIFICATION_LIMIT)
    if rows is None:
        raise ValueError("알림을 불러오지 못했습니다. DBManager/sql/notifications.sql 적용 여부를 확인해 주세요.")
    return rows


@work_regist("notification_list_output")
def notification_list_output(*args, **kwargs):
    return {"notifications": [_to_client(row) for row in args[0]]}


#------------------------------------------------┌> NOTIFICATION_READ

@work_regist("notification_read_input")
def notification_read_input(*args, **kwargs):
    """요청 -> (user_id, ids 또는 None)"""
    req = args[0]
    ids = (req.get("payload") or {}).get("ids")
    if ids is not None:
        try:
            ids = [int(i) for i in ids]
        except (TypeError, ValueError):
            raise ValueError(f"알림 id 가 올바르지 않습니다: {ids!r}")
    return _user_id(req), ids


@work_regist("read_db_notifications")
def read_db_notifications(*args, **kwargs):
    user_id, ids = args[0]
    return db_call("mark_notifications_read", user_id=user_id, ids=ids)


@work_regist("notification_read_output")
def notification_read_output(*args, **kwargs):
    if args[0] is None:
        raise ValueError("알림을 읽음으로 바꾸지 못했습니다.")
    return {"updated": args[0]}


#------------------------------------------------┌> NOTIFICATION_CREATE

@work_regist("notification_create_input")
def notification_create_input(*args, **kwargs):
    """요청 -> (user_id, message, type, link)"""
    req = args[0]
    user_id = _user_id(req)
    payload = req.get("payload") or {}
    message = (payload.get("message") or "").strip()
    if not message:
        raise ValueError("알림 내용(message)이 비어 있습니다.")
    kind = payload.get("type") or "info"
    if kind not in TYPES:
        raise ValueError(f"알림 종류(type)는 {sorted(TYPES)} 중 하나여야 합니다: {kind!r}")
    return user_id, message[:500], kind, payload.get("link")


@work_regist("create_db_notification")
def create_db_notification(*args, **kwargs):
    user_id, message, kind, link = args[0]
    return db_call("insert_notification", user_id=user_id, message=message, type=kind, link=link)


@work_regist("notification_output")
def notification_output(*args, **kwargs):
    if not args[0]:
        raise ValueError("알림을 저장하지 못했습니다.")
    return {"notification": _to_client(args[0])}


#------------------------------------------------┌> 정리 (타이머)

tasks["notifications_prune"] = ["prune_db_notifications"]


@work_regist("prune_db_notifications")
def prune_db_notifications(*args, **kwargs):
    """사용자마다 최신 NOTIFICATION_KEEP 개만 남긴다. 지운 개수(실패면 None)."""
    return db_call("prune_notifications", keep=NOTIFICATION_KEEP)
