"""Grounded customer-reply generation for resolution Phase B."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, Protocol, cast

from app.boundary.translation import CANONICAL_LANGUAGE

_MAX_GENERATION_TOKENS = 900
_GENERATION_TEMPERATURE = 0.2
_SYSTEM_PROMPT = """\
You generate governed customer-facing support replies.

Return ONLY compact JSON matching this schema:
{
  "language": "en",
  "segments": [
    {"kind": "acknowledgment", "text": "...", "citation_ranks": []},
    {"kind": "claim", "text": "...", "citation_ranks": [1]},
    {"kind": "question", "text": "...", "citation_ranks": []}
  ]
}

Rules:
- "acknowledgment" segments are short, non-factual courtesy or empathy text
  only (e.g. greetings, apologies for the inconvenience, offers to help).
  They must not state or imply any fact about the product, the customer's
  account or situation, eligibility, policy, compensation, or shipping.
  Acknowledgment segments must not include citation_ranks.
- Every customer-facing factual claim MUST cite one or more retrieved
  evidence ranks in citation_ranks.
- Do not place citation markers such as [1] in text. The renderer owns
  citation markers.
- Questions must not include citation_ranks.
- Use only facts present in retrieved evidence. If evidence is missing or
  irrelevant, emit one uncited claim explaining that no grounded automatic
  reply can be produced; governance will escalate it.
- Do not promise refunds, replacements, warranty coverage, credits,
  shipping, or policy exceptions.
