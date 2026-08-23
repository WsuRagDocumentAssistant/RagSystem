
#================================================
# data_functions.py
#================================================

import asyncio
import os
from types import SimpleNamespace

from dotenv import load_dotenv

from taskcontroller import work_regist, tasks
from session_data import build_session, Session
from api_data import collect, ApiEntity
import db_manager

load_dotenv()   # .env를 os.environ에 올린다 (없으면 조용히 넘어감)

# 인증키는 .env의 DATA_GO_KR_SERVICE_KEY에서 읽는다.
# 비어 있으면 XmlApiService가 "인증키(service_key)가 필요합니다"로 알려준다.
SERVICE_KEY = os.getenv("DATA_GO_KR_SERVICE_KEY", "")
SURVEY_YEAR = None  # None이면 데이터가 있는 최신 조사연도를 자동으로 고른다

dbmanager = db_manager.DBManager()
dbmanager.init()

#────────────────────────────────────────────────

# session-data
# session insert
tasks["session_insert"] = ["test_session_id", "create_session"]
# session save
tasks["session_save"] = ["test_session_data", "get_session", "insert_db_session_data"]

# api-data
tasks["api_save"] = ["create_api_data", "insert_db_api_data"]


#------------------------------------------------┌> dummy function

# 통신모듈 붙기 전까지 첫 work 에 입력을 넣어주는 자리
TEST_SESSION_ID = "8606be9d-1955-4c57-a95d-06ecc72c268c"

# session_id 하나
@work_regist("test_session_id")
def test_session_id(*args, **kwargs):
    return TEST_SESSION_ID

# session_id + Session 을 함께 들고 다니는 객체
@work_regist("test_session_data")
def test_session_data(*args, **kwargs):
    session = build_session(
        [{"user_query": "포도는요?", "ai_response": "포도는 여름 끝에 수확합니다..."}],
        "포도 수확기",
        "과일 재배 문의",
    )
    return SimpleNamespace(session_id=TEST_SESSION_ID, session=session)

#------------------------------------------------┌> session insert func

# 세션 객체 생성
@work_regist("create_session")
def create_session_data(*args,**kwargs):
    #session_id가 들어왔다 가정
    messages = dbmanager.call("get_recent_messages", session_id=args[0])
    context = dbmanager.call("get_session_context", session_id=args[0])
    return build_session(messages, context["current_topic"], context["overall_summary"])

#------------------------------------------------┌> session save func

# 새 세션의 대한 가공은 이전에 이미 되어있다 가정

# 세션 객체 획득
@work_regist("get_session")
def get_session_data(*args, **kwargs):
    #session_id, session
    session_data = args[0]
    return session_data

# DB에 저장
@work_regist("insert_db_session_data")
def insert_db_session_data(*args, **kwargs):
    inserted_message = dbmanager.call("insert_message", session_id=args[0].session_id, user_query=args[0].session.recent_conversations[-1]["user_query"], ai_response=args[0].session.recent_conversations[-1]["ai_response"])
    updated_topic = dbmanager.call("update_current_topic", session_id=args[0].session_id, topic=args[0].session.current_topic)
    updated_summary = dbmanager.call("update_overall_summary", session_id=args[0].session_id, summary=args[0].session.summary)
    return inserted_message, updated_topic, updated_summary

#-----------------------------------------------┌> api func

# api 실제 데이터로 객체 생성
@work_regist("create_api_data")
def api_data(*args, **kwargs) -> ApiEntity:
    return asyncio.run(collect(SERVICE_KEY, SURVEY_YEAR))

# DB에 저장
@work_regist("insert_db_api_data")
def insert_db_api_data(*args, **kwargs):
    inserted_api_data = dbmanager.call("insert_api_data", metadata=args[0].metadata, json=args[0].json)
    return inserted_api_data
