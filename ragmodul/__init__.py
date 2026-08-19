"""
RAG 처리 모듈.

단계 하나가 메서드 하나다. 순서·재시도·단계 간 데이터 전달은 부르는 쪽 책임이고,
이 모듈은 요청받은 단계만 실행한다. 실패는 예외로 올라온다.

    from ragmodul import RagController

    rag = RagController(
        embedding_model_path="models/bge-m3",
        reranker_model_path="models/bge-reranker-v2-m3",
    )

    # 문서 등록
    parsed = rag.parse_document("문서.hwpx")
    document = rag.chunk_parent_child(parsed)
    rag.embed_bge_m3(document)
    rag.save_to_vector_db(document)

    # 질의 검색
    qvec = rag.embed_query("유학생 유치 수와 국가 수는?")
    results = rag.hybrid_search(qvec, top_k=5)
    results = rag.rerank("유학생 유치 수와 국가 수는?", results, top_k=3)
"""

from .controller import RagController
from .models.chunk_model import ChildChunk, ChunkedDocument, ParentChunk
from .service.chunker_service import chunk
from .service.db_service import DbService
from .service.embedded_service import EmbeddedService
from .service.ocr_service import OcrService
from .service.parser_service import parse
from .service.reranker_service import RerankerService

__all__ = [
    # 진입점
    "RagController",
    # 데이터 모델
    "ChunkedDocument",
    "ParentChunk",
    "ChildChunk",
    # 단계별로 따로 쓰고 싶을 때
    "parse",
    "chunk",
    "EmbeddedService",
    "RerankerService",
    "DbService",
    "OcrService",
]