- Keep the reply concise, professional, and helpful.
"""

# Conservative, deterministic signal of a factual assertion that must not be
# exempted from citation coverage. If an "acknowledgment" segment matches
# this, it is reclassified to "claim" (with no citations) so GroundingPolicy
# denies it as uncited -- the LLM cannot grant its own grounding exemption by
# mislabeling a factual claim as an acknowledgment.
_UNSAFE_ACKNOWLEDGMENT_PATTERN = re.compile(
    r"\b("
    r"refund\w*|replac\w*|warrant\w*|eligib\w*|credit\w*|compensat\w*|"
    r"discount\w*|exchang\w*|reimburs\w*|guarant\w*|entitle\w*|"
    r"polic\w*|cover\w*|approv\w*|denial|denied|ship\w*|rma|return\w*"
    r")\b",
    re.IGNORECASE,
)
_DIGIT_PATTERN = re.compile(r"\d")


def _is_safe_acknowledgment(text: str) -> bool:
    """Conservative check for non-factual courtesy/empathy text.

    Returns False (unsafe) if the text contains any signal of a verifiable
    factual assertion -- policy, eligibility, compensation, shipping, or a
    numeric detail. Callers must fail closed by reclassifying unsafe
    "acknowledgment" segments to "claim".
    """

    if _DIGIT_PATTERN.search(text):
        return False
    if _UNSAFE_ACKNOWLEDGMENT_PATTERN.search(text):
        return False
    return True


@dataclass(frozen=True, slots=True)
class GroundedReplySegment:
    kind: Literal["claim", "question", "acknowledgment"]
    text: str
    citation_ranks: tuple[int, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "text": self.text,
            "citation_ranks": list(self.citation_ranks),
        }


@dataclass(frozen=True, slots=True)
class GroundedReplyDraft:
    language: str
    segments: tuple[GroundedReplySegment, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "language": self.language,
            "segments": [segment.to_dict() for segment in self.segments],
        }


@dataclass(frozen=True, slots=True)
class ConversationGenerationRequest:
    tenant_id: str
    session_id: str
    diagnostic_summary: str
    diagnostic_category: str
    diagnostic_confidence: float
    original_content: str
    source_language: str
    evidence: tuple[Mapping[str, Any], ...]
    conversation_history: tuple[Mapping[str, Any], ...] = ()
    target_language: str = CANONICAL_LANGUAGE


@dataclass(frozen=True, slots=True)
class ConversationGenerationResult:
    draft: GroundedReplyDraft
    provider: str
    model: str
    raw_text: str


@dataclass(frozen=True, slots=True)
class _LLMMessage:
    role: str
    content: str


class _LLMCompletion(Protocol):
    provider: str
    model: str
    text: str


class ConversationGenerationRuntimeProtocol(Protocol):
    async def generate_reply(
        self,
        request: ConversationGenerationRequest,
    ) -> ConversationGenerationResult: ...


class GroundedConversationGenerationRuntime:
    """LLM-backed structured reply generation with a deterministic fallback."""

    def __init__(self, *, llm_client: Any | None = None) -> None:
        self._llm_client = llm_client

    async def generate_reply(
        self,
        request: ConversationGenerationRequest,
    ) -> ConversationGenerationResult:
        if self._llm_client is None:
            draft = _fallback_draft(request)
            return ConversationGenerationResult(
                draft=draft,
                provider="operious-local-grounded-fallback",
                model="citation-coverage-fallback-v1",
                raw_text=json.dumps(draft.to_dict(), sort_keys=True),
            )
        completion = cast(
            _LLMCompletion,
            await self._llm_client.complete(
                system_prompt=_SYSTEM_PROMPT,
                messages=(_LLMMessage(role="user", content=_user_prompt(request)),),
                max_output_tokens=_MAX_GENERATION_TOKENS,
                temperature=_GENERATION_TEMPERATURE,
                tenant_id=request.tenant_id,
            ),
        )
        draft = parse_grounded_reply_draft(
            completion.text,
            expected_language=request.target_language,
        )
        return ConversationGenerationResult(
            draft=draft,
            provider=completion.provider,
            model=completion.model,
            raw_text=completion.text,
        )


def render_grounded_reply(draft: GroundedReplyDraft) -> str:
    """Render structured segments into natural prose with owned citations."""

    rendered: list[str] = []
    for segment in draft.segments:
        text = " ".join(segment.text.split())
        if not text:
            continue
        if segment.kind == "claim" and segment.citation_ranks:
            marker = ",".join(str(rank) for rank in segment.citation_ranks)
            text = f"{text} [{marker}]"
        rendered.append(text)
    return " ".join(rendered).strip()


def parse_grounded_reply_draft(
    raw_text: str,
    *,
    expected_language: str,
) -> GroundedReplyDraft:
    data = _json_object(raw_text)
    language = str(data.get("language") or "").strip().lower()
    if language != expected_language:
        raise ValueError("grounded reply language mismatch")
    segments_value = data.get("segments")
    if not isinstance(segments_value, list) or not segments_value:
        raise ValueError("grounded reply segments are required")
    segments: list[GroundedReplySegment] = []
    for value in cast(list[object], segments_value):
        if not isinstance(value, Mapping):
            raise ValueError("grounded reply segment must be an object")
        segment = cast(Mapping[str, Any], value)
        kind = str(segment.get("kind") or "").strip().lower()
        if kind not in {"claim", "question", "acknowledgment"}:
            raise ValueError("grounded reply segment kind is invalid")
        text = str(segment.get("text") or "").strip()
        if not text:
            raise ValueError("grounded reply segment text is required")
        ranks = _citation_ranks(segment.get("citation_ranks"))
        if kind in {"question", "acknowledgment"} and ranks:
            raise ValueError("question/acknowledgment segments cannot carry citations")
        if kind == "acknowledgment" and not _is_safe_acknowledgment(text):
            # Fail closed: the LLM cannot self-grant a grounding exemption by
            # mislabeling a factual claim as an acknowledgment. Reclassify to
            # "claim" with no citations so GroundingPolicy denies it.
            kind = "claim"
        segments.append(
            GroundedReplySegment(
                kind=cast(Literal["claim", "question", "acknowledgment"], kind),
                text=text,
                citation_ranks=ranks,
            )
        )
    return GroundedReplyDraft(language=language, segments=tuple(segments))


def _user_prompt(request: ConversationGenerationRequest) -> str:
    return json.dumps(
        {
            "task": "generate_grounded_customer_reply",
            "target_language": request.target_language,
            "source_language": request.source_language,
            "session_id": request.session_id,
            "diagnostic": {
                "summary": request.diagnostic_summary,
                "category": request.diagnostic_category,
                "confidence": request.diagnostic_confidence,
            },
            "customer_message": request.original_content,
            "conversation_history": [dict(turn) for turn in request.conversation_history],
            "retrieved_evidence": [_evidence_prompt_item(item) for item in request.evidence],
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def _evidence_prompt_item(item: Mapping[str, Any]) -> dict[str, object]:
    return {
        "rank": item.get("rank"),
        "title": item.get("title"),
        "document_id": item.get("document_id"),
        "document_version": item.get("document_version"),
        "char_start": item.get("char_start"),
        "char_end": item.get("char_end"),
        "safe_excerpt": item.get("safe_excerpt") or item.get("title"),
    }


def _fallback_draft(request: ConversationGenerationRequest) -> GroundedReplyDraft:
    if not request.evidence:
        return GroundedReplyDraft(
            language=request.target_language,
            segments=(
                GroundedReplySegment(
                    kind="claim",
                    text=(
                        "I could not find approved support knowledge that "
                        "grounds an automatic reply for this issue."
                    ),
                    citation_ranks=(),
                ),
            ),
        )
    first = request.evidence[0]
    rank = _int_or_none(first.get("rank")) or 1
    excerpt = str(first.get("safe_excerpt") or first.get("title") or "").strip()
    if not excerpt:
        excerpt = "approved support guidance is available for this issue"
    return GroundedReplyDraft(
        language=request.target_language,
        segments=(
            GroundedReplySegment(
                kind="claim",
                text=f"I found approved support guidance relevant to this issue: {excerpt}.",
                citation_ranks=(rank,),
            ),
            GroundedReplySegment(
                kind="question",
                text=(
                    "Please share your order number or product model so a "
                    "support specialist can confirm the next step."
                ),
                citation_ranks=(),
            ),
        ),
    )


def _json_object(raw_text: str) -> Mapping[str, Any]:
    try:
        value = json.loads(raw_text)
    except json.JSONDecodeError:
        start = raw_text.find("{")
        end = raw_text.rfind("}")
        if start < 0 or end <= start:
            raise
        value = json.loads(raw_text[start : end + 1])
    if not isinstance(value, Mapping):
        raise ValueError("grounded reply must be a JSON object")
    return cast(Mapping[str, Any], value)


def _citation_ranks(value: object) -> tuple[int, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ValueError("citation_ranks must be a list")
    ranks: list[int] = []
    for item in cast(list[object], value):
        rank = _int_or_none(item)
        if rank is None or rank <= 0:
            raise ValueError("citation rank must be a positive integer")
        ranks.append(rank)
    return tuple(dict.fromkeys(ranks))


def _int_or_none(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


__all__ = [
    "ConversationGenerationRequest",
    "ConversationGenerationResult",
    "ConversationGenerationRuntimeProtocol",
    "GroundedConversationGenerationRuntime",
    "GroundedReplyDraft",
    "GroundedReplySegment",
    "parse_grounded_reply_draft",
    "render_grounded_reply",
]
