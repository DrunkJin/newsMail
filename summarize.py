"""Gemini REST API로 카테고리별 기사를 한국어로 요약한다.

google-generativeai SDK는 timeout/retry 제어가 불완전하고 "503 Illegal metadata" 같은
gRPC 이슈가 있어, 가벼운 REST 직접 호출로 대체한다.
"""
from __future__ import annotations

import logging
from typing import Sequence

import requests

from fetch import Article

log = logging.getLogger(__name__)

_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
PRIMARY_MODEL = "gemini-2.5-pro"
FALLBACK_MODEL = "gemini-2.5-flash"
_TIMEOUT_SEC = 45  # 카테고리당 최대 대기

_API_KEY: str | None = None
# 한 번 Pro가 실패하면 이번 run 내에서는 곧장 Flash로 — 시간 낭비 방지.
_pro_disabled: bool = False

PROMPT_TEMPLATE = """당신은 한국어 뉴스 큐레이터입니다. 아래는 "{category}" 분야의 최근 뉴스 기사 목록입니다.
독자가 원문을 읽지 않고도 사안을 충분히 이해할 수 있는 **깊이 있는 요약**을 작성하세요.

각 주요 이슈마다 정확히 아래 3줄 블록 형식으로 작성합니다:

• **헤드라인 (15~30자, 신문 1면 톤, 굵게)**
본문 3~5문장. 첫 문장에서 핵심 사실(누가·무엇·언제·어디)을 제시하고, 이어서 배경·맥락, 그리고 의미·파급효과를 서술하세요. 구체적인 숫자, 인용, 인물·기관명을 적극 활용하고 추측·의견은 배제합니다.
(출처: 매체A, 매체B)

요구사항:
- 주요 이슈 4~6개 선정 (덜 중요한 건 과감히 제외)
- 같은 이슈를 여러 매체가 보도하면 하나로 통합, 출처는 콤마로 나열
- 중요도 순으로 정렬
- 사실만 객관적으로 전달
- 머리말·맺음말 없이 위 블록만 반복 출력
- 각 블록 사이는 빈 줄 1개로 구분

기사 목록:
{articles}
"""


def configure(api_key: str) -> None:
    global _API_KEY, _pro_disabled
    _API_KEY = api_key
    _pro_disabled = False


def _format_articles(articles: Sequence[Article]) -> str:
    lines = []
    for i, a in enumerate(articles, 1):
        snippet = f" | 내용: {a.summary}" if a.summary else ""
        lines.append(f"[{i}] 매체: {a.source} | 제목: {a.title}{snippet}")
    return "\n".join(lines)


def _call_gemini(model_name: str, prompt: str) -> str:
    if not _API_KEY:
        raise RuntimeError("API key not configured — call configure() first")

    url = f"{_BASE}/{model_name}:generateContent"
    resp = requests.post(
        url,
        params={"key": _API_KEY},
        json={"contents": [{"parts": [{"text": prompt}]}]},
        timeout=_TIMEOUT_SEC,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"{model_name} HTTP {resp.status_code}: {resp.text[:300]}")

    data = resp.json()
    candidates = data.get("candidates") or []
    if not candidates:
        # block된 경우 promptFeedback에 이유 있음
        raise RuntimeError(f"{model_name} no candidates: {str(data)[:300]}")
    parts = candidates[0].get("content", {}).get("parts") or []
    text = "".join(p.get("text", "") for p in parts).strip()
    if not text:
        raise RuntimeError(f"{model_name} returned empty text")
    return text


def summarize_category(category: str, articles: Sequence[Article]) -> str:
    global _pro_disabled

    if not articles:
        return "_(이 시간대에 수집된 기사가 없습니다.)_"

    prompt = PROMPT_TEMPLATE.format(category=category, articles=_format_articles(articles))

    if not _pro_disabled:
        try:
            log.info("summarizing %s with %s (%d articles)", category, PRIMARY_MODEL, len(articles))
            return _call_gemini(PRIMARY_MODEL, prompt)
        except Exception as e:
            log.warning("primary failed for %s: %s — disabling Pro for this run, falling back to %s",
                        category, e, FALLBACK_MODEL)
            _pro_disabled = True

    try:
        log.info("summarizing %s with %s (%d articles)", category, FALLBACK_MODEL, len(articles))
        return _call_gemini(FALLBACK_MODEL, prompt)
    except Exception as e:
        log.error("fallback also failed for %s: %s", category, e)
        lines = [f"• {a.title} (출처: {a.source})" for a in articles[:8]]
        return "\n".join(lines) + "\n\n_(AI 요약 실패 — 헤드라인만 표시)_"


def summarize_all(categories: dict[str, list[Article]]) -> dict[str, str]:
    return {cat: summarize_category(cat, arts) for cat, arts in categories.items()}
