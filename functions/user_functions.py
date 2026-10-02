
#================================================
# user_functions.py
#================================================

import os

from dotenv import load_dotenv

from taskcontroller import work_regist, tasks
from functions.data_functions import db_call, db_call_or_raise   # DB 호출은 예외처리까지 묶여 있다

#────────────────────────────────────────────────┌> 테스트 태스크

# 로그인 검증
tasks["login"] = ["test_login_input", "login_user"]

# 계정 생성
tasks["create_user_account"] = ["test_account_input", "create_account"]

# 권한 변경
tasks["update_user_role"] = ["test_role_input", "update_user_role"]

tasks["LOGIN"]    = ["login_input", "login_user", "login_output"]

#────────────────────────────────────────────────┌> 실제 태스크

# 회원가입/로그아웃은 클라이언트가 result 를 읽지 않는다. status 만 본다.
tasks["REGISTER"] = ["register_input", "create_account", "register_output"]

tasks["LOGOUT"]   = ["logout_output"]

# 학교 사용자 정보는 타이머가 학교 DB 뷰를 PostgreSQL 사본(school_users)으로 주기적으로 복사하고
# (main.py TIMER_JOBS), 화면 요청은 그 사본만 읽는다. 학교 DB 가 꺼져도 마지막 사본으로 동작한다.
tasks["school_users_sync"] = ["sync_school_users"]

# 소속·구분은 사본에서 채운다(계정의 login_id = 학번/교번). 사본에 없으면 빈칸으로 둔다.
# 역할과 별개인 권한(문서 정보 입력 등)도 같이 싣는다.
tasks["USER_LIST"]     = ["list_users", "attach_user_info", "user_list_output"]

# 관리자 화면의 "사용자 검색". 학교 구성원을 찾고, 이미 계정이 있으면 그 역할을 같이 준다.
tasks["SCHOOL_USER_SEARCH"] = ["school_search_input", "search_school_users",
                               "school_search_output"]

# 관리자 화면의 "지금 동기화" 버튼. 타이머를 기다리지 않고 바로 사본을 맞춘다.
# 실패하면 이유(동기화 꺼짐·접속 정보 없음·접속 거절 등)를 화면에 그대로 보여준다.
tasks["SCHOOL_USER_SYNC"] = ["admin_input", "sync_school_users_now", "school_sync_output"]

# 역할과 별개인 권한 주기/회수. payload {email, permission, enabled}
tasks["USER_SET_PERMISSION"] = ["user_set_permission_input", "set_user_permission",
                                "user_set_permission_output"]

# 클라이언트는 바꿀 대상을 email 로 보낸다(payload {email, role}). DB 는 uuid 를
# 받으므로 목록에서 email 로 찾아 바꿔준다.
tasks["USER_SET_ROLE"] = ["user_set_role_input", "set_user_role",
                          "user_set_role_output"]


load_dotenv()

# 통신모듈 붙기 전까지 첫 work 에 입력을 넣어주는 자리
TEST_LOGIN_ID = os.getenv("TEST_LOGIN_ID", "")
TEST_PASSWORD = os.getenv("TEST_PASSWORD", "")
TEST_NAME     = os.getenv("TEST_NAME", "")
TEST_ROLE     = os.getenv("TEST_ROLE", "user")   # "admin" 또는 "user"

# 권한 변경용 (비밀값이 아니라 상수로 둔다)
TEST_ADMIN_USER_ID  = "957d827a-78f2-4a52-bc24-7c1cbec27a96"   # 관리자 (admin@wsu.ac.kr)
TEST_TARGET_USER_ID = "ab8eccc9-c642-4238-8718-453a2d0b236c"   # 일반유저 (user@wsu.ac.kr)
TEST_NEW_ROLE       = "user"   # "admin" 또는 "user"

#────────────────────────────────────────────────


#------------------------------------------------┌> dummy function

# login_id, password
@work_regist("test_login_input")
def test_login_input(*args, **kwargs):
    return TEST_LOGIN_ID, TEST_PASSWORD

# admin_user_id, target_user_id, new_role
@work_regist("test_role_input")
def test_role_input(*args, **kwargs):
    return TEST_ADMIN_USER_ID, TEST_TARGET_USER_ID, TEST_NEW_ROLE

