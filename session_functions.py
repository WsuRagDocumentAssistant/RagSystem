
#================================================
# session_functions.py
#================================================

from taskcontroller import work_regist, tasks
from session_data import build_session, Session

#────────────────────────────────────────────────

tasks["session_save"] = ["test_create_session_data", "get_session", "insert_db_session_data"]
tasks["seesion_load"] = ["test_create_session_data", "get_session"]

#------------------------------------------------┌> dummy function & class

class DBManager:
    def insert_session_data(session: Session):
        print("해당 세션 데이터가 DB에 잘 들어갔슈")


@work_regist("test_create_session_data")
def dummy_session_data(*args, **kwargs):
    return (["11"],"11","11")

#------------------------------------------------

@work_regist("get_session")
def get_session_data(*args,**kwargs):
    return build_session(args[0][0],args[0][1],args[0][2])

@work_regist("insert_db_session_data")
def insert_db_session_data(*args, **kwargs):
    DBManager.insert_session_data(args[0])
    return 0