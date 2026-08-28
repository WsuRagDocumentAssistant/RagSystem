
#================================================
# user_functions.py
#================================================

import os

from dotenv import load_dotenv

from taskcontroller import work_regist, tasks
from data_functions import db_call   # DB 호출은 예외처리까지 묶여 있다

load_dotenv()

# 통신모듈 붙기 전까지 첫 work 에 입력을 넣어주는 자리
TEST_LOGIN_ID = os.getenv("TEST_LOGIN_ID", "")
TEST_PASSWORD = os.getenv("TEST_PASSWORD", "")
TEST_NAME     = os.getenv("TEST_NAME", "")
TEST_ROLE     = os.getenv("TEST_ROLE", "user")   # "admin" 또는 "user"

#────────────────────────────────────────────────

# 로그인 검증
tasks["login"] = ["test_login_input", "login_user"]
# 계정 생성
tasks["create_user_account"] = ["test_account_input", "create_account"]

#------------------------------------------------┌> dummy function

# login_id, password
@work_regist("test_login_input")
def test_login_input(*args, **kwargs):
    return TEST_LOGIN_ID, TEST_PASSWORD

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
