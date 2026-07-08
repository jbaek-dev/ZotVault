"""Minimal message catalog. English is the default; other locales are opt-in
via [app] language. Business logic must never hardcode user-facing strings —
call t(key, **kw) instead. Keys missing from a locale fall back to English.
"""
from __future__ import annotations

from typing import Dict

_EN: Dict[str, str] = {
    "log.backfill_title": "ZotVault initial registration (backfill)",
    "log.sync_title": "ZotVault automatic sync",
    "log.notes_created": "{n} note(s) created ({items})",
    "log.pdfs_fetched": "{n} PDF(s) obtained via open access ({items})",
    "log.analyses_detected": "{n} analysis file(s) detected ({items})",
    "log.deleted_in_zotero": "{n} item(s) deleted in Zotero (vault untouched)",
    "log.files_field": "{papers_subdir}/ (auto), state: ~/.zotvault/state.db",
    "log.annotations_updated": "annotation block updated in {n} note(s) ({items})",
}

_KO: Dict[str, str] = {
    "log.backfill_title": "ZotVault 초기 등록(backfill)",
    "log.sync_title": "ZotVault 자동 동기화",
    "log.notes_created": "노트 {n}건 생성({items})",
    "log.pdfs_fetched": "PDF {n}건 OA 확보({items})",
    "log.analyses_detected": "분석완료 감지 {n}건({items})",
    "log.deleted_in_zotero": "Zotero 삭제 감지 {n}건(볼트는 미변경)",
    "log.files_field": "{papers_subdir}/ (자동), state: ~/.zotvault/state.db",
    "log.annotations_updated": "주석 블록 갱신 {n}건({items})",
}

_CATALOGS: Dict[str, Dict[str, str]] = {"en": _EN, "ko": _KO}

_current = "en"


def set_language(lang: str) -> None:
    global _current
    _current = lang if lang in _CATALOGS else "en"


def t(key: str, **kw: object) -> str:
    template = _CATALOGS.get(_current, _EN).get(key) or _EN.get(key, key)
    try:
        return template.format(**kw)
    except (KeyError, IndexError):
        return template