# name, login_id, password, role
@work_regist("test_account_input")
def test_account_input(*args, **kwargs):
    return TEST_NAME, TEST_LOGIN_ID, TEST_PASSWORD, TEST_ROLE

#------------------------------------------------┌> user func

# 로그인 검증. 일치하면 사용자 정보, 아니면 None
@work_regist("login_user")
def login_user(*args, **kwargs):
    login_id, password = args[0]
    logined_user = db_call("login", login_id=login_id, password=password)
    return logined_user

# 계정 생성. 비밀번호 암호화는 DB 프로시저가 한다
@work_regist("create_account")
def create_account(*args, **kwargs):
    name, login_id, password, role = args[0]
    created_user = db_call("create_user_account", name=name, login_id=login_id, password=password, role=role)
    return created_user

# 권한 변경. 호출자가 admin 인지 DB 가 검증한다
@work_regist("update_user_role")
def update_user_role(*args, **kwargs):
    admin_user_id, target_user_id, new_role = args[0]
    updated_role = db_call("update_user_role", admin_user_id=admin_user_id, target_user_id=target_user_id, new_role=new_role)
    return updated_role

#────────────────────────────────────────────────┌> 통신부 task (명세 task_type)
#
# 클라이언트가 보내는 payload 를 각 work 이 읽는 모양으로 바꾼다. 위쪽 test_*_input 이
# "통신모듈 붙기 전까지 입력을 넣어주는 자리" 였고, 이제 그 자리를 payload 가 채운다.
# 이름은 클라이언트(src/config/TaskType.js)가 보내는 그대로 쓴다.



@work_regist("login_input")
def login_input(*args, **kwargs):
    """요청 {payload, session_id, token} -> login_user 가 읽는 (login_id, password)"""
    payload = args[0].get("payload") or {}
    return payload["email"], payload["password"]


@work_regist("register_input")
def register_input(*args, **kwargs):
    """payload {email, password, name} -> create_account 가 읽는 (name, login_id, password, role)

    명세에 role 이 없다. 회원가입은 항상 일반 사용자로 만들고, 권한 승격은
    USER_SET_ROLE 로만 하게 둔다 — payload 로 role 을 받으면 아무나 admin 으로
    가입할 수 있다.
    """
    payload = args[0].get("payload") or {}
    return payload["name"], payload["email"], payload["password"], "user"


@work_regist("login_output")
def login_output(*args, **kwargs):
    """login_user 의 DB 행 -> 클라이언트가 읽는 {access_token, user}.

    AppState.login 이 data.access_token 과 data.user 를 바로 꺼내 쓴다. 둘 중 하나가
    없으면 예외도 안 나고 user 가 undefined 로 남아서, 로그인 화면에서 조용히
    되돌아온다(실제로 겪었다).

    실패는 예외로 올린다. 성공 status 에 null 을 실어 보내면 클라이언트가 그걸
    더미 계정 로그인으로 흘려버려서, 비밀번호가 틀렸는데 들어가진 것처럼 보인다.

    [임시] access_token 에 user_id 를 그대로 쓴다. 토큰 발급이 정해지기 전까지의
    자리표시자다. 남의 user_id 를 Authorization 헤더에 넣으면 그 사람으로 행세할 수
    있으므로, 토큰을 검증하는 work 이 생기기 전에 배포되면 안 된다.
    """
    row = args[0]
    if not row:
        raise ValueError("이메일 또는 비밀번호가 올바르지 않습니다.")

    user_id = str(row["user_id"])
    return {
        "access_token": user_id,
        "user": {
            "id": user_id,
            "email": row.get("login_id"),
            "name": row.get("name"),
            "role": row.get("role"),
            "permissions": sorted(_permissions_by_user(user_id).get(user_id, ())),
            "provider": "local",
            "created_at": None,
        },
    }


# 역할과 별개로 주는 권한. 이름은 sql/user_permissions.sql 의 CHECK 와 같아야 한다.
PERMISSIONS = {"document_input"}   # 문서 정보 입력 (문서 등록(비정형) 화면)


