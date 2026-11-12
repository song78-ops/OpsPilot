"""Build a bounded, citation-numbered evidence context."""

from collections.abc import Callable
from dataclasses import dataclass

from app.rag.retrieval.types import RankedRetrievalHit


@dataclass(frozen=True, slots=True)
class EvidenceSource:
    citation_id: int
    hit: RankedRetrievalHit


@dataclass(frozen=True, slots=True)
class EvidenceContext:
    text: str
    sources: list[EvidenceSource]
    token_count: int
    dropped_count: int


class EvidenceContextBuilder:
    """Pack whole retrieval units into a model-independent token budget."""

    def __init__(
        self,
        *,
        max_tokens: int,
        count_tokens: Callable[[str], int],
    ) -> None:
        self._max_tokens = max_tokens
        self._count_tokens = count_tokens

    def build(self, hits: list[RankedRetrievalHit]) -> EvidenceContext:
        blocks: list[str] = []
        sources: list[EvidenceSource] = []
        seen_keys: set[str] = set()
        dropped_count = 0

        for hit in hits:
            key = hit.unit.key
            if key in seen_keys:
                dropped_count += 1
                continue
            seen_keys.add(key)

            citation_id = len(sources) + 1
            page = (
                f"第 {hit.unit.page_number} 页"
                if hit.unit.page_number is not None
                else "页码未知"
            )
            block = (
                f"[{citation_id}] 来源文件：{hit.unit.filename}；{page}；"
                f"chunk_id：{hit.unit.chunk_id}；part：{hit.unit.part_index}\n"
                f'<evidence id="{citation_id}">\n'
                f"{hit.unit.content}\n"
                f"</evidence>"
            )
            candidate = "\n\n".join([*blocks, block])
            if self._count_tokens(candidate) > self._max_tokens:
                dropped_count += 1
                continue
            blocks.append(block)
            sources.append(
                EvidenceSource(citation_id=citation_id, hit=hit)
            )

        text = "\n\n".join(blocks)
        return EvidenceContext(
            text=text,
            sources=sources,
            token_count=self._count_tokens(text) if text else 0,
            dropped_count=dropped_count,
        )

