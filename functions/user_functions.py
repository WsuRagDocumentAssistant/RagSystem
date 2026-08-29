
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
