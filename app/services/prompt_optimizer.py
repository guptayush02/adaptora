import re
import requests
from typing import Optional
from app.core.config import settings
from app.core.logger import logger
from app.core.tokens import count_tokens
from app.models.schema import PromptOptimization


# Unicode ranges for the major non-Latin scripts users actually type prompts
# in. If the prompt contains a meaningful fraction of these characters we
# treat it as non-English and ask Ollama to translate-AND-optimize in one go.
_NON_LATIN_RANGES = (
    (0x0900, 0x097F),  # Devanagari (Hindi, Marathi, Sanskrit)
    (0x0980, 0x09FF),  # Bengali / Assamese
    (0x0A00, 0x0A7F),  # Gurmukhi (Punjabi)
    (0x0A80, 0x0AFF),  # Gujarati
    (0x0B00, 0x0B7F),  # Oriya
    (0x0B80, 0x0BFF),  # Tamil
    (0x0C00, 0x0C7F),  # Telugu
    (0x0C80, 0x0CFF),  # Kannada
    (0x0D00, 0x0D7F),  # Malayalam
    (0x0D80, 0x0DFF),  # Sinhala
    (0x0600, 0x06FF),  # Arabic
    (0x0750, 0x077F),  # Arabic Supplement
    (0x0590, 0x05FF),  # Hebrew
    (0x0400, 0x04FF),  # Cyrillic
    (0x0370, 0x03FF),  # Greek
    (0x4E00, 0x9FFF),  # CJK Unified Ideographs (Chinese, Japanese kanji)
    (0x3040, 0x309F),  # Hiragana
    (0x30A0, 0x30FF),  # Katakana
    (0xAC00, 0xD7AF),  # Hangul Syllables (Korean)
    (0x0E00, 0x0E7F),  # Thai
)


def _is_non_latin(ch: str) -> bool:
    cp = ord(ch)
    for lo, hi in _NON_LATIN_RANGES:
        if lo <= cp <= hi:
            return True
    return False


# Hinglish marker words: Hindi typed in Latin script. Most are unlikely to
# appear in legitimate English text. If two or more of these show up, we
# treat the prompt as non-English so it routes through the translate path
# rather than going through the (English-only) optimizer.
_HINGLISH_MARKERS = (
    # time / recency
    "aaj", "kal", "abhi", "kabhi", "jaldi", "baad",
    # question words
    "kya", "kyun", "kyon", "kaise", "kaisa", "kaisi", "kab",
    "kaha", "kahan", "kitna", "kitne", "kitni", "kaun", "kis",
    # copula / particles
    "hai", "hain", "tha", "thi", "hoga", "hogi", "honge",
    # postpositions
    "mein", "ka", "ki", "ke", "ko", "se", "ne", "par", "pe",
    # pronouns
    "tum", "tu", "aap", "mujhe", "tujhe", "hume", "tumhe",
    "mera", "meri", "mere", "tera", "teri", "tere",
    "uska", "uski", "uske", "iska", "iski", "iske",
    # common verbs
    "bata", "batao", "batana", "karo", "karna", "kar", "karta",
    "karte", "karti", "hua", "hui", "huye", "hone",
    "chahiye", "chahta", "chahti", "lagta", "lagti", "lagega",
    # negations / particles
    "nahi", "nahin", "mat", "haan", "bhi", "toh", "phir",
    # demonstratives
    "yeh", "woh", "yaha", "wahan", "yahan", "waha",
    # other very common Hinglish words
    "matlab", "samajh", "samjha", "samjhi",
    "bohot", "bahut", "thoda", "thodi", "kuch", "saara", "sab",
)


def _is_hinglish(prompt: str, min_matches: int = 2) -> bool:
    """Detect Hinglish (Hindi typed in Latin script). Counts DISTINCT
    Hinglish marker words present (word-boundary match). Requires
    `min_matches` to avoid false positives — a single 'me' or 'to' isn't
    enough since those exist in English too."""
    if not prompt:
        return False
    text = prompt.lower()
    seen = set()
    for marker in _HINGLISH_MARKERS:
        if marker in seen:
            continue
        if re.search(r"\b" + re.escape(marker) + r"\b", text):
            seen.add(marker)
            if len(seen) >= min_matches:
                return True
    return False


def _detect_non_english(prompt: str, threshold: float = 0.25) -> bool:
    """Heuristic language check: True when EITHER
      • more than `threshold` (default 25%) of the letter-like characters
        live in a non-Latin script (Hindi-Devanagari, Arabic, CJK, …), OR
      • the prompt contains two or more Hinglish marker words (Latin-script
        Hindi like 'aaj kya hai').
    Both paths route the prompt through the translate-then-optimize
    pipeline. Cheap and dependency-free."""
    if _is_hinglish(prompt):
        return True
    letters = [ch for ch in prompt if ch.isalpha()]
    if not letters:
        return False
    non_latin = sum(1 for ch in letters if _is_non_latin(ch))
    return (non_latin / len(letters)) > threshold


