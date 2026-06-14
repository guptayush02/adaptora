"""Shared BPE token counting helper.

Word-count (``len(text.split())``) badly under-counts non-Latin scripts —
a Hindi prompt and its English translation often have the same word count
but the Hindi text takes 5-7× more BPE tokens. That mismatch caused the
"original vs optimized graph shows equal bars" bug on the dashboard AND
the "Saved 0 tokens" bug on the optimize preview modal.

Both the middleware (per-turn DB accounting) and the optimizer (preview
modal's ``tokens_saved`` value) call ``count_tokens()`` so a single
encoder is loaded once and shared across the pipeline.
"""

from __future__ import annotations

from app.core.logger import logger


_TIKTOKEN_ENC = None  # None = not yet tried; False = tried and failed


def _get_token_encoder():
    global _TIKTOKEN_ENC
    if _TIKTOKEN_ENC is None:
        try:
            import tiktoken

            # cl100k_base is GPT-3.5/4's encoding — close enough for our
            # "before vs after" UI estimate. We don't need per-model
            # accuracy here; we need the dashboard to reflect that
            # non-Latin scripts are dense.
            _TIKTOKEN_ENC = tiktoken.get_encoding("cl100k_base")
        except Exception as exc:  # pragma: no cover — tiktoken absent / offline
            logger.warning(
                f"tiktoken unavailable, falling back to word-count: {exc}"
            )
            _TIKTOKEN_ENC = False
    return _TIKTOKEN_ENC or None


def count_tokens(text: str) -> int:
    """Best-effort BPE token count. Falls back to ``len(text.split())`` only
    when tiktoken can't load (install missing / offline)."""
    if not text:
        return 0
    enc = _get_token_encoder()
    if enc is not None:
        try:
            return len(enc.encode(text))
        except Exception:
            pass
    return len(text.split())
