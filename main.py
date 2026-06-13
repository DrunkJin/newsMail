"""뉴스 수집 → Gemini 요약 → Gmail 발송 오케스트레이션."""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

import yaml

import fetch
import mailer
import summarize

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("main")

CONFIG_PATH = Path(__file__).parent / "config" / "sources.yaml"


def _require_env(name: str) -> str:
    # GitHub Secret 등록 과정에서 trailing \n이나 BOM이 섞일 수 있어 강하게 정제한다.
    raw = os.environ.get(name, "")
    val = raw.lstrip("﻿").strip()
    if not val:
        log.error("환경변수 %s 가 설정되지 않았습니다.", name)
        sys.exit(1)
    return val


def main() -> None:
    gemini_key = _require_env("GEMINI_API_KEY")
    gmail_user = _require_env("GMAIL_USER")
    gmail_pass = _require_env("GMAIL_APP_PASSWORD")
    recipient = _require_env("MAIL_RECIPIENT")

    summarize.configure(gemini_key)

    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    lookback = int(config.get("lookback_hours", 12))
    max_per_cat = int(config.get("max_articles_per_category", 30))

    articles_by_cat: dict[str, list[fetch.Article]] = {}
    for category, cfg in config["categories"].items():
        log.info("=== 수집: %s ===", category)
        arts = fetch.fetch_category(cfg["sources"], lookback, max_per_cat)
        log.info("총 %d건 수집 (dedup 후)", len(arts))
        articles_by_cat[category] = arts

    total = sum(len(v) for v in articles_by_cat.values())
    if total == 0:
        log.warning("수집된 기사가 없습니다. 발송을 건너뜁니다.")
        return

    log.info("=== Gemini 요약 시작 ===")
    summaries = summarize.summarize_all(articles_by_cat)

    log.info("=== 이메일 발송 ===")
    mailer.send(gmail_user, gmail_pass, recipient, summaries, articles_by_cat)
    log.info("완료.")


if __name__ == "__main__":
    main()
