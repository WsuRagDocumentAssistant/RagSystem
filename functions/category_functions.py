#================================================
# category_functions.py
#================================================
"""
문서 등록(비정형) 화면의 입력 카테고리 (document_categories 테이블).

조회는 문서 등록 화면이 쓰므로 로그인한 사용자 누구나, 추가·삭제는 설정 관리 화면의 관리자만.
관리자인지는 DB 함수도 한 번 더 확인한다.
"""

from taskcontroller import work_regist, tasks
from functions.data_functions import db_call   # DB 호출은 예외처리까지 묶여 있다
from functions.user_functions import _require_admin

#────────────────────────────────────────────────┌> 실제 태스크

tasks["DOCUMENT_CATEGORY_LIST"]   = ["list_db_categories", "category_list_output"]

# payload {kind, value, parent?, pair?}
tasks["DOCUMENT_CATEGORY_SAVE"]   = ["category_save_input", "save_db_category", "category_output"]

# payload {id}
tasks["DOCUMENT_CATEGORY_DELETE"] = ["category_delete_input", "delete_db_category",
                                     "category_delete_output"]

# kind -> 상위(parent)가 무엇이어야 하는가. None 이면 상위가 없다.
KINDS = {
    "work_category": None,
    "task": "work_category",
    "department": "work_category",
    "report_type": None,
}

#────────────────────────────────────────────────


def _to_client(row: dict) -> dict:
    return {
        "id": str(row["id"]),
        "kind": row["kind"],
        "parent": row["parent"] or "",
        "value": row["value"],
        "pair": row.get("pair"),
    }


@work_regist("list_db_categories")
def list_db_categories(*args, **kwargs):
    """전체 카테고리. 실패면 이유를 알린다 — 화면은 그때 기본값으로 대신한다."""
    rows = db_call("list_document_categories")
    if rows is None:
        raise ValueError("문서 카테고리를 불러오지 못했습니다. "
                         "DBManager/sql/document_categories.sql 적용 여부를 확인해 주세요.")
    return rows


@work_regist("category_list_output")
def category_list_output(*args, **kwargs):
    return {"categories": [_to_client(row) for row in args[0]]}


@work_regist("category_save_input")
def category_save_input(*args, **kwargs):
    """요청 -> 저장할 값 {admin_user_id, kind, parent, value, pair}. 관리자가 아니면 ValueError."""
    req = args[0]
    _require_admin(req)
    payload = req.get("payload") or {}

    kind = payload.get("kind")
    if kind not in KINDS:
        raise ValueError(f"알 수 없는 카테고리 종류입니다: {kind!r}")
    value = (payload.get("value") or "").strip()
    if not value:
        raise ValueError("값을 입력하세요.")

    parent = (payload.get("parent") or "").strip()
    if KINDS[kind] and not parent:
        raise ValueError("업무구분을 선택하세요.")
    if not KINDS[kind]:
        parent = ""

    pair = (payload.get("pair") or "").strip() if kind == "task" else ""
    return {"admin_user_id": req["token"], "kind": kind, "parent": parent, "value": value, "pair": pair}


@work_regist("save_db_category")
def save_db_category(*args, **kwargs):
    return db_call("save_document_category", **args[0])


@work_regist("category_output")
def category_output(*args, **kwargs):
    if not args[0]:
        raise ValueError("카테고리를 저장하지 못했습니다.")
    return {"category": _to_client(args[0])}


@work_regist("category_delete_input")
def category_delete_input(*args, **kwargs):
    """요청 -> (관리자 uuid, 카테고리 id)"""
    req = args[0]
    _require_admin(req)
    category_id = (req.get("payload") or {}).get("id")
    if not str(category_id or "").isdigit():
        raise ValueError(f"카테고리 id 가 올바르지 않습니다: {category_id!r}")
    return req["token"], int(category_id)


@work_regist("delete_db_category")
def delete_db_category(*args, **kwargs):
    admin_user_id, category_id = args[0]
    return db_call("delete_document_category", admin_user_id=admin_user_id, id=category_id)


@work_regist("category_delete_output")
def category_delete_output(*args, **kwargs):
    if not args[0]:
        raise ValueError("카테고리를 지우지 못했습니다. 이미 지워졌을 수 있습니다.")
    return {}
