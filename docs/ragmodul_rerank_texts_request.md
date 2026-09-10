# ragmodul 요청 — 텍스트 목록을 받는 리랭킹

## 왜

이미지 검색에 리랭커를 붙였다. 벡터 검색만으로는 순위가 흔들린다 — 이미지 설명이
"2026년 68.7%", "간호학과 92%" 처럼 숫자와 고유명사 덩어리라 의미 유사도가 약하다.

그런데 지금 `rerank` 는 `RetrievedContext` 를 전제로 한다.

```python
pairs = [[query, c.rerank_text] for c in contexts]   # 속성으로 읽고
context.rerank_score = float(score)                  # 속성에 쓴다
```

DB 에서 오는 이미지 행은 dict 라 속성 접근이 안 된다. 그래서 이런 걸 만들어서
감싸고 있다.

```python
class _ImageHit:
    __slots__ = ("row", "rerank_text", "rerank_score")
    def __init__(self, row, text):
        self.row = row
        self.rerank_text = text
        self.rerank_score = 0.0
```

리랭커가 실제로 필요한 건 **텍스트 목록**뿐인데, 그걸 넘길 통로가 없어서 부르는
쪽마다 껍데기를 만들게 된다.

## 요청

텍스트 목록을 받는 진입점을 하나 열어주세요.

```python
def rerank_texts(self, query: str, texts: list[str], top_k: int | None = None,
                 min_score: float | None = DEFAULT_MIN_SCORE,
                 ) -> list[tuple[int, float]]:
    """(원래 인덱스, 점수) 를 점수순으로 돌려준다."""
```

**인덱스로 돌려주는 게 중요하다.** 부르는 쪽은 그 텍스트가 어느 행의 것인지 알아야
하는데, 텍스트만 돌려받으면 되짚을 방법이 없다(같은 설명이 두 행에 있을 수도 있다).
인덱스면 `rows[i]` 로 바로 찾는다.

```python
for index, score in rag.rerank_texts(query, [r["ai_summary"] for r in rows], top_k=2):
    picked.append(rows[index])
```

`max_per_parent` 는 필요 없다. 그건 한 부모의 조각이 최종 자리를 독점하는 것을 막는
값이라 맥락 전용이다.

`min_score` 는 지금과 같은 기본값이면 된다. 다만 `DEFAULT_MIN_SCORE = 0.01` 은 문서
맥락으로 잰 값이라(무관한 질의 최고점 0.000445 의 22배), **이미지 설명에서는 분포가
다를 수 있다.** 우리 쪽에서 로그로 재보고 결과를 알려주겠다.

## 그리고 `rerank` 는 이걸로 다시 쓸 수 있다

지금 `rerank` 가 하는 일은 (1) 점수 매기기 (2) 정렬 (3) 문턱 (4) 부모당 제한 이다.
(1)~(3) 은 `rerank_texts` 와 같으므로, 기존 `rerank` 를 이렇게 얹을 수 있다.

```python
def rerank(self, query, contexts, top_k, max_per_parent=..., min_score=...):
    scored = self.rerank_texts(query, [c.rerank_text for c in contexts],
                               top_k=None, min_score=None)
    for index, score in scored:
        contexts[index].rerank_score = score     # 기존 계약대로 점수를 써준다
    ...
```

기존 호출부는 그대로 두고 안쪽만 공유하는 모양이라, 우리가 쓰는 `rerank` 의 동작은
바뀌지 않는다. 다만 이건 제안일 뿐이고 `rerank_texts` 만 따로 있어도 충분하다.

## 참고 — 이 요청과 별개로 아쉬운 것

이미지 벡터는 dense 뿐이라 하이브리드가 안 된다(`document_image_vectors` 가
`embedding vector(1024)` 한 컬럼이다). 이미지 설명은 숫자와 고유명사가 많아서
sparse 가 제일 잘 맞는 자료인데 그걸 못 쓰고 있다. 이건 DB 쪽 작업이라 따로 요청할
예정이고, 여기서는 리랭킹만 부탁한다.
