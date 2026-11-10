#================================================
# log_helper.py
#================================================
"""rag-server 로깅 설정. 메인 프로세스와 실행부(자식 프로세스) 양쪽에서 부른다.

형식은 RagRouter·ServerCommunication 의 LogHelper 와 같다(KST 시각 | 레벨 | 이름 | 메시지).
여기에 프로세스 이름을 더한다 — rag-server 는 메인(라우터), 실행부, 타이머 실행부가 한 로그로
섞여 나오므로 어느 프로세스의 줄인지 봐야 한다.

왜 우리 로거를 루트에서 떼는가(propagate=False):
    실행부에서 모델 라이브러리(paddle 등)를 불러오면 루트 로거 레벨을 WARNING 으로 올리거나
    핸들러를 갈아 끼운다. 그러면 functions·ragmodul 의 INFO 로그가 통째로 사라지고 메인
    프로세스 로그만 남는다(실측). 우리 패키지 로거에 직접 핸들러와 레벨을 달면 루트가 어떻게
    바뀌든 영향을 받지 않는다. 루트는 그 밖의 라이브러리 로그용으로만 남긴다.

레벨은 환경변수 LOG_LEVEL(기본 INFO). 라우터와 같은 이름이라 배포 설정 하나로 맞춰진다.
"""
import logging
import os
import sys
from datetime import datetime, timedelta, timezone

LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(processName)-14s | %(name)-30s | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
KST = timezone(timedelta(hours=9))

# 우리 코드의 최상위 로거 이름. 하위(functions.rag_functions 등)는 여기에 붙는다.
APP_LOGGERS = (
    "bridge", "timer", "access", "auth", "files", "streaming", "functions", "utils",
    "ragmodul", "taskexecutor", "taskcontroller", "db_manager", "ai_rag_comm", "rag_router",
)
UVICORN_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access")
# 요청마다 줄을 남겨 로그를 덮는 라이브러리
QUIET_LOGGERS = ("httpx", "httpcore", "urllib3", "PIL", "matplotlib", "asyncio")


class KSTFormatter(logging.Formatter):
    def formatTime(self, record, datefmt=None):
        return datetime.fromtimestamp(record.created, tz=KST).strftime(datefmt or DATE_FORMAT)


def setup_logging(level: str | None = None) -> None:
    """로깅을 잡는다. 여러 번 불러도 된다 — 매번 핸들러를 갈아 끼워 중복 출력이 없다.

    부르는 곳:
      - main.py 시작 직후, 그리고 라우터를 불러온 뒤(라우터가 import 될 때 루트를 자기 형식으로 덮는다)
      - 실행부 프로세스 시작 시(streaming.StreamExecutor.run, timer) — spawn 이라 설정이 상속되지 않는다
    """
    level_name = (level or os.environ.get("LOG_LEVEL") or "INFO").upper()
    numeric = getattr(logging, level_name, logging.INFO)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(KSTFormatter(fmt=LOG_FORMAT, datefmt=DATE_FORMAT))

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(numeric)

    for name in APP_LOGGERS + UVICORN_LOGGERS:
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.addHandler(handler)
        logger.setLevel(numeric)
        logger.propagate = False        # 루트가 바뀌어도 우리 로그는 그대로 나간다

    for name in QUIET_LOGGERS:
        logging.getLogger(name).setLevel(max(numeric, logging.WARNING))


class LoggingProcess:
    """Process 하위 클래스에 섞어 쓰는 믹스인. 자식 프로세스가 시작하자마자 setup_logging() 을 부른다.

    spawn 자식은 새 인터프리터라 메인의 로깅 설정을 받지 못한다. 라이브러리(TaskExecutor·
    TaskController)를 고치지 않고 여기서 감싼다.

        class TimerExecutor(LoggingProcess, TaskExecutor): pass
    """

    def run(self) -> None:
        setup_logging()
        super().run()