def _permissions_by_user(user_id=None) -> dict:
    """{user_id: {권한, ...}}. 조회에 실패하면(테이블이 아직 없는 등) 빈 dict — 권한 표시 때문에
    로그인·목록이 막히면 안 된다."""
    by_user = {}
    for row in db_call("list_user_permissions", user_id=user_id) or []:
        by_user.setdefault(str(row["user_id"]), set()).add(row["permission"])
    return by_user





@work_regist("list_users")
def list_users(*args, **kwargs):
    """전체 사용자 행 목록. payload 가 없다."""
    return db_call("list_users") or []


def _school_index(people) -> dict:
    """학교 사용자 행을 학번/교번과 이메일(소문자) 둘 다로 찾을 수 있게 한다.

    계정의 login_id 는 학번/교번이 원칙이지만, 예전 계정은 이메일로 만들어져 있다.
    """
    index = {}
    for person in people or []:
        for key in (person.get("user_id"), (person.get("email") or "").lower()):
            if key:
                index.setdefault(key, person)
    return index


def _school_of(index: dict, login_id) -> dict:
    login_id = login_id or ""
    return index.get(login_id) or index.get(login_id.lower()) or {}


@work_regist("attach_user_info")
def attach_user_info(*args, **kwargs):
    """사용자 행 -> (사용자 행, 학교 사용자 인덱스, 권한). 학교 사용자는 사본(school_users)에서 읽는다.

    사본 조회에 실패하면 db_call 이 None 을 돌려준다. 그때는 소속을
    빈칸으로 두고 목록은 그대로 보여준다 — 소속 때문에 권한 관리 화면이 막히면 안 된다.
    """
    rows = args[0] or []
    login_ids = [row["login_id"] for row in rows if row.get("login_id")]
    people = db_call("get_school_users", user_ids=login_ids) if login_ids else []
    return rows, _school_index(people), _permissions_by_user()


@work_regist("user_list_output")
def user_list_output(*args, **kwargs):
    """(사용자 행, 학교 인덱스, 권한) -> 클라이언트가 읽는
    {users:[{id, email, name, department, status, role, permissions}]}.

    DB 는 login_id 로 부르고 클라이언트는 email 로 읽는다(화면 표기는 "교번").
    id 는 uuid 문자열이다 — 클라이언트 타입이 number 로 선언돼 있지만 화면에서
    행 구분에만 쓰므로 문자열이어도 동작한다.
    """
    rows, index, permissions = args[0]
    users = []
    for row in rows:
        school = _school_of(index, row.get("login_id"))
        user_id = str(row.get("user_id"))
        users.append({
            "id": user_id,
            "email": row.get("login_id"),
            "name": row.get("name") or school.get("name"),
            "department": school.get("department"),
            "status": school.get("status"),
            "role": row.get("role"),
            "permissions": sorted(permissions.get(user_id, ())),
        })
    return {"users": users}


def _require_admin(req: dict) -> list:
    """토큰의 주인이 관리자인지 확인하고, 확인에 쓴 전체 계정 목록을 돌려준다.

    학교 사용자 사본에는 학생 개인정보가 있어서 관리자만 검색할 수 있다. 토큰이 곧 user_id 인
    임시 구조라 계정 목록에서 그 user_id 의 role 을 본다.
    """
    accounts = db_call("list_users") or []
    me = next((a for a in accounts if str(a.get("user_id")) == req.get("token")), None)
    if not me or me.get("role") != "admin":
        raise ValueError("관리자만 사용할 수 있습니다.")
    return accounts


@work_regist("admin_input")
def admin_input(*args, **kwargs):
    """요청 -> 요청 그대로. 관리자가 아니면 ValueError."""
    req = args[0] if args and isinstance(args[0], dict) else {}
    _require_admin(req)
    return req


@work_regist("school_search_input")
def school_search_input(*args, **kwargs):
    """요청 {payload:{keyword}, token} -> (keyword, 전체 계정 목록).

    한 글자도 받는다 — 성씨 하나("김")로 찾는 일이 흔하다. 결과는 50명에서 자른다.
    """
    req = args[0] if args and isinstance(args[0], dict) else {}
    keyword = ((req.get("payload") or {}).get("keyword") or "").strip()
    if not keyword:
        raise ValueError("검색어를 입력하세요.")
    return keyword, _require_admin(req)


