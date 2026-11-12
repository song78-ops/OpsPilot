"""Mixed Chinese, English, numeric, and product-code tokenization."""

import logging
import re
import unicodedata

import jieba

jieba.setLogLevel(logging.WARNING)

_TOKEN_PATTERN = re.compile(
    r"[A-Za-z0-9]+(?:[-_.:/][A-Za-z0-9]+)*|[\u4e00-\u9fff]+"
)
_CODE_SEPARATORS = re.compile(r"[-_.:/]+")
_STOP_WORDS = frozenset(
    {
        "的",
        "了",
        "是",
        "在",
        "与",
        "和",
        "及",
        "或",
        "对",
        "如何",
        "什么",
        "the",
        "a",
        "an",
        "and",
        "or",
        "to",
        "of",
        "is",
        "how",
        "what",
    }
)


class BM25Tokenizer:
    """Preserve full codes while also making their components searchable."""

    version = "mixed-jieba-v1"

    def tokenize(self, text: str) -> list[str]:
        normalized = unicodedata.normalize("NFKC", text).lower()
        tokens: list[str] = []

        for match in _TOKEN_PATTERN.finditer(normalized):
            segment = match.group(0)
            if re.fullmatch(r"[\u4e00-\u9fff]+", segment):
                tokens.extend(
                    token
                    for token in jieba.lcut(segment, cut_all=False)
                    if token.strip() and token not in _STOP_WORDS
                )
                continue

            if segment not in _STOP_WORDS:
                tokens.append(segment)
            for component in _CODE_SEPARATORS.split(segment):
                if (
                    component
                    and component != segment
                    and component not in _STOP_WORDS
                ):
                    tokens.append(component)

        return tokens

