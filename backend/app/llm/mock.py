"""Deterministic local LLM used by default for low-cost development."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import AsyncIterator
from typing import Any

from app.llm.base import (
    LLMResult,
    LLMStreamChunk,
    LLMToolCall,
    LLMToolResponse,
)

_DRAFT_ID_RE = re.compile(r"draft_id=([0-9a-f]{32})")
_REQUEST_ID_RE = re.compile(r"([0-9a-f]{32})")
_EVIDENCE_RE = re.compile(
    r"<knowledge_evidence>\s*(.*?)\s*</knowledge_evidence>",
    re.DOTALL,
)
_QUESTION_RE = re.compile(
    r"<question>\s*(.*?)\s*</question>",
    re.DOTALL,
)


class MockLLM:
    """Small deterministic provider for tests, local development, and E2E."""

    model_name = "mock-local"

    async def generate(
        self,
        *,
        system_prompt: str,
        user_message: str,
    ) -> LLMResult:
        if "Supervisor" in system_prompt and "意图" in system_prompt:
            content = self._supervisor_decision(user_message)
        elif (
            "<knowledge_evidence>" in system_prompt
            or "<knowledge_evidence>" in user_message
        ):
            content = self._rag_answer(user_message)
        else:
            content = self._chat_answer(user_message)
        return LLMResult(
            content=content,
            model=self.model_name,
            prompt_tokens=0,
            completion_tokens=0,
        )

    async def stream(
        self,
        *,
        system_prompt: str,
        user_message: str,
    ) -> AsyncIterator[LLMStreamChunk]:
        content = self._chat_answer(user_message)
        midpoint = max(1, len(content) // 2)
        yield LLMStreamChunk(
            text=content[:midpoint],
            model=self.model_name,
        )
        yield LLMStreamChunk(
            text=content[midpoint:],
            model=self.model_name,
        )
        yield LLMStreamChunk(
            model=self.model_name,
            prompt_tokens=0,
            completion_tokens=0,
        )

    async def generate_with_tools(
        self,
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> LLMToolResponse:
        if not tools:
            raise ValueError("Mock tool provider requires tool definitions")
        if messages and messages[-1].get("role") == "tool":
            raw = str(messages[-1].get("content") or "{}")
            try:
                outcome = json.loads(raw)
            except json.JSONDecodeError:
                outcome = {"message": "工具已执行。"}
            return LLMToolResponse(
                content=str(outcome.get("message") or "工具已执行。"),
                model=self.model_name,
            )

        user_message = next(
            (
                str(message.get("content") or "")
                for message in reversed(messages)
                if message.get("role") == "user"
            ),
            "",
        )
        system_text = "\n".join(
            str(message.get("content") or "")
            for message in messages
            if message.get("role") == "system"
        )
        lowered = user_message.lower()
        draft_ids = list(dict.fromkeys(_DRAFT_ID_RE.findall(system_text)))

        update_words = ("改成", "修改", "更新", "改成", "改为")
        query_words = ("查询", "查看", "看看", "内容", "详情", "状态")
        create_words = (
            "创建",
            "建个",
            "新建",
            "报修",
            "登记",
            "开一张",
            "提交工单",
        )
        if any(word in user_message for word in update_words):
            explicit_id = next(
                (value for value in _REQUEST_ID_RE.findall(user_message)),
                None,
            )
            target_id = explicit_id or (
                draft_ids[-1] if len(draft_ids) == 1 else None
            )
            if target_id is None:
                return LLMToolResponse(
                    content="当前有多个可能的工单草稿，请明确要修改的 draft_id。",
                    model=self.model_name,
                )
            arguments: dict[str, str] = {"draft_id": target_id}
            description = self._value_after(
                user_message,
                ("问题描述改成", "描述改成", "改成", "修改为", "改为"),
            )
            title = self._quoted_title(user_message, marker="标题")
            if description:
                arguments["description"] = description
            if title:
                arguments["title"] = title
            if len(arguments) == 1:
                arguments["description"] = user_message.strip()
            return self._tool_response("update_ticket_draft", arguments)

        if any(word in user_message for word in query_words):
            target_id = (
                draft_ids[-1]
                if draft_ids
                else next(
                    iter(_REQUEST_ID_RE.findall(user_message)),
                    None,
                )
            )
            if target_id:
                return self._tool_response(
                    "get_ticket_draft",
                    {"draft_id": target_id},
                )

        if any(word in user_message for word in create_words):
            title = self._quoted_title(user_message, marker="标题")
            if not title:
                if "电脑" in user_message and "网" in user_message:
                    title = "电脑无法联网"
                elif "打印机" in user_message:
                    title = "打印机故障"
                elif "投影" in user_message:
                    title = "投影仪故障"
                elif "邮箱" in user_message:
                    title = "邮箱故障"
                else:
                    title = "故障工单"
            device = self._value_after(
                user_message,
                ("设备是", "设备为", "系统是", "系统为"),
            ) or (
                "电脑"
                if "电脑" in user_message
                else "打印机"
                if "打印机" in user_message
                else "办公设备"
            )
            return self._tool_response(
                "create_ticket_draft",
                {
                    "title": title,
                    "description": user_message.strip(),
                    "device_or_system": device,
                },
            )

        return LLMToolResponse(
            content="请补充设备或系统名称、故障现象和期望处理方式。",
            model=self.model_name,
        )

    async def aclose(self) -> None:
        return None

    @staticmethod
    def _supervisor_decision(user_message: str) -> str:
        text = user_message.lower()
        current_request = (
            user_message.split("<current_user_request>", 1)[-1]
            .split("</current_user_request>", 1)[0]
            .strip()
        )
        if any(
            word in current_request
            for word in ("工单", "报修", "维修单", "草稿")
        ):
            intent = "ticket_request"
            reason = "请求明确涉及工单或草稿。"
        elif any(
            word in current_request
            for word in (
                "缓存",
                "数据库",
                "mysql",
                "redis",
                "rag",
                "api key",
                "错误代码",
                "流程",
                "vpn",
                "sse",
                "qdrant",
                "fastapi",
            )
        ):
            intent = "knowledge_query"
            reason = "请求需要企业知识或技术资料。"
        elif any(
            word in current_request
            for word in ("处理一下", "搞一下", "那个东西", "有个问题", "不太对")
        ):
            intent = "clarification"
            reason = "请求缺少可执行目标。"
        else:
            intent = "general_chat"
            reason = "普通对话或一般性问题。"
        return json.dumps(
            {
                "intent": intent,
                "reason": reason,
                "clarification_question": (
                    "请补充要查询知识、创建工单还是普通聊天。"
                    if intent == "clarification"
                    else ""
                ),
            },
            ensure_ascii=False,
        )

    @staticmethod
    def _rag_answer(user_message: str) -> str:
        evidence_match = _EVIDENCE_RE.search(user_message)
        question_match = _QUESTION_RE.search(user_message)
        evidence = evidence_match.group(1).strip() if evidence_match else ""
        question = question_match.group(1).strip() if question_match else ""
        if not evidence:
            return json.dumps(
                {
                    "status": "insufficient_evidence",
                    "answer": "",
                    "used_citations": [],
                    "evidence_assessment": "没有可用证据。",
                },
                ensure_ascii=False,
            )
        evidence_body = re.sub(r"\[[0-9]+\]\s*(?:Source:)?[^\n]*\n?", "", evidence)
        evidence_body = " ".join(evidence_body.split())
        if not evidence_body:
            evidence_body = " ".join(evidence.split())[:240]
        if any(word in question for word in ("年假余额", "差旅报销标准")):
            return json.dumps(
                {
                    "status": "insufficient_evidence",
                    "answer": "",
                    "used_citations": [],
                    "evidence_assessment": "现有证据没有包含该事实。",
                },
                ensure_ascii=False,
            )
        return json.dumps(
            {
                "status": "answered",
                "answer": f"根据知识库证据，{evidence_body[:260]} [1]。",
                "used_citations": [1],
                "evidence_assessment": "模拟模式下引用首条真实检索证据。",
            },
            ensure_ascii=False,
        )

    @staticmethod
    def _chat_answer(user_message: str) -> str:
        current = (
            user_message.split("<current_user_request>", 1)[-1]
            .split("</current_user_request>", 1)[0]
            .strip()
        )
        normalized = current.strip("。！？!? ")
        if normalized.lower() == "只回复 ok":
            return "OK"
        if "你好" in current or "介绍" in current:
            return "你好，我是 OpsPilot 的本地模拟助手。"
        return f"这是本地模拟回复：{current}"

    def _tool_response(
        self,
        name: str,
        arguments: dict[str, Any],
    ) -> LLMToolResponse:
        serialized = json.dumps(
            {"name": name, "arguments": arguments},
            ensure_ascii=False,
            sort_keys=True,
        )
        call_id = "mock-" + hashlib.sha256(
            serialized.encode("utf-8")
        ).hexdigest()[:24]
        return LLMToolResponse(
            content=None,
            model=self.model_name,
            tool_calls=(
                LLMToolCall(
                    id=call_id,
                    name=name,
                    arguments=json.dumps(
                        arguments,
                        ensure_ascii=False,
                    ),
                ),
            ),
        )

    @staticmethod
    def _value_after(
        text: str,
        markers: tuple[str, ...],
    ) -> str:
        for marker in markers:
            if marker in text:
                value = text.split(marker, 1)[1]
                value = re.split(r"[，。；\n]", value, maxsplit=1)[0]
                return value.strip(" ：:，。")
        return ""

    @staticmethod
    def _quoted_title(text: str, *, marker: str) -> str:
        patterns = (
            rf"{marker}(?:使用|改成|改为|为|是)?[“\"]([^”\"]+)[”\"]",
            rf"{marker}\s*[:：]\s*([^，。；\n]+)",
        )
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return match.group(1).strip()
        return ""