def _school_copy_status() -> dict:
    """사본 상태 {count, synced_at}. 테이블·함수가 없으면(SQL 미적용) 이유를 담아 ValueError."""
    status = db_call("school_users_status")
    if status is None:
        raise ValueError("학교 사용자 사본 테이블이 없습니다. "
                         "DBManager/sql/school_users.sql 을 DB에 적용해 주세요.")
    return status


def _status_output(status: dict) -> dict:
    """사본 상태 -> 화면이 읽는 {count, syncedAt}"""
    synced_at = status.get("synced_at")
    return {"count": status.get("count") or 0,
            "syncedAt": synced_at.isoformat() if synced_at else None}


@work_regist("search_school_users")
def search_school_users(*args, **kwargs):
    """(keyword, 계정 목록) -> (학교 사용자 행, 계정 목록, 사본 상태).

    검색이 비면 그게 "그런 사람이 없다" 인지 "사본이 아직 비었다" 인지 구분해서 알린다 —
    둘 다 빈 목록이라 화면에서는 똑같이 "결과 없음" 으로 보인다.
    """
    keyword, accounts = args[0]
    status = _school_copy_status()
    if not status["count"]:
        raise ValueError("학교 사용자 사본이 비어 있습니다. 학교 DB 연결(SCHOOL_SYNC_ENABLED)을 확인하고 "
                         "'지금 동기화'를 눌러 주세요.")
    people = db_call("search_school_users", keyword=keyword)
    if people is None:
        raise ValueError("학교 사용자 정보를 조회하지 못했습니다.")
    return people, accounts, status


@work_regist("sync_school_users")
def sync_school_users(*args, **kwargs):
    """타이머 작업. 학교 DB 뷰 전체를 PostgreSQL 사본에 맞추고 반영한 행 수를 돌려준다.

    학교 DB 가 꺼져 있거나 실패하면 db_call 이 이유를 한 줄 찍고 None 을 돌려준다 — 사본은
    그대로 남고 다음 주기에 다시 시도한다.
    """
    return db_call("sync_school_users")


@work_regist("sync_school_users_now")
def sync_school_users_now(*args, **kwargs):
    """관리자의 "지금 동기화". 타이머 작업과 같지만 실패 이유를 ValueError 로 올린다."""
    try:
        return db_call_or_raise("sync_school_users")
    except ValueError as e:
        raise ValueError(f"학교 DB에서 사용자를 가져오지 못했습니다 — {e}") from e


@work_regist("school_sync_output")
def school_sync_output(*args, **kwargs):
    """반영한 행 수 -> {count, syncedAt}"""
    return _status_output(_school_copy_status())


@work_regist("school_search_output")
def school_search_output(*args, **kwargs):
    """-> {users:[{id, name, department, college, status, account}]}.

    account 는 이미 가입한 사람만 {email, role} 이고, 아니면 null 이다. 화면은 account 가
    있으면 그 email 로 USER_SET_ROLE 을 불러 역할을 바꾼다.
    """
    people, accounts, status = args[0]
    by_login = {a["login_id"].lower(): a for a in accounts if a.get("login_id")}
    users = []
    for person in people:
        keys = (person.get("user_id"), person.get("email"))
        account = next((by_login[k.lower()] for k in keys if k and k.lower() in by_login), None)
        users.append({
            "id": person["user_id"],
            "name": person.get("name"),
            "department": person.get("department"),
            "college": person.get("college"),
            "status": person.get("status"),
            "account": {"email": account["login_id"], "role": account["role"]} if account else None,
        })
    return {"users": users, "copy": _status_output(status)}


