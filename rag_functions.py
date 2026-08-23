
#================================================
# rag_functions.py
#================================================
"""
RAG 파이프라인 work 등록.

work 는 TaskExecutor 프로세스 안에서 실행된다. spawn 방식에서는 자식이 main 을
재import 하므로, RagController 를 모듈 레벨에서 만들면 프로세스마다 임베딩·리랭커
모델을 각각 로드하고 DB 에도 각각 접속한다. 그래서 첫 호출 시점에 한 번만 만든다.

파싱·청킹은 모델도 DB도 필요 없으므로 ragmodul 이 따로 열어둔 parse()/chunk() 를
직접 쓴다. RagController 를 거치면 생성자에서 모델 두 개를 올리고 PostgreSQL 까지
붙기 때문에, 파싱만 보고 싶을 때도 그게 전부 떠 있어야 한다.

입력값(문서 경로·질의문)은 모듈 상수/환경변수로 준다. TaskExecutor 가 task() 를
인자 없이 호출하는 데다 워커가 별 프로세스라, main 에서 값을 넣어도 워커까지
넘어가지 않는다. 환경변수는 spawn 시점에 상속되므로 넘어간다.
"""

import os

from taskcontroller import work_regist, tasks
from ragmodul import RagController, chunk, parse

#────────────────────────────────────────────────

# 로컬 모델 폴더. 리랭커는 local_files_only 로 로드하므로 실제 폴더여야 한다.
EMBEDDING_MODEL_PATH = os.environ.get("RAG_EMBEDDING_MODEL", "models/bge-m3")
RERANKER_MODEL_PATH = os.environ.get("RAG_RERANKER_MODEL", "models/bge-reranker-v2-m3")

# None 이면 라이브러리 자동 감지. GPU 가 있으면 "cuda" 를 명시하는 편이 낫다
# (안 주면 가중치가 CPU 에 남아 배치마다 복사된다).
DEVICE = os.environ.get("RAG_DEVICE") or None

UNPACK_DIR = os.environ.get("RAG_UNPACK_DIR", "unpacked")
HWPX_FILE_PATH = os.environ.get("RAG_HWPX_FILE", "C:/Users/aaa/Desktop/RagSystem/RagSystem/2주기(2023년) 2022 ~ 2024 대학혁신지원사업 성과평가보고서 (2).hwpx")


TOP_K_SEARCH = int(os.environ.get("RAG_TOP_K_SEARCH", "40"))     # 조각. 넉넉히 뽑는다
TOP_K_CONTEXT = int(os.environ.get("RAG_TOP_K_CONTEXT", "10"))   # 리랭커에 넘길 후보
TOP_K_FINAL = int(os.environ.get("RAG_TOP_K_FINAL", "5"))        # LLM 에 실을 최종 개수

#────────────────────────────────────────────────

tasks["레그 실행"] = ["parse_function", "chunk_function", "embed_function", "save_function"]
tasks["레그 청킹"] = ["parse_function", "chunk_function"]   # 모델·DB 없이 확인용
tasks["레그 검색"] = ["embed_query_function", "hybrid_search_function", "build_context_function", "rerank_function"]

#------------------------------------------------┌> 지연 생성

_controller: RagController | None = None


def get_controller() -> RagController:
    """워커 프로세스에서 처음 필요할 때 한 번만 만든다.

    생성자가 임베딩 모델·리랭커 로드와 DB 연결을 전부 하므로 몇십 초 걸린다.
    """
    global _controller
    if _controller is None:
        _controller = RagController(
            EMBEDDING_MODEL_PATH,
            RERANKER_MODEL_PATH,
            device=DEVICE,
            unpack_dir=UNPACK_DIR,
        )
    return _controller

#------------------------------------------------┌> 문서 등록


@work_regist("parse_function")
def parse_function(*args, **kwargs):
    """hwpx -> DocumentModel. 체인의 첫 단계라 경로를 상수에서 받는다."""
    file_path = HWPX_FILE_PATH
    if not file_path:
        raise ValueError(
            "문서 경로가 비어 있습니다. RAG_HWPX_FILE 환경변수나 "
            "rag_functions.HWPX_FILE_PATH 를 지정하세요."
        )
    print(f"[parse_function] 파싱 시작: {file_path}")
    parsed = parse(file_path, unpack_dir=UNPACK_DIR)
    print(f"[parse_function] 파싱 종료: block {len(parsed.blocks)}개")
    return parsed


@work_regist("chunk_function")
def chunk_function(*args, **kwargs):
    """DocumentModel -> ChunkedDocument (parent/child)."""
    document = chunk(args[0])
    print(f"[chunk_function] 청킹 종료: parent {len(document.parents)}, "
          f"child {len(document.children())}")
    return document


@work_regist("embed_function")
def embed_function(*args, **kwargs):
    """child 에 dense/sparse 를 채운다. 같은 객체를 돌려주므로 체인이 이어진다."""
    document = get_controller().embed_bge_m3(args[0])
    print(f"[embed_function] 임베딩 종료: child {len(document.children())}개")
    return document


@work_regist("save_function")
def save_function(*args, **kwargs):
    """DB 저장. 저장한 child 수를 돌려준다."""
    saved = get_controller().save_to_vector_db(args[0])
    print(f"[save_function] 저장 종료: child {saved}개")
    return saved

#------------------------------------------------┌> 질의 검색


@work_regist("embed_query_function")
def embed_query_function(*args, **kwargs):
    """질의 -> (dense 벡터, sparse 가중치). 체인의 첫 단계라 질의를 상수에서 받는다.

    다음 단계가 질의 문자열도 필요하므로(리랭킹) 함께 실어 보낸다.
    """
    query = args[0] 
    if not query:
        raise ValueError(
            "질의가 비어 있습니다. RAG_QUERY 환경변수나 "
            "rag_functions.QUERY 를 지정하세요."
        )
    vector, weights = get_controller().embed_query(query)
    return query, vector, weights


@work_regist("hybrid_search_function")
def hybrid_search_function(*args, **kwargs):
    query, vector, weights = args[0]
    hits = get_controller().hybrid_search(vector, weights, top_k=TOP_K_SEARCH)
    print(f"[hybrid_search_function] 조각 {len(hits)}개")
    return query, hits


@work_regist("build_context_function")
def build_context_function(*args, **kwargs):
    query, hits = args[0]
    contexts = get_controller().build_contexts(hits, limit=TOP_K_CONTEXT)
    print(f"[build_context_function] 맥락 {len(contexts)}개 "
          f"(승격 {sum(1 for c in contexts if c.merged)})")
    return query, contexts


@work_regist("rerank_function")
def rerank_function(*args, **kwargs):
    query, contexts = args[0]
    ordered = get_controller().rerank(query, contexts, top_k=TOP_K_FINAL)
    for rank, context in enumerate(ordered, 1):
        print(f"[rerank_function] {rank}. score={context.rerank_score:.4f} "
              f"merged={context.merged} {context.breadcrumb[:60]}")
    return ordered
