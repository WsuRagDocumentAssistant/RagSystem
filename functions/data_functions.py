
#================================================
# data_functions.py
#================================================

import asyncio
import logging
import os
from types import SimpleNamespace

from dotenv import load_dotenv

from taskcontroller import work_regist, tasks
from session_data import build_session, Session
from api_data import collect, ApiEntity
import db_manager
from functions.exception_functions import safe_call

load_dotenv()   # .env를 os.environ에 올린다 (없으면 조용히 넘어감)

# 워커가 basicConfig(level=INFO) 로 루트 로거를 열기 때문에 httpx 가 요청마다
# url 을 통째로 찍는다. url 에 인증키가 들어 있어 콘솔에 그대로 노출된다.
logging.getLogger("httpx").setLevel(logging.WARNING)

# 호출할 api 정보 하나. collect() 는 request.url 을 GET 만 하므로 인증키는 url 안에 있어야 한다.
API_TITLE  = os.environ["API_TITLE"]
API_SOURCE = os.environ["API_SOURCE"]
API_KEY    = os.environ["API_KEY"]   # 비밀값
API_URL    = os.environ["API_URL"]   # 인증키가 들어 있어 이것도 비밀값

dbmanager = db_manager.DBManager()
_inited = False


def db():
    """DB를 쓰는 프로세스에서 첫 호출 때 한 번만 연결한다.

    init()을 모듈 최상단에서 부르면 spawn 방식이라 부모·컨트롤러·워커가 각자
    main을 재import 하면서 커넥션 풀을 세 개 연다. 실제로 work를 실행하는 건
    워커뿐이고, DB가 꺼져 있으면 DB와 무관한 태스크까지 시작이 느려진다.
    """
    global _inited
    if not _inited:
        dbmanager.init()
        _inited = True
    return dbmanager 


def db_call(task_name, **kwargs):
    """DB 작업 호출. 실패하면 한 줄 찍고 None 을 돌려준다."""
    return safe_call(db().call, task_name, **kwargs)

#────────────────────────────────────────────────

# session-data
# session insert
tasks["session_insert"] = ["test_session_id", "create_session"]
# session save
tasks["session_save"] = ["test_session_data", "get_session", "insert_db_session_data"]
# session title
tasks["update_session_title"] = ["test_session_title_input", "update_db_session_title"]
# session 확보 / 목록
tasks["get_or_create_session"] = ["test_user_id", "get_or_create_db_session"]
tasks["list_sessions"] = ["test_user_id", "list_db_sessions"]

# api-data
# api insert
tasks["api_insert"] = ["create_api_data", "insert_db_api_data", "embed_api_function"]
# api all update
tasks["api_all_update"] = ["select_all_db_api_data", "update_api_data", "update_db_api_data"]
# api delete
tasks["api_delete"] = ["test_api_url", "delete_db_api_data"]



#------------------------------------------------┌> dummy function

# 통신모듈 붙기 전까지 첫 work 에 입력을 넣어주는 자리
TEST_SESSION_ID = "7ba0535a-eb7d-40d0-813d-fa7f9c1c09b1"
TEST_SESSION_TITLE = "과일 재배 문의"
TEST_USER_ID = "0049c7f8-d327-4b87-878d-20f6f0f8c444"

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
    messages = db_call("get_recent_messages", session_id=args[0])
    context = db_call("get_session_context", session_id=args[0])
    return build_session(messages, context["current_topic"], context["overall_summary"])

#------------------------------------------------┌> session save func

# 새 세션의 대한 가공은 이전에 이미 되어있다 가정

# 세션 객체 획득
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
    inserted_message = db_call("insert_message", session_id=args[0].session_id, user_query=args[0].session.recent_conversations[-1]["user_query"], ai_response=args[0].session.recent_conversations[-1]["ai_response"])
    updated_topic = db_call("update_current_topic", session_id=args[0].session_id, topic=args[0].session.current_topic)
    updated_summary = db_call("update_overall_summary", session_id=args[0].session_id, summary=args[0].session.summary)
    return inserted_message, updated_topic, updated_summary

#-----------------------------------------------┌> api func

# api 실제 데이터로 객체 생성
@work_regist("create_api_data")
def api_data(*args, **kwargs) -> ApiEntity:
    request = ApiEntity(title=API_TITLE, url=API_URL, source=API_SOURCE, key=API_KEY)
    return asyncio.run(collect(request))

# DB에 저장, API 결과 리스트 반환
@work_regist("insert_db_api_data")
def insert_db_api_data(*args, **kwargs):
    inserted_api_data = db_call("insert_api_data", title=args[0].title, url=args[0].url, source=args[0].source, key=args[0].key, data=args[0].data, data_type=args[0].data_type)
    return inserted_api_data

