"""Gemini API로 카테고리별 기사를 한국어로 요약한다. Pro 우선 + Flash fallback."""
from __future__ import annotations

import logging
import os
from typing import Sequence

import google.generativeai as genai

from fetch import Article

log = logging.getLogger(__name__)

PRIMARY_MODEL = "gemini-2.5-pro"
FALLBACK_MODEL = "gemini-2.5-flash"

PROMPT_TEMPLATE = """당신은 한국어 뉴스 큐레이터입니다. 아래는 "{category}" 분야의 최근 뉴스 기사 목록입니다.
이 기사들을 종합해서 독자에게 핵심을 전달하는 요약을 작성하세요.

요구사항:
- 주요 이슈 3~6개를 추려서 각각을 한 개의 bullet로 작성
- 각 bullet은 1~2문장의 자연스러운 한국어로 작성 (신문 헤드라인 톤)
- 같은 이슈를 여러 매체가 보도하면 하나로 통합
- bullet 끝에 "(출처: 매체명1, 매체명2)" 형식으로 출처 표기
- 각 bullet 시작은 "• " 로 통일
- 사실만 객관적으로 전달, 추측·의견 금지
- 중요도 순으로 정렬
- 머리말·맺음말 없이 bullet만 출력

기사 목록:
{articles}
"""


def _format_articles(articles: Sequence[Article]) -> str:
    lines = []
    for i, a in enumerate(articles, 1):
        snippet = f" | 내용: {a.summary}" if a.summary else ""
        lines.append(f"[{i}] 매체: {a.source} | 제목: {a.title}{snippet}")
    return "\n".join(lines)


def _try_model(model_name: str, prompt: str) -> str:
    model = genai.GenerativeModel(model_name)
    resp = model.generate_content(prompt)
    text = (resp.text or "").strip()
    if not text:
        raise RuntimeError(f"{model_name} returned empty text")
    return text


def summarize_category(category: str, articles: Sequence[Article]) -> str:
    if not articles:
        return "_(이 시간대에 수집된 기사가 없습니다.)_"

    prompt = PROMPT_TEMPLATE.format(category=category, articles=_format_articles(articles))

    try:
        log.info("summarizing %s with %s (%d articles)", category, PRIMARY_MODEL, len(articles))
        return _try_model(PRIMARY_MODEL, prompt)
    except Exception as e:
        log.warning("primary model failed for %s: %s — falling back to %s", category, e, FALLBACK_MODEL)
        try:
            return _try_model(FALLBACK_MODEL, prompt)
        except Exception as e2:
            log.error("fallback model also failed for %s: %s", category, e2)
            # 최후수단: AI 요약 없이 헤드라인만 나열
            lines = [f"• {a.title} (출처: {a.source})" for a in articles[:8]]
            return "\n".join(lines) + "\n\n_(AI 요약 실패 — 헤드라인만 표시)_"


def configure(api_key: str) -> None:
    genai.configure(api_key=api_key)


def summarize_all(categories: dict[str, list[Article]]) -> dict[str, str]:
    return {cat: summarize_category(cat, arts) for cat, arts in categories.items()}