@work_regist("user_set_role_input")
def user_set_role_input(*args, **kwargs):
    """payload {email, role} + 토큰 -> (관리자 uuid, 대상 uuid, 새 role).

    호출자가 admin 인지는 DB 함수가 admin_user_id 로 검증한다. 토큰이 곧 user_id 인
    임시 구조라 그대로 넘긴다 — 토큰 발급 방식이 바뀌면 여기서 변환이 필요하다.
    """
    req = args[0] if args and isinstance(args[0], dict) else {}
    payload = req.get("payload") or {}
    email, role = payload.get("email"), payload.get("role")

    if role not in ("admin", "user"):
        raise ValueError(f"role 은 admin 또는 user 여야 합니다: {role!r}")

    admin_user_id = req.get("token")
    if not admin_user_id:
        raise ValueError("사용자를 알 수 없습니다. Authorization 헤더가 필요합니다.")

    # 클라이언트가 email 로 지목하므로 uuid 를 찾아준다.
    target = next((r for r in (db_call("list_users") or [])
                   if r.get("login_id") == email), None)
    if not target:
        raise ValueError(f"그런 사용자가 없습니다: {email!r}")

    return admin_user_id, str(target["user_id"]), role


@work_regist("set_user_role")
def set_user_role(*args, **kwargs):
    """권한을 바꾼다. DB 가 {success, message} 를 돌려준다."""
    admin_user_id, target_user_id, new_role = args[0]
    return db_call("update_user_role", admin_user_id=admin_user_id,
                   target_user_id=target_user_id, new_role=new_role)


@work_regist("user_set_role_output")
def user_set_role_output(*args, **kwargs):
    """{success, message} -> {}. 실패면 DB 가 준 이유를 그대로 올린다.

    admin 이 아닌 사용자가 부르면 DB 가 success=False 로 거절한다. 그걸 성공으로
    넘기면 화면에는 권한이 바뀐 것처럼 보이고 실제로는 안 바뀐다.
    """
    result = args[0] or {}
    if not result.get("success"):
        raise ValueError(result.get("message") or "권한을 변경하지 못했습니다.")
    return {}


@work_regist("register_output")
def register_output(*args, **kwargs):
    """생성된 계정 행 -> {}. 실패면 예외로 올린다."""
    if not args[0]:
        raise ValueError("계정 생성에 실패했습니다. 이미 있는 이메일인지 확인하세요.")
    return {}


@work_regist("logout_output")
def logout_output(*args, **kwargs):
    """서버에 지울 세션 상태가 없다. 토큰은 클라이언트가 localStorage 에서 지운다."""
    return {}


@work_regist("user_set_permission_input")
def user_set_permission_input(*args, **kwargs):
    """payload {email, permission, enabled} + 토큰 -> (관리자 uuid, 대상 uuid, 권한, 켜기/끄기).

    대상은 USER_SET_ROLE 처럼 email(=login_id)로 지목한다. 관리자인지는 DB 함수가 다시 확인한다.
    """
    req = args[0] if args and isinstance(args[0], dict) else {}
    payload = req.get("payload") or {}
    email, permission = payload.get("email"), payload.get("permission")

    if permission not in PERMISSIONS:
        raise ValueError(f"알 수 없는 권한입니다: {permission!r}")

    admin_user_id = req.get("token")
    if not admin_user_id:
        raise ValueError("사용자를 알 수 없습니다. Authorization 헤더가 필요합니다.")

    target = next((r for r in (db_call("list_users") or [])
                   if r.get("login_id") == email), None)
    if not target:
        raise ValueError(f"그런 사용자가 없습니다: {email!r}")

    return admin_user_id, str(target["user_id"]), permission, bool(payload.get("enabled"))


@work_regist("set_user_permission")
def set_user_permission(*args, **kwargs):
    """권한을 주거나 회수한다. DB 가 {success, message} 를 돌려준다."""
    admin_user_id, target_user_id, permission, enabled = args[0]
    return db_call("set_user_permission", admin_user_id=admin_user_id, target_user_id=target_user_id,
                   permission=permission, enabled=enabled)


@work_regist("user_set_permission_output")
def user_set_permission_output(*args, **kwargs):
    """{success, message} -> {}. 실패면 이유를 올린다 — 테이블이 없으면 db_call 이 None 을 준다."""
    result = args[0]
    if result is None:
        raise ValueError("권한을 저장하지 못했습니다. DBManager/sql/user_permissions.sql 적용 여부를 확인해 주세요.")
    if not result.get("success"):
        raise ValueError(result.get("message") or "권한을 변경하지 못했습니다.")
    return {}