#-----------------------------------------------┌> api all update

# 기존 API 전체 조회
@work_regist("select_all_db_api_data")
def select_all_db_api_data(*args, **kwargs):
    return db_call("select_all_api_data")

# 행마다 api 재호출
@work_regist("update_api_data")
def update_api_data(*args, **kwargs):
    updated_entities = []
    for row in args[0]:
        entity = safe_call(lambda: asyncio.run(collect(ApiEntity(title=row["title"], url=row["url"], source=row["source"], key=row["key"]))), label=row.get("title", "api 수집"))
        if entity is not None:
            updated_entities.append(entity)
    return updated_entities

# 갱신된 data 를 url 기준으로 저장
@work_regist("update_db_api_data")
def update_db_api_data(*args, **kwargs):
    updated_api_data = [db_call("update_api_data_date", url=entity.url, data=entity.data) for entity in args[0]]
    return updated_api_data

#-----------------------------------------------┌>  api timer all update



#-----------------------------------------------┌> api delete

# 삭제할 url (통신모듈 붙기 전까지 .env 의 API_URL 을 그대로 쓴다)
@work_regist("test_api_url")
def test_api_url(*args, **kwargs):
    return API_URL

# url 단건 삭제
@work_regist("delete_db_api_data")
def delete_db_api_data(*args, **kwargs):
    deleted_api_data = db_call("delete_api_data", url=args[0])
    return deleted_api_data

#-----------------------------------------------┌> session title func

# session_id, title
@work_regist("test_session_title_input")
def test_session_title_input(*args, **kwargs):
    return TEST_SESSION_ID, TEST_SESSION_TITLE

# 세션 제목 갱신. 갱신된 세션 row 를 돌려준다
@work_regist("update_db_session_title")
def update_db_session_title(*args, **kwargs):
    session_id, title = args[0]
    updated_title = db_call("update_session_title", session_id=session_id, title=title)
    return updated_title

#-----------------------------------------------┌> session user func

# user_id 하나
@work_regist("test_user_id")
def test_user_id(*args, **kwargs):
    return TEST_USER_ID

# 세션 확보. 없거나 타임아웃이면 새로 만든다
@work_regist("get_or_create_db_session")
def get_or_create_db_session(*args, **kwargs):
    session = db_call("get_or_create_session", user_id=args[0])
    return session["session_id"]

# 세션 목록. 최근 활동순
@work_regist("list_db_sessions")
def list_db_sessions(*args, **kwargs):
    session_list = db_call("list_sessions", user_id=args[0])
    return session_list


#────────────────────────────────────────────────┌> 통신부 task (명세 task_type)

tasks["CHAT_SESSION_LIST"] = ["chat_session_list_input", "list_db_sessions",
                              "chat_session_list_output"]


def _to_millis(value):
    """클라이언트가 createdAt 을 숫자 timestamp(ms)로 읽는다. DB 는 datetime 을 준다."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    to_timestamp = getattr(value, "timestamp", None)
    if to_timestamp is not None:            # datetime
        return int(to_timestamp() * 1000)
    return None                             # date 등 시각이 없는 값은 비워 둔다


@work_regist("chat_session_list_input")
def chat_session_list_input(*args, **kwargs):
    """요청 -> user_id.

    명세상 payload 가 없고 Authorization 토큰으로 사용자를 식별한다. login_output 이
    지금 user_id 를 토큰으로 내보내고 있어서 그대로 쓸 수 있다 — 토큰 발급 방식이
    바뀌면 여기서 토큰을 user_id 로 바꾸는 단계가 필요하다.

    인자가 없으면(메뉴로 직접 실행) TEST_USER_ID 로 떨어진다.
    """
    req = args[0] if args and isinstance(args[0], dict) else {}
    user_id = req.get("token") or TEST_USER_ID
    if not user_id:
        raise ValueError("사용자를 알 수 없습니다. Authorization 헤더가 필요합니다.")
    return user_id


@work_regist("chat_session_list_output")
def chat_session_list_output(*args, **kwargs):
    """세션 행 목록 -> 클라이언트가 읽는 {sessions:[{sessionId, title, createdAt}]}.

    title 컬럼이 없으면 요약이나 현재 토픽을 대신 쓴다. 그것도 없으면 클라이언트가
    기본값으로 쓰는 문구를 그대로 넣는다.
    """
    rows = args[0] or []
    return {"sessions": [
        {
            "sessionId": str(row.get("session_id")),
            "title": (row.get("title") or row.get("current_topic")
                      or row.get("overall_summary") or "새 대화"),
            "createdAt": _to_millis(row.get("created_at")),
        }
        for row in rows
    ]}