class PromptOptimizer:
    """Optimize prompts using Ollama"""

    def __init__(self):
        """Initialize prompt optimizer"""
        self.ollama_url = settings.OLLAMA_API_URL
        self.model = settings.OLLAMA_MODEL
        self.timeout = settings.OLLAMA_TIMEOUT

    # Words that carry TIME/RECENCY meaning. The optimizer must NEVER drop
    # these — losing them turns a "today's weather" query into "weather", which
    # then fails the internet-needed classifier and gives stale answers.
    # Kept as separate tokens so we can both:
    #   1. Tell the Ollama optimizer to preserve them (in the prompt below)
    #   2. Post-check the result and reject rewrites that strip them
    _PRESERVED_TIME_WORDS = (
        "today", "tomorrow", "yesterday",
        "now", "currently", "current", "right now",
        "latest", "recent", "recently",
        "this week", "this month", "this year",
        "last week", "last month", "last year",
        "next week", "next month", "next year",
        "tonight", "this morning", "this evening", "this afternoon",
        "live", "real-time", "real time",
        "breaking", "trending", "happening",
    )

    # Common verbose phrases that almost never carry meaning. Used by the
    # deterministic fallback so a real reduction is always produced even when
    # Ollama is slow, returns garbage JSON, or is unreachable.
    _FILLER_PATTERNS = [
        r"^\s*please\s+",
        r"^\s*hey[,!]?\s+",
        r"^\s*hi[,!]?\s+",
        r"^\s*hello[,!]?\s+",
        r"^\s*so[,]?\s+",
        r"\bcould you (?:please |kindly )?",
        r"\bwould you (?:please |kindly )?(?:mind\s+)?",
        r"\bif (?:it'?s |it is )?possible[,]?\s*",
        r"\bif you (?:don'?t |do not )?mind[,]?\s*",
        r"\bi (?:would|'?d) (?:really |kindly )?(?:like|appreciate it if you could)\s+(?:to\s+)?",
        r"\bi want you to\s+",
        r"\bi was (?:just )?wondering (?:if )?",
        r"\bi[' ]?am wondering (?:if )?",
        r"\bplease make sure (?:to|that)\s+",
        r"\bbe sure (?:to|that)\s+",
        r"\bi am (?:looking|trying) (?:to|for)\s+",
        r"\bi need to know\s+",
        r"\bcan you (?:please |kindly )?",
        r"\bin a (?:brief|short|quick|nutshell)\s+(?:way|manner)?[,]?\s*",
        r"\bvery (?:much )?",
        r"\bquite\s+",
        r"\breally\s+",
        r"\bbasically\s+",
        r"\bactually\s+",
        r"\bjust\s+",
        r"\bthank you (?:so much |very much )?(?:in advance )?[.,]?\s*",
        r"\bthanks (?:so much |a lot |in advance )?[.,]?\s*",
    ]

    # Verbose phrases → shorter equivalents. Applied BEFORE the filler-strip
    # so a sentence like "in order to find a number of options due to the
    # fact that …" collapses to "to find several options because …". Each
    # rule must preserve meaning — these are well-known synonym pairs.
    _VERBOSE_SUBSTITUTIONS = [
        (r"\bin order to\b", "to"),
        (r"\bin order for\b", "for"),
        (r"\bdue to the fact that\b", "because"),
        (r"\bowing to the fact that\b", "because"),
        (r"\bfor the reason that\b", "because"),
        (r"\bin the event that\b", "if"),
        (r"\bon the condition that\b", "if"),
        (r"\bat the present time\b", "now"),
        (r"\bat this point in time\b", "now"),
        (r"\bat this moment in time\b", "now"),
        (r"\bin the near future\b", "soon"),
        (r"\bin the past\b", "previously"),
        (r"\bfor the purpose of\b", "for"),
        (r"\bwith regard to\b", "about"),
        (r"\bwith respect to\b", "about"),
        (r"\bin reference to\b", "about"),
        (r"\bin terms of\b", "for"),
        (r"\bin the case of\b", "for"),
        (r"\bin spite of\b", "despite"),
        (r"\ba large number of\b", "many"),
        (r"\ba great deal of\b", "much"),
        (r"\ba number of\b", "several"),
        (r"\bthe majority of\b", "most"),
        (r"\ba majority of\b", "most"),
        (r"\bprior to\b", "before"),
        (r"\bsubsequent to\b", "after"),
        (r"\bas a matter of fact\b", "actually"),
        (r"\bthe question (?:as to )?whether\b", "whether"),
        (r"\bthe reason why\b", "why"),
        (r"\bin spite of the fact that\b", "although"),
        (r"\bdespite the fact that\b", "although"),
        (r"\bnotwithstanding the fact that\b", "although"),
        (r"\bregardless of the fact that\b", "although"),
        (r"\bgiven the fact that\b", "since"),
        (r"\bin light of the fact that\b", "since"),
        (r"\bin view of the fact that\b", "since"),
        (r"\bit is important to note that\b", ""),
        (r"\bit should be noted that\b", ""),
        (r"\bit is worth (?:noting|mentioning) that\b", ""),
        (r"\bplease (?:note|be advised) that\b", ""),
        (r"\bkindly note that\b", ""),
    ]

    # Re-usable preservation rules shared between the English-only and the
    # translate-and-optimize prompts. Centralised so a fix to "what counts as
    # important" doesn't have to be made in two places.
    _PRESERVATION_RULES = (
        "PRESERVE these word classes verbatim — losing any of them changes "
        "the meaning of the prompt:\n"
        "- TIME / RECENCY: today, tomorrow, yesterday, now, current, "
        "currently, latest, recent, this week, this month, this year, "
        "tonight, live, real-time, breaking, trending.\n"
        "- QUESTION WORDS: who, what, when, where, why, how, which.\n"
        "- NEGATIONS: not, never, no, none, without, except.\n"
        "- PROPER NOUNS / NAMED ENTITIES: cities, countries, people, "
        "companies, products, brands, programming languages, model names.\n"
        "- NUMBERS, UNITS, CURRENCIES: \"10\", \"5kg\", \"$20\", "
        "\"3.5 GHz\", \"version 17\".\n"
        "- TECHNICAL TERMS and ACRONYMS: API, SQL, JSON, GPU, etc."
    )

    def optimize(
        self, prompt: str, status_callback=None
    ) -> PromptOptimization:
        """Optimize prompt. Always returns a PromptOptimization.

        - English prompts: ask Ollama to shorten while preserving every
          word class in `_PRESERVATION_RULES`.
        - Non-English prompts: a TWO-STEP pipeline — first a plain-text
          translate-to-English call (no JSON required, works on smaller /
          code-focused models like qwen2.5-coder:3b), then the regular
          English optimizer on the translated text. This is the fix for
          the bug where the structured translate-and-optimize prompt would
          silently fail (model echoed back the Hindi) and the deterministic
          fallback then returned the un-translated original.

        Prompts under 6 ASCII-only words skip the LLM round-trip and go
        straight to the deterministic stripper. Non-English short prompts
        still go through Ollama so they get translated.

        `status_callback(step, data)` — optional; lets the streaming /api/optimize
        endpoint emit fine-grained progress events (translating /
        optimizing / etc.) to the UI."""
        def _emit(step: str, **data):
            if status_callback:
                try:
                    status_callback(step, data)
                except Exception as e:
                    logger.warning(f"optimize status_callback failed: {e}")

        word_count = len(prompt.split())

        # Primary: ask Ollama itself whether the prompt is English. Replaces
        # the old keyword-based `_is_hinglish` / Unicode-block detection
        # (which missed ambiguous Hinglish like "aaj ne US ke latest news").
        # On Ollama unreachable / bad output we fall back to the keyword
        # detector so the pipeline never breaks.
        classifier_result = self._classify_is_english_via_ollama(prompt)
        if classifier_result is None:
            keyword_non_english = _detect_non_english(prompt)
            is_non_english = keyword_non_english
            detection_method = "keyword_fallback"
            logger.info(
                f"Language detection: Ollama classifier unavailable; "
                f"falling back to keyword detector "
                f"(is_non_english={is_non_english})"
            )
        else:
            is_non_english = not classifier_result
            detection_method = "ollama_classifier"
            logger.info(
                f"Language detection (ollama): "
                f"is_english={classifier_result}, "
                f"is_non_english={is_non_english}"
            )

        _emit(
            "language_detected",
            is_non_english=is_non_english,
            word_count=word_count,
            method=detection_method,
        )

        if word_count < 6 and not is_non_english:
            # Skip the slow Ollama optimization call, but still run the
            # deterministic strip so the optimization step always produces a
            # real result.
            return self._deterministic_optimize(prompt)

        # Non-English path: translate first (plain text), then optimize the
        # English version with the regular flow.
        if is_non_english:
            _emit("translating", source_lang="non_english")
            translated = self._translate_to_english(prompt)
            if not translated:
                logger.warning(
                    f"Translation of non-English prompt failed; returning "
                    f"original unchanged: {prompt[:80]!r}"
                )
                _emit("translation_failed")
                return PromptOptimization(
                    original_prompt=prompt,
                    optimized_prompt=prompt,
                    optimization_reason=(
                        "Translation failed (model couldn't translate); "
                        "using original prompt"
                    ),
                    tokens_saved=0,
                    optimization_percentage=0.0,
                )
            logger.info(
                f"Translated non-English prompt → English: "
                f"{translated[:120]!r}"
            )
            _emit("translated", english_prompt=translated)
            # Now optimize the English version. Mirror the English-path guard
            # above (word_count < 6): a very short prompt is already minimal,
            # so handing it to the aggressive LLM optimizer buys no real
            # savings and risks SEMANTIC DRIFT — the weather-heavy few-shots
            # in _build_english_optimize_prompt would, for a 3-word input like
            # "today's news", happily rewrite it to "today's weather". The
            # deterministic pass only strips filler, so it can never change
            # the meaning. This is content-agnostic: it protects every short
            # translated prompt in any language, not just this one phrase.
            if len(translated.split()) < 6:
                english_result = self._deterministic_optimize(translated)
            else:
                english_result = self._optimize_english_via_ollama(
                    translated, original_for_fallback=translated
                )
            # Rewrap so original_prompt is the user's actual (non-English)
            # input and tokens_saved compares the right things. Word counts
            # were the wrong primitive here — Hindi packs ~5× more BPE
            # tokens per word than English so two equal word counts hid
            # huge real savings. Use the BPE counter instead.
            original_tokens = count_tokens(prompt)
            optimized_tokens = count_tokens(english_result.optimized_prompt)
            tokens_saved = max(0, original_tokens - optimized_tokens)
            pct = (tokens_saved / original_tokens * 100) if original_tokens else 0.0
            return PromptOptimization(
                original_prompt=prompt,
                optimized_prompt=english_result.optimized_prompt,
                optimization_reason=(
                    "Translated to English"
                    + (f" + {english_result.optimization_reason}"
                       if english_result.optimization_reason
                       and english_result.optimization_reason
                       != "Removed common filler phrases"
                       else "")
                ),
                tokens_saved=tokens_saved,
                optimization_percentage=pct,
            )

        # English path: existing single-call optimizer.
        _emit("optimizing", lang="english")
        return self._optimize_english_via_ollama(prompt, original_for_fallback=prompt)

    def _optimize_english_via_ollama(
        self, prompt: str, original_for_fallback: str
    ) -> PromptOptimization:
        """Run the English JSON-output optimizer on `prompt`. Falls back to
        the deterministic filler stripper on any Ollama / parsing failure.
        Extracted so the non-English two-step pipeline can reuse it on the
        translated text."""
        word_count = len(prompt.split())
        try:
            optimization_prompt = self._build_english_optimize_prompt(prompt)
            response = requests.post(
                f"{self.ollama_url}/api/generate",
                json={
                    "model": self.model,
                    "prompt": optimization_prompt,
                    "stream": False,
                    # Pin to deterministic output and a tight token budget.
                    # Without these the model occasionally answers the prompt
                    # (long, creative) instead of rewriting it (short, JSON).
                    "options": {
                        "temperature": 0,
                        "num_predict": 256,
                    },
                },
                timeout=(settings.OLLAMA_CONNECT_TIMEOUT, self.timeout),
            )
            if response.status_code == 200:
                response_text = response.json().get("response", "")
                extracted = self._extract_optimization(response_text, prompt)
                if extracted and extracted.tokens_saved > 0:
                    logger.info(
                        f"Optimizer (Ollama, english): {word_count} → "
                        f"{len(extracted.optimized_prompt.split())} words "
                        f"({extracted.tokens_saved} saved, "
                        f"{extracted.optimization_percentage:.1f}%)"
                    )
                    return extracted
                if extracted:
                    logger.info(
                        f"Optimizer (Ollama): no reduction "
                        f"(returned {len(extracted.optimized_prompt.split())} "
                        f"words); trying deterministic fallback"
                    )
                else:
                    logger.warning(
                        f"Optimizer (Ollama): could not parse JSON "
                        f"(first 200 chars: {response_text[:200]!r}); "
                        f"trying deterministic fallback"
                    )
            else:
                # Surface the response body so 404s (model not pulled),
                # 503s (Ollama not warmed up), etc. are diagnosable from
                # one log line.
                body_hint = ""
                try:
                    err = response.json()
                    if isinstance(err, dict) and err.get("error"):
                        body_hint = f" — {err['error']}"
                except Exception:
                    body_hint = (
                        f" — body[:200]={response.text[:200]!r}"
                        if response.text
                        else ""
                    )
                logger.warning(
                    f"Optimizer (Ollama): status {response.status_code}"
                    f"{body_hint}; model={self.model!r} on "
                    f"{self.ollama_url!r}; trying deterministic fallback"
                )
        except (requests.exceptions.ConnectTimeout, requests.exceptions.ConnectionError) as e:
            logger.error(
                f"Optimizer: cannot reach Ollama at {self.ollama_url} "
                f"({e.__class__.__name__}). Falling back to deterministic optimization. "
                "Check EC2 security group + OLLAMA_HOST=0.0.0.0."
            )
        except Exception as e:
            logger.error(f"Optimizer (Ollama) error: {e}; trying deterministic fallback")

        # Deterministic fallback — guaranteed to produce *some* output.
        return self._deterministic_optimize(original_for_fallback)

    def _classify_is_english_via_ollama(
        self, prompt: str
    ) -> Optional[bool]:
        """Ask Ollama whether the prompt is in English.

        Returns:
          True  → English (or close enough — accents / odd punctuation OK)
          False → non-English (Hindi script, Hinglish, Spanish, Arabic, …)
          None  → Ollama unreachable or response unparseable; caller should
                  fall back to the keyword detector.

        We do this instead of hard-coded marker lists because Hinglish like
        "aaj ne US ke latest news" looks like English to the Unicode check
        and was getting missed. Few-shots cover all the cases we've seen so
        far: pure English, Hinglish in Latin script, Devanagari Hindi,
        Spanish / Arabic / Chinese."""
        classifier_prompt = (
            "TASK: Decide whether the user's prompt is written in English.\n\n"
            "Count Hinglish (Hindi-words-in-Latin-script like 'aaj kya "
            "hai', 'kya tum mujhe bata sakte ho') as NOT English — those "
            "prompts need translation before the rest of the pipeline runs.\n\n"
            "English with stray non-English proper nouns (city names, "
            "brand names, foreign words quoted inside an English question) "
            "still counts as English.\n\n"
            "Reply with EXACTLY one word: YES (it is English) or NO. "
            "No other text.\n\n"
            "Examples:\n"
            "Q: aaj ne US ke latest news\nA: NO\n"
            "Q: kya tum mujhe iPhone 17 ka price bata sakte ho\nA: NO\n"
            "Q: mujhe aaj ka mausam bata\nA: NO\n"
            "Q: मुझे आज दिल्ली का मौसम बताओ\nA: NO\n"
            "Q: ¿Cuál es el precio actual de Bitcoin?\nA: NO\n"
            "Q: 今天东京的天气怎么样？\nA: NO\n"
            "Q: ما هو الطقس في القاهرة اليوم؟\nA: NO\n"
            "Q: what is the weather today in Toronto\nA: YES\n"
            "Q: latest news about Tesla\nA: YES\n"
            "Q: tell me about Akbar (Mughal emperor)\nA: YES\n"
            "Q: best café in Montréal — recommendations?\nA: YES\n"
            "Q: Translate 'hello' to French\nA: YES\n"
            "Q: Write a Python function to reverse a string\nA: YES\n\n"
            f"Q: {prompt}\nA:"
        )
        try:
            response = requests.post(
                f"{self.ollama_url}/api/generate",
                json={
                    "model": self.model,
                    "prompt": classifier_prompt,
                    "stream": False,
                    "options": {"temperature": 0, "num_predict": 5},
                },
                timeout=(settings.OLLAMA_CONNECT_TIMEOUT, 60),
            )
            if response.status_code != 200:
                logger.warning(
                    f"Language classifier: status {response.status_code}; "
                    f"falling back to keyword detection"
                )
                return None
            raw = (response.json().get("response", "") or "").strip().upper()
            first = raw.split()[0].rstrip(".,!?:;") if raw else ""
            if first in ("YES", "Y", "ENGLISH"):
                return True
            if first in ("NO", "N", "NOT"):
                return False
            logger.warning(
                f"Language classifier returned unrecognized response "
                f"{raw[:80]!r}; falling back to keyword detection"
            )
            return None
        except Exception as e:
            logger.warning(
                f"Language classifier call failed: {e}; falling back "
                f"to keyword detection"
            )
            return None

    # Two prompt styles for the translate-to-English step. The richer one is
    # tried first; if the model echoes the input back (common on code-focused
    # models like qwen2.5-coder:3b), we retry with a one-line prompt that
    # leaves the model less room to "ignore the instruction and just repeat".
    _TRANSLATE_PROMPTS = [
        (
            "structured",
            "Translate the text below into clear, natural English.\n\n"
            "RULES:\n"
            "- Output ONLY the English translation.\n"
            "- No quotes, no labels, no explanation, no 'Sure, here is …'.\n"
            "- If the text is ALREADY English, output it unchanged.\n"
            "- Preserve all named entities (people, cities, products), "
            "numbers, and units.\n\n"
            "TEXT: {prompt}\n\n"
            "ENGLISH:"
        ),
        (
            "minimal",
            # One-line, no rule list. Some small models follow this better.
            "English translation of: {prompt}\n\nAnswer:"
        ),
    ]

    def _translate_to_english(self, prompt: str) -> Optional[str]:
        """Plain-text translation step. Tries two prompt styles in order:
          1. Structured prompt with explicit rules.
          2. One-line minimal prompt as a fallback when the structured one
             returns the input verbatim (qwen2.5-coder:3b echoes Hindi back
             on the structured prompt fairly often).
        Each attempt is logged so failures are visible in the server log.
        Returns the English string, or None if both attempts fail.

        Post-checks per attempt:
        - Response must be non-empty.
        - Response must NOT itself look non-English (else the model just
          echoed the input back)."""
        for attempt_name, template in self._TRANSLATE_PROMPTS:
            logger.info(
                f"Translate-to-English: attempt={attempt_name!r}, "
                f"input={prompt[:60]!r}"
            )
            translate_prompt = template.format(prompt=prompt)
            try:
                response = requests.post(
                    f"{self.ollama_url}/api/generate",
                    json={
                        "model": self.model,
                        "prompt": translate_prompt,
                        "stream": False,
                        "options": {
                            "temperature": 0,
                            "num_predict": 256,
                        },
                    },
                    timeout=(settings.OLLAMA_CONNECT_TIMEOUT, self.timeout),
                )
                if response.status_code != 200:
                    logger.warning(
                        f"Translate-to-English ({attempt_name}): status "
                        f"{response.status_code}"
                    )
                    continue
                raw = (response.json().get("response") or "").strip()
            except Exception as e:
                logger.warning(
                    f"Translate-to-English ({attempt_name}) call failed: {e}"
                )
                continue

            if not raw:
                logger.warning(
                    f"Translate-to-English ({attempt_name}): empty response"
                )
                continue

            cleaned = self._clean_translation_response(raw)
            if not cleaned:
                logger.warning(
                    f"Translate-to-English ({attempt_name}): nothing left "
                    f"after cleanup; raw was {raw[:120]!r}"
                )
                continue
            if _detect_non_english(cleaned):
                logger.warning(
                    f"Translate-to-English ({attempt_name}): response is "
                    f"still non-English (model echoed input back): "
                    f"{cleaned[:80]!r}"
                )
                continue

            logger.info(
                f"Translate-to-English ({attempt_name}) succeeded: "
                f"{cleaned[:120]!r}"
            )
            return cleaned

        logger.warning(
            f"Translate-to-English: all attempts failed for input "
            f"{prompt[:80]!r}"
        )
        return None

    @staticmethod
    def _clean_translation_response(raw: str) -> str:
        """Strip preamble noise ("ENGLISH:" / "Answer:" / "Sure, here is …" /
        outer quotes / trailing commentary) from a translate-to-English
        response, returning the bare English string. Pure string→string; the
        non-English detection lives in the caller."""
        if not raw:
            return ""
        cleaned = raw.strip()
        # Strip leading labels the model often emits.
        for prefix in (
            "ENGLISH:", "English:", "Translation:", "Translated:",
            "Answer:", "answer:",
        ):
            if cleaned.startswith(prefix):
                cleaned = cleaned[len(prefix):].strip()
                break
        # Drop a leading "Sure, here is …" sentence if present (anything up
        # to the first blank line).
        first_blank = cleaned.find("\n\n")
        if first_blank > 0 and any(
            cleaned.lower().startswith(p)
            for p in ("sure,", "here is", "here's", "of course")
        ):
            cleaned = cleaned[first_blank:].strip()
        # Strip outer quotes (and repeat once to handle smart quotes nested
        # inside ASCII quotes).
        cleaned = cleaned.strip().strip('"').strip("'").strip()
        cleaned = cleaned.strip("“”‘’").strip()
        # Take the first paragraph (model sometimes adds notes after).
        cleaned = cleaned.split("\n\n", 1)[0].strip()
        return cleaned

    def _build_english_optimize_prompt(self, prompt: str) -> str:
        """The standard 'shorten an English prompt' instruction. Aggressive
        few-shots — each example shows a 40–70% word-count reduction so the
        model picks up "compress hard" as the target pattern, not "trim a
        word or two". Also includes a counter-example where the input is
        already minimal and the output is identical."""
        return (
            "You are a prompt-rewriting tool. REWRITE the user's prompt into "
            "the SHORTEST, CLEAREST form that still asks the same thing. "
            "Aim for the minimum word count. You DO NOT answer the prompt; "
            "you only rewrite it.\n\n"
            f"{self._PRESERVATION_RULES}\n\n"
            "Each example below shows aggressive compression. Match this "
            "level of reduction:\n\n"
            'INPUT: "Could you please write a very detailed and thorough '
            'explanation of how machine learning works in plain language so '
            'that a beginner can easily understand it?"\n'
            'OUTPUT: {"optimized_prompt": "Explain how machine learning '
            'works for a beginner.", "reason": "Aggressive compression: '
            '20→8 words"}\n\n'
            'INPUT: "Hi, I was wondering if you could please help me figure '
            'out what is the capital city of France in a brief way thanks"\n'
            'OUTPUT: {"optimized_prompt": "What is the capital of France?", '
            '"reason": "Stripped pleasantries: 19→6 words"}\n\n'
            'INPUT: "Please tell me what the weather is like today in '
            'Toronto, I would really appreciate it if you could let me '
            'know."\n'
            'OUTPUT: {"optimized_prompt": "Weather in Toronto today?", '
            '"reason": "Kept today/Toronto: 19→4 words"}\n\n'
            'INPUT: "Can you please help me find out which one of the '
            'latest iPhone 17 Pro Max models has the best camera and how '
            'much does it currently cost in USD?"\n'
            'OUTPUT: {"optimized_prompt": "Best-camera iPhone 17 Pro Max '
            'and current USD price?", "reason": "Kept latest entities: '
            '24→9 words"}\n\n'
            'INPUT: "Please help me generate a follow-up email for a '
            'client thanking them for the demo and asking about next '
            'steps that we should take together."\n'
            'OUTPUT: {"optimized_prompt": "Write a client follow-up email '
            'thanking them for the demo and asking next steps.", "reason": '
            '"Removed verbose framing: 22→14 words"}\n\n'
            'INPUT: "In order to find a number of options due to the fact '
            'that the deadline is approaching I need help."\n'
            'OUTPUT: {"optimized_prompt": "Find several options — deadline '
            'approaching.", "reason": "Compressed verbose phrases: '
            '19→6 words"}\n\n'
            'INPUT: "What is the capital of France?"\n'
            'OUTPUT: {"optimized_prompt": "What is the capital of France?", '
            '"reason": "Already minimal, no change"}\n\n'
            "Now rewrite the next prompt. AIM FOR THE MINIMUM word count "
            "while keeping every PRESERVE-class word. Output ONLY the JSON.\n\n"
            f"INPUT: {prompt!r}\n"
            "OUTPUT:"
        )

    def _build_translate_and_optimize_prompt(self, prompt: str) -> str:
        """For non-English prompts: translate to English AND shorten in one
        step. Same preservation rules apply on the translated output."""
        return (
            "You are a prompt translator and rewriter. The user's prompt "
            "is NOT in English. Your job is to:\n"
            "  1. Translate it into clear, natural English.\n"
            "  2. Shorten the English translation if possible.\n"
            "You DO NOT answer the prompt — only translate-and-rewrite it.\n\n"
            f"{self._PRESERVATION_RULES}\n\n"
            "ALWAYS output English. The optimized_prompt field MUST be "
            "English even if the input is in any other script.\n\n"
            "Examples:\n\n"
            'INPUT (Hindi): "मुझे आज दिल्ली का मौसम बताओ"\n'
            'OUTPUT: {"optimized_prompt": "What is the weather in Delhi '
            'today?", "reason": "Translated from Hindi, kept today/Delhi"}\n\n'
            'INPUT (Spanish): "¿Cuál es el precio actual de Bitcoin en USD?"\n'
            'OUTPUT: {"optimized_prompt": "Current Bitcoin price in USD?", '
            '"reason": "Translated from Spanish, kept current/Bitcoin/USD"}\n\n'
            'INPUT (Hinglish): "kya tum mujhe iPhone 17 Pro ka latest '
            'price bata sakte ho?"\n'
            'OUTPUT: {"optimized_prompt": "What is the latest iPhone 17 '
            'Pro price?", "reason": "Translated from Hinglish, kept '
            'latest/iPhone 17 Pro"}\n\n'
            'INPUT (Arabic): "ما هو الطقس في القاهرة اليوم؟"\n'
            'OUTPUT: {"optimized_prompt": "What is the weather in Cairo '
            'today?", "reason": "Translated from Arabic, kept today/Cairo"}\n\n'
            "Now translate-and-rewrite the next prompt. Output English only. "
            "DO NOT answer it.\n\n"
            f"INPUT: {prompt!r}\n"
            "OUTPUT (return only the JSON object, no other text):"
        )

    def _no_op(self, prompt: str, reason: str) -> PromptOptimization:
        return PromptOptimization(
            original_prompt=prompt,
            optimized_prompt=prompt,
            optimization_reason=reason,
            tokens_saved=0,
            optimization_percentage=0.0,
        )

    def _deterministic_optimize(self, prompt: str) -> PromptOptimization:
        """Two-pass deterministic compressor:
          1. Replace verbose phrases with shorter equivalents
             ("in order to" → "to", "due to the fact that" → "because", …).
          2. Strip common filler / pleasantries.
        Both passes preserve the time / proper-noun / question / negation
        words listed in `_PRESERVATION_RULES`. The result is guaranteed to
        be a real PromptOptimization (never None) — used as the floor when
        the Ollama optimizer fails or returns no reduction."""
        optimized = prompt
        # Pass 1: verbose-phrase substitutions.
        for pattern, replacement in self._VERBOSE_SUBSTITUTIONS:
            optimized = re.sub(
                pattern, replacement, optimized, flags=re.IGNORECASE
            )
        # Pass 2: filler / pleasantry removal.
        for pattern in self._FILLER_PATTERNS:
            optimized = re.sub(pattern, "", optimized, flags=re.IGNORECASE)
        # Collapse runs of whitespace and trim
        optimized = re.sub(r"\s+", " ", optimized).strip()
        # Capitalize the first letter so the trimmed prompt still reads cleanly
        if optimized:
            optimized = optimized[0].upper() + optimized[1:]

        original_tokens = count_tokens(prompt)
        optimized_tokens = count_tokens(optimized)
        tokens_saved = max(0, original_tokens - optimized_tokens)
        pct = (tokens_saved / original_tokens * 100) if original_tokens else 0.0

        logger.info(
            f"Optimizer (deterministic): {original_tokens} → "
            f"{optimized_tokens} tokens ({tokens_saved} saved, {pct:.1f}%)"
        )
        return PromptOptimization(
            original_prompt=prompt,
            optimized_prompt=optimized or prompt,
            optimization_reason=(
                "Compressed verbose phrases and stripped filler"
                if tokens_saved > 0
                else "No deterministic patterns matched"
            ),
            tokens_saved=tokens_saved,
            optimization_percentage=pct,
        )

    def _extract_optimization(
        self,
        response_text: str,
        original_prompt: str,
        allow_translation: bool = False,
    ):
        """Extract optimization details from response. Tries several strategies
        because Ollama models occasionally wrap JSON in ```json fences, prefix
        it with prose, or omit it entirely.

        `allow_translation=True` is set when the upstream call was the
        translate-and-optimize prompt. In that mode the candidate is in a
        different language than the original, so the per-word "did you drop
        a time word?" check would always trip — we skip it and instead
        verify that the candidate is now in Latin script (i.e. actually
        translated to English)."""
        import json

        text = response_text.strip()
        # Strip leading/trailing markdown code fences if present
        fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        candidates = []
        if fenced:
            candidates.append(fenced.group(1))
        # Greedy match for the outermost {...} block — handles nested objects
        greedy = re.search(r"\{.*\}", text, re.DOTALL)
        if greedy:
            candidates.append(greedy.group(0))
        # Final fallback: try the raw text in case the response is just JSON
        candidates.append(text)

        for blob in candidates:
            try:
                data = json.loads(blob)
            except (json.JSONDecodeError, ValueError):
                continue
            if not isinstance(data, dict):
                continue

            raw_optimized = (
                data.get("optimized_prompt") or data.get("optimised_prompt") or ""
            )
            # Defensive: some models occasionally return optimized_prompt as a
            # nested dict (e.g. {"text": "...", "intent": "..."}). Coerce to a
            # string so .strip() doesn't blow up.
            if isinstance(raw_optimized, dict):
                raw_optimized = (
                    raw_optimized.get("text")
                    or raw_optimized.get("prompt")
                    or raw_optimized.get("content")
                    or ""
                )
            if not isinstance(raw_optimized, str):
                raw_optimized = str(raw_optimized)
            optimized_prompt = raw_optimized.strip()
            if not optimized_prompt:
                continue

            # Sanity check: reject responses that look like the LLM answered
            # the prompt instead of rewriting it. Symptoms include:
            #   - the "optimized" text is much LONGER than the original
            #   - it begins with greeting/closing phrases typical of answers
            if self._looks_like_answer(original_prompt, optimized_prompt):
                logger.warning(
                    f"Optimizer: rejected response that looks like an answer "
                    f"(orig {len(original_prompt.split())} words → returned "
                    f"{len(optimized_prompt.split())} words)"
                )
                continue

            if allow_translation:
                # Translation path — the per-word "time word still present"
                # check is meaningless (different language). Instead verify
                # the candidate is now Latin-script (i.e. actually English-
                # ish). If the model just echoed back the non-English input,
                # `_detect_non_english` will still flag it → reject.
                if _detect_non_english(optimized_prompt):
                    logger.warning(
                        "Optimizer (translate path): rejected response that "
                        "is still non-English; trying next candidate."
                    )
                    continue
            else:
                # Reject rewrites that dropped TIME / RECENCY words — those
                # words change the meaning of the query (a "today's weather"
                # prompt becomes "weather", which fails the internet-needed
                # classifier and serves stale info from training data).
                dropped = self._dropped_time_words(
                    original_prompt, optimized_prompt
                )
                if dropped:
                    logger.warning(
                        f"Optimizer: rejected rewrite that dropped time "
                        f"word(s) {dropped!r}; keeping original prompt"
                    )
                    continue

            reason = (
                data.get("reason")
                or data.get("optimization_reason")
                or "General optimization"
            )
            original_tokens = count_tokens(original_prompt)
            optimized_tokens = count_tokens(optimized_prompt)
            tokens_saved = max(0, original_tokens - optimized_tokens)
            save_percentage = (
                (tokens_saved / original_tokens * 100) if original_tokens > 0 else 0
            )

            return PromptOptimization(
                original_prompt=original_prompt,
                optimized_prompt=optimized_prompt,
                optimization_reason=reason,
                tokens_saved=tokens_saved,
                optimization_percentage=save_percentage,
            )

        return None

    # Phrases that typically open an answer rather than a rewritten prompt.
    _ANSWER_OPENERS = (
        "dear ",
        "hi ",
        "hello,",
        "sure,",
        "sure!",
        "of course",
        "here is",
        "here's",
        "i'd be happy",
        "i would be happy",
        "thank you for",
        "absolutely",
        "certainly",
        "<html",
        "```",
    )

    def _dropped_time_words(self, original: str, candidate: str) -> list:
        """Return the list of TIME / RECENCY words from `_PRESERVED_TIME_WORDS`
        that appeared in the original prompt but are missing from the
        candidate rewrite. Empty list = nothing was dropped.

        Matched with word boundaries (`\\b`) so "today" doesn't match inside
        a longer word like "today's" — which would create false-positive
        rejections. Multi-word phrases ("this week") just check substring."""
        orig_lc = original.lower()
        cand_lc = candidate.lower()
        dropped = []
        for word in self._PRESERVED_TIME_WORDS:
            if " " in word or "-" in word:
                if word in orig_lc and word not in cand_lc:
                    dropped.append(word)
            else:
                pattern = r"\b" + re.escape(word) + r"\b"
                if re.search(pattern, orig_lc) and not re.search(pattern, cand_lc):
                    dropped.append(word)
        return dropped

    def _looks_like_answer(self, original: str, candidate: str) -> bool:
        """Heuristic: detect when the LLM produced the answer rather than a
        rewritten prompt. Catches the common failure mode where the model
        responds to the instruction instead of meta-rewriting it."""
        if not candidate:
            return False

        orig_words = max(1, len(original.split()))
        cand_words = len(candidate.split())

        # A real rewrite should be shorter (or at most slightly longer). If it
        # blows past 1.3x the original, it's almost certainly an answer.
        if cand_words > orig_words * 1.3:
            return True

        lowered = candidate.lstrip().lower()
        for opener in self._ANSWER_OPENERS:
            if lowered.startswith(opener):
                return True

        return False

    def check_bypass_keywords(self, prompt: str) -> bool:
        """Check if prompt contains any bypass keyword as a whole word.

        Whole-word matching is important: substring matches caused common
        prompts containing "advanced", "directly", "critically", etc. to be
        misrouted to the advanced model regardless of complexity.
        """
        keywords = settings.BYPASS_KEYWORDS or []
        prompt_lower = prompt.lower()

        for keyword in keywords:
            kw = keyword.lower().strip()
            if not kw:
                continue
            # \b doesn't match around hyphens, so escape and use word boundaries
            pattern = r"\b" + re.escape(kw) + r"\b"
            if re.search(pattern, prompt_lower):
                logger.info(f"Bypass keyword detected: {keyword!r}")
                return True

        return False
