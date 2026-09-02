
#================================================
# user_functions.py
#================================================

import os

from dotenv import load_dotenv

from taskcontroller import work_regist, tasks
from functions.data_functions import db_call   # DB 호출은 예외처리까지 묶여 있다

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

# 로그인 검증
tasks["login"] = ["test_login_input", "login_user"]
# 계정 생성
tasks["create_user_account"] = ["test_account_input", "create_account"]
# 권한 변경
tasks["update_user_role"] = ["test_role_input", "update_user_role"]

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

tasks["LOGIN"]    = ["login_input", "login_user", "login_output"]


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
            "provider": "local",
            "created_at": None,
        },
    }


# 회원가입/로그아웃은 클라이언트가 result 를 읽지 않는다. status 만 본다.
tasks["REGISTER"] = ["register_input", "create_account", "register_output"]
tasks["LOGOUT"]   = ["logout_output"]

tasks["USER_LIST"]     = ["list_users", "user_list_output"]
# 클라이언트는 바꿀 대상을 email 로 보낸다(payload {email, role}). DB 는 uuid 를
# 받으므로 목록에서 email 로 찾아 바꿔준다.
tasks["USER_SET_ROLE"] = ["user_set_role_input", "set_user_role",
                          "user_set_role_output"]


@work_regist("list_users")
def list_users(*args, **kwargs):
    """전체 사용자 행 목록. payload 가 없다."""
    return db_call("list_users") or []


@work_regist("user_list_output")
def user_list_output(*args, **kwargs):
    """사용자 행 -> 클라이언트가 읽는 {users:[{id, email, name, role}]}.

    DB 는 login_id 로 부르고 클라이언트는 email 로 읽는다.
    id 는 uuid 문자열이다 — 클라이언트 타입이 number 로 선언돼 있지만 화면에서
    행 구분에만 쓰므로 문자열이어도 동작한다.
    """
    rows = args[0] or []
    return {"users": [
        {
            "id": str(row.get("user_id")),
            "email": row.get("login_id"),
            "name": row.get("name"),
            "role": row.get("role"),
        }
        for row in rows
    ]}


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
