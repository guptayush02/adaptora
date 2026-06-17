import hashlib
import re
import time
import requests
from datetime import datetime
from typing import Any, Callable, Dict, List, Tuple, Optional
from app.core.config import settings
from app.core.logger import logger
from ddgs import DDGS
from googlesearch import search
import trafilatura

# Phrases Ollama models use when they bail out of a question because they lack
# fresh data or internet access. When the response contains any of these we
# transparently fall back to a DuckDuckGo search and re-ask the model with the
# results as context.
_NO_INTERNET_PATTERNS = (
    "don't have access to real-time",
    "do not have access to real-time",
    "cannot access real-time",
    "can't access real-time",
    "don't have real-time",
    "do not have real-time",
    "no real-time access",
    "cannot browse",
    "can't browse",
    "unable to browse",
    "cannot access the internet",
    "can't access the internet",
    "do not have access to the internet",
    "don't have access to the internet",
    "no access to the internet",
    "no internet access",
    "without internet access",
    "knowledge cutoff",
    "knowledge cut-off",
    "training data only goes",
    "training data ends",
    "as of my last update",
    "as of my last training",
    "as of my knowledge",
    "i don't have the latest",
    "i do not have the latest",
    "i don't have up-to-date",
    "i don't have up to date",
    "i don't have current",
    "i do not have current",
    "i am not able to provide real-time",
    "i'm not able to provide real-time",
    "i'm unable to provide real-time",
    "i cannot provide current",
    "i can't provide current",
)

def _response_indicates_no_internet(text: str) -> bool:
    """Heuristic: did the model bail out because it lacked fresh data?"""
    if not text:
        return False
    t = text.lower()
    return any(p in t for p in _NO_INTERNET_PATTERNS)

def _response_has_stale_year(text: str, results_block: str) -> bool:
    """Detect a training-data leak: the model named a year that's two or more
    years older than today AND that year does not appear anywhere in the
    search-result snippets. That combination almost always means the model
    ignored the search results and answered from its training cutoff (e.g.
    Mistral 7B → May 2023).

    Returns True only for `20YY` years (avoids false positives on history
    questions about Mughal-era dates etc.)."""
    if not text:
        return False
    current_year = datetime.now().year
    # Anything older than (current_year - 1) is suspicious. current_year - 1
    # itself is allowed because results can legitimately reference last year.
    threshold = current_year - 1
    response_years = set(re.findall(r"\b(20\d{2})\b", text))
    result_years = set(re.findall(r"\b(20\d{2})\b", results_block or ""))
    for y in response_years:
        try:
            yi = int(y)
        except ValueError:
            continue
        if yi < threshold and y not in result_years:
            return True
    return False

# City → IANA timezone for deterministic "current time in <city>" lookups.
# DuckDuckGo's text endpoint returns *article snippets*, so when a user asks
# "current time in Toronto" the model quotes whatever stale time appeared in
# a search-result snippet (e.g. "01:45 EDT"). Routing these queries through
# zoneinfo instead always yields the correct system-computed answer.
_CITY_TIMEZONES: Dict[str, str] = {
    # North America
    "toronto": "America/Toronto",
    "ottawa": "America/Toronto",
    "montreal": "America/Montreal",
    "vancouver": "America/Vancouver",
    "calgary": "America/Edmonton",
    "edmonton": "America/Edmonton",
    "winnipeg": "America/Winnipeg",
    "halifax": "America/Halifax",
    "new york": "America/New_York",
    "nyc": "America/New_York",
    "boston": "America/New_York",
    "miami": "America/New_York",
    "washington": "America/New_York",
    "atlanta": "America/New_York",
    "chicago": "America/Chicago",
    "dallas": "America/Chicago",
    "houston": "America/Chicago",
    "denver": "America/Denver",
    "phoenix": "America/Phoenix",
    "los angeles": "America/Los_Angeles",
    "san francisco": "America/Los_Angeles",
    "seattle": "America/Los_Angeles",
    "honolulu": "Pacific/Honolulu",
    "anchorage": "America/Anchorage",
    "mexico city": "America/Mexico_City",
    # South America
    "sao paulo": "America/Sao_Paulo",
    "rio de janeiro": "America/Sao_Paulo",
    "buenos aires": "America/Argentina/Buenos_Aires",
    "lima": "America/Lima",
    "bogota": "America/Bogota",
    "santiago": "America/Santiago",
    # Europe
    "london": "Europe/London",
    "dublin": "Europe/Dublin",
    "lisbon": "Europe/Lisbon",
    "madrid": "Europe/Madrid",
    "paris": "Europe/Paris",
    "amsterdam": "Europe/Amsterdam",
    "brussels": "Europe/Brussels",
    "berlin": "Europe/Berlin",
    "frankfurt": "Europe/Berlin",
    "rome": "Europe/Rome",
    "vienna": "Europe/Vienna",
    "zurich": "Europe/Zurich",
    "stockholm": "Europe/Stockholm",
    "oslo": "Europe/Oslo",
    "copenhagen": "Europe/Copenhagen",
    "helsinki": "Europe/Helsinki",
    "warsaw": "Europe/Warsaw",
    "prague": "Europe/Prague",
    "athens": "Europe/Athens",
    "istanbul": "Europe/Istanbul",
    "moscow": "Europe/Moscow",
    # Asia
    "tokyo": "Asia/Tokyo",
    "osaka": "Asia/Tokyo",
    "seoul": "Asia/Seoul",
    "beijing": "Asia/Shanghai",
    "shanghai": "Asia/Shanghai",
    "hong kong": "Asia/Hong_Kong",
    "taipei": "Asia/Taipei",
    "singapore": "Asia/Singapore",
    "kuala lumpur": "Asia/Kuala_Lumpur",
    "bangkok": "Asia/Bangkok",
    "jakarta": "Asia/Jakarta",
    "manila": "Asia/Manila",
    "hanoi": "Asia/Ho_Chi_Minh",
    "ho chi minh city": "Asia/Ho_Chi_Minh",
    "delhi": "Asia/Kolkata",
    "new delhi": "Asia/Kolkata",
    "noida": "Asia/Kolkata",
    "greater noida": "Asia/Kolkata",
    "gurgaon": "Asia/Kolkata",
    "mumbai": "Asia/Kolkata",
    "bangalore": "Asia/Kolkata",
    "bengaluru": "Asia/Kolkata",
    "kolkata": "Asia/Kolkata",
    "chennai": "Asia/Kolkata",
    "hyderabad": "Asia/Kolkata",
    "pune": "Asia/Kolkata",
    "ahmedabad": "Asia/Kolkata",
    "jaipur": "Asia/Kolkata",
    "lucknow": "Asia/Kolkata",
    "karachi": "Asia/Karachi",
    "islamabad": "Asia/Karachi",
    "lahore": "Asia/Karachi",
    "dhaka": "Asia/Dhaka",
    "kathmandu": "Asia/Kathmandu",
    "colombo": "Asia/Colombo",
    "dubai": "Asia/Dubai",
    "abu dhabi": "Asia/Dubai",
    "doha": "Asia/Qatar",
    "riyadh": "Asia/Riyadh",
    "tehran": "Asia/Tehran",
    "tel aviv": "Asia/Jerusalem",
    "jerusalem": "Asia/Jerusalem",
    # Africa
    "cairo": "Africa/Cairo",
    "johannesburg": "Africa/Johannesburg",
    "cape town": "Africa/Johannesburg",
    "lagos": "Africa/Lagos",
    "nairobi": "Africa/Nairobi",
    "casablanca": "Africa/Casablanca",
    "accra": "Africa/Accra",
    # Oceania
    "sydney": "Australia/Sydney",
    "melbourne": "Australia/Melbourne",
    "brisbane": "Australia/Brisbane",
    "perth": "Australia/Perth",
    "adelaide": "Australia/Adelaide",
    "auckland": "Pacific/Auckland",
    "wellington": "Pacific/Auckland",
}

# Sorted longest-first so "new york" matches before "york".
_CITY_TIMEZONE_ITEMS = sorted(
    _CITY_TIMEZONES.items(), key=lambda kv: -len(kv[0])
)

# Words/phrases that disqualify a query from the deterministic clock path —
# they're asking about historical / relative time, not "what time is it right now".
_TIME_QUERY_DISQUALIFIERS = (
    "history", "historical", "ago", "before", "yesterday", "tomorrow",
    "last week", "next week", "last month", "next month",
    "last year", "next year", "year ago", "years ago",
    "minutes ago", "hours ago",
)

def _try_answer_time_in_city(prompt: str) -> Optional[Tuple[str, str, str]]:
    """If `prompt` is asking for the current time in a known city, return
    (answer, matched_city, iana_tz). Otherwise return None and let the caller
    fall back to web search / LLM.

    This bypass exists because DuckDuckGo's `.text()` endpoint returns article
    snippets — not the actual current time — so questions like "current time
    in Toronto" used to get back whatever time happened to be quoted in some
    old article (e.g. "01:45 EDT"). Computing it from `zoneinfo` is exact."""
    p = prompt.lower().strip()
    if not any(kw in p for kw in ("time", "clock", "hour")):
        return None
    if any(flag in p for flag in _TIME_QUERY_DISQUALIFIERS):
        return None

    matched_city = None
    matched_tz = None
    for city, tz_name in _CITY_TIMEZONE_ITEMS:
        if re.search(r"\b" + re.escape(city) + r"\b", p):
            matched_city = city
            matched_tz = tz_name
            break

    if not matched_tz:
        return None

    try:
        from zoneinfo import ZoneInfo  # Python 3.9+
        tz = ZoneInfo(matched_tz)
    except Exception as e:
        logger.warning(f"zoneinfo lookup failed for {matched_tz!r}: {e}")
        return None

    now = datetime.now(tz)
    answer = (
        f"It is currently {now.strftime('%I:%M %p').lstrip('0')} "
        f"({now.tzname()}) in {matched_city.title()} — "
        f"{now.strftime('%A, %B %d, %Y')}."
    )
    return answer, matched_city, matched_tz

def _current_date_context() -> str:
    """A short system-style preamble pinning today's date and time so Ollama
    models (frozen at an old training cutoff) don't claim it's 2023 or refuse
    with "I can't access real-time data"."""
    now = datetime.now()
    tz = now.astimezone().tzname() or ""
    return (
        f"Today's date is {now.strftime('%A, %B %d, %Y')}. "
        f"The current local time is {now.strftime('%I:%M %p')} {tz}. "
        f"The current year is {now.year}. "
        "Use these for ANY question about the current date, day, year, or "
        "time. Do NOT say you cannot access real-time information — the "
        "above values ARE real-time and authoritative. Do NOT rely on your "
        "training-data cutoff for date or time facts."
    )

def _ollama_timeouts(read_override: Optional[int] = None) -> Tuple[int, int]:
    """Return (connect_timeout, read_timeout) for `requests.timeout=`.

    Passing a tuple to `requests` lets the TCP handshake fail fast (so an
    unreachable Ollama host doesn't block for the full generation timeout)
    while still allowing the model long enough to produce a real answer.
    """
    return (
        settings.OLLAMA_CONNECT_TIMEOUT,
        read_override if read_override is not None else settings.OLLAMA_TIMEOUT,
    )

def _ollama_unreachable_message(exc: Exception) -> str:
    return (
        f"Cannot reach Ollama at {settings.OLLAMA_API_URL}: {exc.__class__.__name__}. "
        "Check that the host is up, the security group allows inbound TCP on the "
        "Ollama port from this server's egress IP, and that Ollama is bound to "
        "0.0.0.0 (OLLAMA_HOST=0.0.0.0)."
    )

# In-memory cache for list_models results. Models change infrequently; caching
# avoids hitting api.openai.com / api.anthropic.com on every page load.
_MODELS_CACHE: Dict[str, Tuple[float, list]] = {}
_MODELS_CACHE_TTL_SECONDS = 300  # 5 minutes

# OpenAI's /v1/models endpoint returns ~100 entries — embeddings, TTS, Whisper,
# Sora, image, audio-realtime, moderation, transcription. We only want chat /
# reasoning models in the UI dropdown.
_OPENAI_NON_CHAT_KEYWORDS = (
    "embedding",
    "whisper",
    "tts",
    "dall-e",
    "sora",
    "moderation",
    "transcribe",
    "image",
    "audio",
    "realtime",
    "search",
    "codex",
    "babbage",
    "davinci",
)
_OPENAI_CHAT_PREFIXES = ("gpt-", "o1", "o3", "o4", "chatgpt-", "chat-")

def _is_openai_chat_model(model_id: str) -> bool:
    """Return True for OpenAI model IDs usable in a chat-completion dropdown."""
    m = (model_id or "").lower()
    if any(kw in m for kw in _OPENAI_NON_CHAT_KEYWORDS):
        return False
    return m.startswith(_OPENAI_CHAT_PREFIXES)

def _dedupe_dated_variants(models: list) -> list:
    """Drop dated snapshots (e.g. 'gpt-4o-2024-05-13') when their base alias
    (e.g. 'gpt-4o') is also in the list. Keeps the dropdown short and points
    users at the maintained aliases."""
    import re as _re

    base_set = set(models)
    # Matches a trailing -<digits> chunk (date YYYY-MM-DD or build like -1106)
    date_pattern = _re.compile(r"-\d{4,}(?:-\d+)*$")
    pruned = []
    for m in models:
        stripped = date_pattern.sub("", m)
        if stripped != m and stripped in base_set:
            continue  # has a non-dated alias — drop this variant
        pruned.append(m)
    return pruned

class LLMProvider:
    """Handle interactions with various LLM providers"""

    def __init__(self):
        """Initialize LLM provider"""
        self.openai_key = settings.OPENAI_API_KEY
        self.anthropic_key = settings.ANTHROPIC_API_KEY

    def search_web(self, query: str, max_results=5):
        results = []

        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=max_results):
                results.append({
                    "title": r.get("title"),
                    "body": r.get("body"),
                    "url": r.get("href")
                })

        return results

    def _raw_ollama_generate(
        self, full_prompt: str, model: str, temperature: float
    ) -> Tuple[str, Dict[str, int]]:
        """Single POST to /api/generate. Returns (response_text, tokens)."""
        response = requests.post(
            f"{settings.OLLAMA_API_URL}/api/generate",
            json={
                "model": model,
                "prompt": full_prompt,
                "stream": False,
                "keep_alive": settings.OLLAMA_KEEP_ALIVE,
                "options": {
                    "temperature": temperature,
                    "num_predict": 256,
                    "num_ctx": 2048,
                },
            },
            timeout=(30, 1800),
        )
        result = response.json()
        response_text = result.get("response", "")
        tokens = {
            "prompt_tokens": len(full_prompt.split()),
            "response_tokens": len(response_text.split()),
        }
        tokens["total_tokens"] = tokens["prompt_tokens"] + tokens["response_tokens"]
        return response_text, tokens

    def _raw_ollama_chat(
        self,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float,
        num_predict: int = 384,
        num_ctx: int = 4096,
    ) -> Tuple[str, Dict[str, int]]:
        """POST to /api/chat with role-tagged messages. Ollama applies the
        model's native chat template (e.g. [INST]…[/INST] for Mistral), which
        is far more reliable than transcript-style string prompts when there
        is multi-turn context: the model is trained to answer the LATEST user
        message under that template rather than continuing the previous topic
        (which was the multi-turn bug seen with /api/generate)."""
        response = requests.post(
            f"{settings.OLLAMA_API_URL}/api/chat",
            json={
                "model": model,
                "messages": messages,
                "stream": False,
                "keep_alive": settings.OLLAMA_KEEP_ALIVE,
                "options": {
                    "temperature": temperature,
                    "num_predict": num_predict,
                    "num_ctx": num_ctx,
                },
            },
            timeout=(30, 1800),
        )
        result = response.json()
        text = (result.get("message") or {}).get("content", "")
        # /api/chat doesn't echo token counts in the same shape — estimate.
        joined = " ".join((m.get("content") or "") for m in messages)
        tokens = {
            "prompt_tokens": len(joined.split()),
            "response_tokens": len(text.split()),
        }
        tokens["total_tokens"] = tokens["prompt_tokens"] + tokens["response_tokens"]
        return text, tokens

    from datetime import datetime

    def rank_results(results):

        keywords = [
            "today",
            str(datetime.now().year),
            "festival",
            "holiday",
            "india"
        ]

        scored = []

        for r in results:

            score = 0

            text = (
                r.get("title","")
                + " "
                + r.get("body","")
            ).lower()

            for k in keywords:
                if k.lower() in text:
                    score += 1

            scored.append(
                (score,r)
            )

        scored.sort(
            reverse=True,
            key=lambda x:x[0]
        )

        return [x[1] for x in scored]

    def _search_duckduckgo(self, query: str, max_results: int = 5) -> list:
        """Return search-result dicts with keys title/href/body.

        Uses trafilatura to fetch full page content from each result URL so
        the downstream LLM extractor gets real doc text, not just snippets.
        Falls back to the raw DDGS snippet when fetch/extraction fails."""
        try:
            with DDGS() as ddgs:
                search_results = list(ddgs.text(query, max_results=max(max_results, 5)))
        except Exception as e:
            logger.warning(f"DuckDuckGo search failed: {e}")
            return []

        results = []
        for r in search_results:
            url = r.get("href", "")
            snippet = r.get("body", "")
            try:
                downloaded = trafilatura.fetch_url(url)
                text = trafilatura.extract(downloaded) if downloaded else None
            except Exception:
                text = None
            results.append(
                {
                    "title": r.get("title", ""),
                    "href": url,
                    "body": (text[:10000] if text else snippet),
                }
            )

        return results

    def _search_searxng(self, query: str, max_results: int = 5) -> list:
        """Return a list of search-result dicts from a self-hosted SearXNG
        instance. Returns [] on any failure so callers can decide what to do
        with an empty result set."""
        searx_url = settings.SEARCH_SEARXNG_URL
        params = {
            "q": "what is ollama",
            "format": "json"
        }

        if not searx_url:
            return []
        try:
            resp = requests.get(
                searx_url,
                # params={"q": query, "format": "json", "categories": "general"},
                params,
                timeout=10,
            )
            if resp.status_code != 200:
                logger.warning(f"SearXNG search returned {resp.status_code}: {resp.text[:200]!r}")
                return []
            data = resp.json() or {}
            raw_results = data.get("results") or []
            results = []
            for item in raw_results[:max_results]:
                results.append({
                    "title": item.get("title") or "",
                    "body": item.get("content") or "",
                    "href": item.get("url") or "",
                })
            return results
        except Exception as e:
            logger.warning(f"SearXNG search failed: {e}")
            return []

    def _search_google_query(self, query: str, max_results: int = 5) -> list:
        try:
            results = list(search(query, num_results=max_results, sleep_interval=2))
            logger.debug(f"results from google search: {results}")
            return results
        except Exception as e:
            logger.warning(f"Google search error: {e}")
            return []

    # Hard cap for the Tavily call (search + per-URL fetch + retries). When
    # this trips we fall through to Ollama / Google / DDG instead of
    # blocking the whole pipeline on a single slow site (accuweather etc.).
    _TAVILY_OVERALL_TIMEOUT_SECONDS = 15

    def _search_tavily(
        self, query: str, max_results: int = 5
    ) -> Optional[list]:
        """Search the web via Tavily and return results in the unified shape
        `{'title', 'body', 'href'}`.

        Tavily's `search()` returns its own indexed snippets — already
        substantially richer than Google/DDG snippets, AND no per-URL fetch
        is required. `search_depth='basic'` is the right default: it stays
        with Tavily's prefetched index instead of crawling every result
        page live (which is what was hanging on slow sites like
        accuweather.com behind a urllib3 retry storm).

        The whole call is wrapped in a ThreadPoolExecutor timeout
        (`_TAVILY_OVERALL_TIMEOUT_SECONDS`) so even if the SDK ignores its
        internal timeout we abort within a fixed budget and fall through
        to the next search engine.

        Returns None if Tavily isn't configured, the SDK isn't installed,
        the call timed out, or the call failed — caller falls through to
        Ollama web_search / Google / DDG."""
        api_key = settings.TAVILY_API_KEY
        if not api_key:
            return None

        try:
            from tavily import TavilyClient
        except ImportError:
            logger.warning(
                "tavily-python is not installed but TAVILY_API_KEY is set. "
                "Run: pip install tavily-python"
            )
            return None

        import concurrent.futures

        def _do_search():
            client = TavilyClient(api_key=api_key)
            return client.search(
                query=query,
                max_results=max(1, min(max_results, 10)),
                # 'basic' uses Tavily's own indexed snippets — no per-URL
                # crawl, which is what was hanging the pipeline on slow
                # sites. Still richer than Google/DDG snippets in practice.
                search_depth="basic",
                # We do our own LLM summarization (citations, no
                # training-data leak), so don't pull Tavily's one-liner.
                include_answer=False,
                # Skip raw_content too — it triggers the per-URL fetch we're
                # trying to avoid. The `content` field is enough.
                include_raw_content=False,
            )

        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(_do_search)
                response = future.result(
                    timeout=self._TAVILY_OVERALL_TIMEOUT_SECONDS
                )
        except concurrent.futures.TimeoutError:
            logger.warning(
                f"Tavily search timed out after "
                f"{self._TAVILY_OVERALL_TIMEOUT_SECONDS}s; falling through "
                f"to next engine"
            )
            return None
        except Exception as e:
            logger.warning(f"Tavily search failed: {e}")
            return None

        try:
            items = response.get("results") or []
            results = []
            for item in items:
                body = item.get("content") or item.get("raw_content") or ""
                # Cap per-result body so the summarizer prompt fits inside
                # num_ctx=4096. Cut on a word boundary so we don't slice
                # mid-word.
                if len(body) > 2500:
                    body = body[:2500].rsplit(" ", 1)[0] + "…"
                results.append({
                    "title": item.get("title") or "",
                    "body": body,
                    "href": item.get("url") or "",
                })
            return results
        except Exception as e:
            logger.warning(f"Parsing Tavily response failed: {e}")
            return None

    def _search_ollama_web(
        self, query: str, max_results: int = 5
    ) -> Optional[list]:
        """Call Ollama's hosted web_search endpoint at
        https://ollama.com/api/web_search.

        This is the *hosted* Ollama service (separate from the EC2 chat
        endpoint — settings.OLLAMA_API_URL is unaffected). Requires
        settings.OLLAMA_API_KEY. Returns results in the unified shape
        `{'title', 'body', 'href'}` or None if not configured / the call
        failed, so the caller can fall through to Google / DuckDuckGo."""
        api_key = settings.OLLAMA_API_KEY
        if not api_key:
            return None

        url = settings.OLLAMA_WEB_SEARCH_URL or "https://ollama.com/api/web_search"
        try:
            resp = requests.post(
                url,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={"query": query},
                timeout=30,
            )
            if resp.status_code != 200:
                logger.warning(
                    f"Ollama web_search returned {resp.status_code}: "
                    f"{resp.text[:200]!r}"
                )
                return None
            data = resp.json() or {}
            # Ollama's payload shape: {"results": [{"title", "url", "content"}, …]}.
            # We accept a few field-name variants defensively in case the API
            # shape changes (snippet vs content, link vs url).
            raw_items = data.get("results") or data.get("data") or []
            items = []
            for item in raw_items[:max_results]:
                body = (
                    item.get("content")
                    or item.get("snippet")
                    or item.get("body")
                    or ""
                )
                # Page content from web_search can be large; cap it so the
                # summarizer prompt stays under the model context window.
                if len(body) > 2000:
                    body = body[:2000].rsplit(" ", 1)[0] + "…"
                items.append({
                    "title": item.get("title") or "",
                    "body": body,
                    "href": item.get("url") or item.get("link") or "",
                })
            return items
        except Exception as e:
            logger.warning(f"Ollama web_search call failed: {e}")
            return None

    def _search_google(self, query: str, max_results: int = 5) -> Optional[list]:
        """Call Google Custom Search JSON API. Returns a list of result dicts
        in the same shape as `_search_duckduckgo` (`title`/`body`/`href`), or
        None when the API is not configured / fails — so the caller can fall
        back to DuckDuckGo without confusing 'no results' with 'no key'."""
        api_key = settings.GOOGLE_API_KEY
        cse_id = settings.GOOGLE_CSE_ID
        if not api_key or not cse_id:
            return None

        try:
            resp = requests.get(
                "https://www.googleapis.com/customsearch/v1",
                params={
                    "key": api_key,
                    "cx": cse_id,
                    "q": query,
                    # Google CSE caps `num` at 10.
                    "num": max(1, min(max_results, 10)),
                    # Recency hint — biases towards pages updated in the last
                    # year. Helps a lot on "today's …" queries.
                    "sort": "date",
                },
                timeout=10,
            )
            if resp.status_code != 200:
                logger.warning(
                    f"Google CSE returned {resp.status_code}: "
                    f"{resp.text[:200]!r}"
                )
                return None
            items = resp.json().get("items") or []
            return [
                {
                    "title": item.get("title") or "",
                    "body": item.get("snippet") or "",
                    "href": item.get("link") or "",
                }
                for item in items
            ]
        except Exception as e:
            logger.warning(f"Google CSE call failed: {e}")
            return None

    def _search_web(self, query: str, max_results: int = 5) -> Tuple[list, str]:
        """Unified web search. Preference order:
          1. Tavily (purpose-built for AI agents — full page content)
          2. Ollama hosted web_search (also returns full content)
          3. Google Custom Search (good snippets, no full content)
          4. DuckDuckGo (free keyless fallback)
        Returns `(results, engine_name)` so the caller can log / emit which
        engine actually answered."""
        # Preferred: Tavily — purpose-built for AI agents, returns full
        # page content (not just snippets), no separate extract step needed.
        if settings.TAVILY_API_KEY:
            tavily_results = self._search_tavily(query, max_results)
            if tavily_results:
                logger.info(
                    f"Search via Tavily returned {len(tavily_results)} result(s)"
                )
                return tavily_results, "tavily"
            logger.info(
                "Tavily returned no usable results; trying Ollama / Google / DDG"
            )

        # Next: Ollama hosted web_search — best snippets, full content.
        if settings.OLLAMA_API_KEY:
            ollama_results = self._search_ollama_web(query, max_results)
            if ollama_results:
                logger.info(
                    f"Search via Ollama web_search returned "
                    f"{len(ollama_results)} result(s)"
                )
                return ollama_results, "ollama_web"
            logger.info(
                "Ollama web_search returned no usable results; "
                "trying Google CSE / DuckDuckGo"
            )

        # Next: Google Custom Search if API + CSE keys are configured.
        if settings.GOOGLE_API_KEY and settings.GOOGLE_CSE_ID:
            google_results = self._search_google(query, max_results)
            if google_results:
                logger.info(
                    f"Search via Google CSE returned {len(google_results)} result(s)"
                )
                return google_results, "google"
            logger.info(
                "Google CSE returned no usable results; falling back to "
                "DuckDuckGo"
            )

        # Final fallback: DuckDuckGo — no key required.
        ddg_results = self._search_duckduckgo(query, max_results)
        return ddg_results, "duckduckgo"
        # searxng_results = self._search_searxng(query, max_results)
        # return searxng_results, "searxng"
        # search_results = self._search_google_query(query, max_results)
        # return search_results, "google search api"

    @staticmethod
    def _format_results_block(results: list) -> str:
        """Numbered, compact rendering of DDG results for prompt injection."""
        if not results:
            return "(no web results returned)"
        lines = []
        for i, r in enumerate(results, start=1):
            lines.append(
                f"[{i}] \n"
                f"Title: {r.get('title') or ''}\n"
                f"Content: {r.get('content') or ''}\n"
                f"Source: {r.get('url') or ''}"
            )
        return "\n\n".join(lines)

    # ── URL → main-text extraction (trafilatura) ───────────────────────────
    # We download the page ourselves so we can pin a tight per-request
    # timeout (trafilatura.fetch_url's own timeout story is patchy), then
    # hand the HTML to trafilatura which does the heavy lifting of boilerplate
    # removal / main-content scoring. Far better than html.parser for
    # news / blog / docs pages where 70% of the markup is chrome.

    @classmethod
    def _fetch_url_content(
        cls,
        url: str,
        timeout: float = 6.0,
        max_bytes: int = 800_000,
        max_chars: int = 8000,
    ) -> Optional[str]:
        """Fetch a URL and return main-text extracted by trafilatura. Returns
        None on any failure (timeout, non-HTML content type, no extractable
        text) so callers can keep the original snippet."""
        result = cls._fetch_url_content_with_html(url, timeout=timeout, max_bytes=max_bytes, max_chars=max_chars)
        return result[0] if result else None

    @classmethod
    def _fetch_url_content_with_html(
        cls,
        url: str,
        timeout: float = 6.0,
        max_bytes: int = 800_000,
        max_chars: int = 8000,
    ) -> Optional[Tuple[Optional[str], str]]:
        """Like _fetch_url_content but also returns the raw HTML so callers
        can extract links for pagination/menu discovery. Returns (text, html)
        or None on failure."""
        try:
            resp = requests.get(
                url,
                timeout=timeout,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (compatible; Adaptora/1.0; "
                        "+https://github.com/)"
                    ),
                    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.9",
                },
                stream=True,
            )
            if resp.status_code != 200:
                return None
            ctype = (resp.headers.get("Content-Type") or "").lower()
            if "html" not in ctype and "xml" not in ctype:
                return None
            html_text = resp.raw.read(max_bytes, decode_content=True)
            if isinstance(html_text, bytes):
                try:
                    html_text = html_text.decode(
                        resp.apparent_encoding or "utf-8", errors="replace"
                    )
                except Exception:
                    html_text = html_text.decode("utf-8", errors="replace")
        except Exception as e:
            logger.debug(f"URL fetch failed for {url}: {e.__class__.__name__}: {e}")
            return None

        try:
            text = trafilatura.extract(
                html_text,
                include_comments=False,
                include_tables=False,
                no_fallback=False,
            )
        except Exception as e:
            logger.debug(f"trafilatura.extract failed for {url}: {e}")
            text = None

        if text:
            text = text.strip()
            if len(text) > max_chars:
                text = text[:max_chars].rsplit(" ", 1)[0] + "…"
        return (text, html_text)

    # Heuristic: a `body` longer than this many characters is treated as
    # already-fetched full content (Tavily / Ollama web_search return that
    # shape). Snippet-only engines (DuckDuckGo, Google CSE) return ~50-300
    # chars — those get the trafilatura fetch.
    _ENRICH_BODY_CHAR_THRESHOLD = 500

    def _enrich_results_with_page_content(
        self,
        results: list,
        max_to_fetch: int = 5,
        per_url_timeout: float = 6.0,
        overall_timeout: float = 15.0,
    ) -> list:
        """For the top N search results, fetch the actual page (trafilatura)
        and replace the thin search snippet with extracted main-text. Falls
        back to the original snippet for any URL that fails or returns too
        little text. Runs concurrently so the wall-clock cost is roughly one
        slow page rather than the sum of all of them. The whole batch is
        bounded by `overall_timeout` so a single hanging site can't stall.

        Results whose `body` is already substantial (>= 500 chars — i.e.
        Tavily / Ollama web_search returned full page content) are SKIPPED.
        Snippet-only engines (DuckDuckGo, Google CSE) still trigger the
        scrape since their snippets are too thin for good summarization."""
        import concurrent.futures

        if not results:
            return results

        targets = []
        skipped_existing = 0
        for idx, r in enumerate(results[:max_to_fetch]):
            body_len = len(r.get("body") or "")
            if body_len >= self._ENRICH_BODY_CHAR_THRESHOLD:
                # Already-fetched full content (Tavily / Ollama web_search).
                # Don't double-fetch — we'd just waste time and bandwidth.
                skipped_existing += 1
                continue
            url = (r.get("href") or "").strip()
            if url:
                targets.append((idx, url))
        if not targets:
            logger.info(
                f"Enrichment skipped: {skipped_existing} result(s) already "
                f"have full content; no snippet-only results to fetch."
            )
            return results

        enriched = 0
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(targets)) as pool:
            future_to_idx = {
                pool.submit(self._fetch_url_content_with_html, url, per_url_timeout): idx
                for idx, url in targets
            }
            try:
                for future in concurrent.futures.as_completed(
                    future_to_idx, timeout=overall_timeout
                ):
                    idx = future_to_idx[future]
                    try:
                        result = future.result()
                    except Exception:
                        result = None
                    if result:
                        content, raw_html = result
                        if content and len(content) > 200:
                            results[idx]["body"] = content
                            enriched += 1
                        # Always store raw HTML for link discovery even if
                        # trafilatura extracted nothing (JS-rendered pages).
                        if raw_html:
                            results[idx]["_raw_html"] = raw_html
            except concurrent.futures.TimeoutError:
                logger.info(
                    f"URL-fetch batch hit overall timeout "
                    f"({overall_timeout}s); using snippets for the rest"
                )

        logger.info(
            f"Enriched {enriched}/{len(targets)} search results with "
            f"extracted page content"
        )
        return results

    @staticmethod
    def _extract_lead_summary(text: str, max_chars: int = 280) -> str:
        """Extractive lead-paragraph summary for source cards. Takes the
        first ~280 chars on a sentence boundary so the per-source card the
        UI shows is a real summary (the lead of an article is usually the
        TL;DR), not a mid-page snippet. Cheap, deterministic, no LLM call."""
        if not text:
            return ""
        cleaned = re.sub(r"\s+", " ", text).strip()
        if not cleaned:
            return ""
        if len(cleaned) <= max_chars:
            return cleaned
        # Find a sentence-ending punctuation within the budget.
        sentences = re.split(r"(?<=[.!?])\s+", cleaned)
        acc = ""
        for s in sentences:
            candidate = (acc + " " + s).strip() if acc else s
            if len(candidate) > max_chars:
                if not acc:
                    # First sentence already overflows — hard cut on word
                    # boundary as a last resort.
                    return s[:max_chars].rsplit(" ", 1)[0] + "…"
                break
            acc = candidate
        return acc or cleaned[:max_chars].rsplit(" ", 1)[0] + "…"

    @staticmethod
    def _raw_results_fallback(prompt: str, results: list) -> str:
        """Plain-text fallback shown to the user when the model REFUSES to
        summarize even after being given web context. Better to surface real
        links than ship the canned 'I can't access the internet' apology."""
        if not results:
            return (
                f"I couldn't find usable web results for: {prompt!r}. "
                "Try rephrasing the question."
            )
        bullets = []
        for r in results[:5]:
            title = (r.get("title") or "").strip()
            body = (r.get("body") or "").strip()
            url = (r.get("href") or "").strip()
            bullets.append(f"- {title}\n  {body}\n  {url}")
        return (
            f"Here's what a fresh web search returned for: {prompt!r}\n\n"
            + "\n\n".join(bullets)
        )

    _SUMMARIZER_SYSTEM = (
        "ROLE: You are a search-result summarizer, not a general assistant. "
        "A live web search has already been performed FOR YOU. Your only job "
        "is to extract the answer to the user's CURRENT question from the "
        "SEARCH RESULTS the user provides and present it.\n\n"
        "STRICT RULES:\n"
        "1. Use ONLY the search results the user just sent — do not say you "
        "can't access real-time data; the search is already done.\n"
        "2. If results contain the answer, give it directly and cite the "
        "source number (e.g. '[2]').\n"
        "3. If results don't contain a clear answer, summarize the closest "
        "information found and point the user at the most relevant URL.\n"
        "4. NEVER apologize for not having current information — just "
        "summarize what is in the results.\n"
        "5. Earlier turns in this chat are context only; answer ONLY the "
        "CURRENT question, even if previous turns were about a different "
        "topic."
    )

    @staticmethod
    def _safe_emit(
        status_callback: Optional[Callable[[str, Dict[str, Any]], None]],
        step: str,
        **data: Any,
    ) -> None:
        """Best-effort SSE-status emission. Never raise — a broken status
        consumer must not break the LLM pipeline."""
        if not status_callback:
            return
        try:
            status_callback(step, data)
        except Exception as e:
            logger.warning(f"status_callback failed for step={step!r}: {e}")

    def _ollama_with_web_context(
        self,
        prompt: str,
        model: str,
        temperature: float,
        date_context: Optional[str] = None,  # noqa: ARG002 — kept for call-site compat
        history: Optional[List[Dict[str, str]]] = None,  # noqa: ARG002 — intentionally ignored
        status_callback: Optional[Callable[[str, Dict[str, Any]], None]] = None,
    ) -> Tuple[str, Dict[str, int]]:
        """Search the web for `prompt`, then ask Ollama to summarize the
        results. Reframing the model as a *search-result summarizer* (not as
        an AI that answers from its own knowledge) sidesteps the trained
        "I don't have real-time access" refusal.

        `date_context` is accepted for call-site compatibility but no longer
        used — we now stamp today's date inline so it appears immediately
        before the search results in the user message (where the chat
        template gives it the most weight).

        `history` is INTENTIONALLY IGNORED here. With small models
        (Mistral 7B / llama2 7B) the prior conversation primes the model
        with off-topic context that drowns out the fresh search results,
        producing the "May 2023 answer in a 2026 chat" bug. The web search
        is the ground truth — no history needed.

        `status_callback`, when provided, receives fine-grained pipeline
        events ("searching_internet", "search_complete", "summarizing_results")
        which the streaming endpoint forwards to the UI as SSE."""
        self._safe_emit(status_callback, "searching_internet", query=prompt)
        results, search_engine = self._search_web(prompt, max_results=6)
        self._safe_emit(
            status_callback,
            "search_complete",
            result_count=len(results),
            query=prompt,
            engine=search_engine,
        )
        logger.info(
            f"Web search ({search_engine}) for {prompt!r} returned "
            f"{len(results)} result(s)"
            + (
                f"; top title={results[0].get('title','')[:80]!r}"
                if results
                else ""
            )
        )

        logger.debug(f"Web search results for {prompt!r}: {results}")

        # No results at all → don't call the LLM; it will only hallucinate.
        if not results:
            logger.info("No web results; returning empty-result message")
            fallback = self._raw_results_fallback(prompt, results)
            tokens = {
                "prompt_tokens": len(prompt.split()),
                "response_tokens": len(fallback.split()),
            }
            tokens["total_tokens"] = (
                tokens["prompt_tokens"] + tokens["response_tokens"]
            )
            return fallback, tokens

        # Fetch the actual page bodies for the top results so the summarizer
        # has real article text — not just thin engine snippets. Stdlib-only
        # extraction (urllib + html.parser), no paid SDK. Falls back to the
        # snippet on any per-URL failure, and the whole batch is bounded by
        # an overall timeout so a single slow site can't stall the pipeline.
        self._safe_emit(
            status_callback,
            "fetching_pages",
            count=min(len(results), 5),
        )
        results = self._enrich_results_with_page_content(
            results, max_to_fetch=5
        )
        self._safe_emit(status_callback, "pages_fetched", count=len(results))

        results_block = self._format_results_block(results)
        summarizer_temp = min(temperature, 0.2)

        # Build the structured per-source data the UI will render as cards.
        # The summary is EXTRACTIVE (first 2-3 sentences of the trafilatura-
        # extracted body) — cheap, deterministic, no extra LLM calls, always
        # reliable even when the model misbehaves on the main answer. Pushed
        # to the frontend via SSE so it can render cards under the assistant
        # bubble.
        web_sources_payload = []
        for r in results[:5]:
            title = (r.get("title") or "").strip()
            url = (r.get("url") or "").strip()
            body = (r.get("content") or "").strip()
            if not title or not url:
                continue
            web_sources_payload.append({
                "title": title,
                "url": url,
                "summary": self._extract_lead_summary(body, max_chars=280),
            })
        if web_sources_payload:
            self._safe_emit(
                status_callback,
                "web_sources",
                sources=web_sources_payload,
            )
            logger.info(
                f"Emitted web_sources event with {len(web_sources_payload)} "
                f"source card(s) for the UI"
            )

        # Build a numbered "title + URL" reference table for the prompt so
        # the model can copy the right title + URL into each inline
        # `[title](url)` citation. The `_format_results_block` already
        # includes URLs, but a tight numeric lookup right next to the
        # citation rule makes the model's link output much more reliable.
        citation_lookup_lines = []
        for i, r in enumerate(results[:5], start=1):
            t = (r.get("title") or "").strip().replace("\n", " ")
            u = (r.get("url") or "").strip()
            if not u:
                continue
            # Truncate long titles so the prompt's lookup table stays tidy.
            if len(t) > 80:
                t = t[:77].rsplit(" ", 1)[0] + "…"
            citation_lookup_lines.append(f"[{i}] title={t!r} url={u}")
        citation_lookup_block = (
            "\n".join(citation_lookup_lines) or "(no citable results)"
        )

        # The LLM synthesizes Quick answer + Overview + Key details. The
        # `## Sources` section is built deterministically by us in the
        # post-processor so the model can't hallucinate URLs there.
        #
        # For inline citations the model MUST copy a URL verbatim from the
        # CITATION TABLE — never invent one. The previous prompt used
        # "Title" / "URL" as placeholder tokens in the format spec, and the
        # model was treating them as literal strings or inventing
        # example.com when uncertain. The new spec embeds a concrete
        # example only, no placeholder tokens.
        # current_user_msg = (
        #     "You are a retrieval-only summarizer for a user-facing answer. "
        #     "Use ONLY the SEARCH RESULTS below. Do NOT use prior knowledge. "
        #     "Do NOT invent facts, numbers, dates or sources. If a piece of "
        #     "information is not in the results, write \"NOT FOUND\" for "
        #     "that part (do not guess).\n\n"
        #     f"SEARCH RESULTS:\n{results_block}\n\n"
        #     "CITATION TABLE — the ONLY URLs you are allowed to use:\n"
        #     f"{citation_lookup_block}\n\n"
        #     f"QUESTION: {prompt}\n\n"
        #     "Write a helpful answer the user can actually read. Use this "
        #     "EXACT markdown structure — every section is required:\n\n"
        #     "## Quick answer\n"
        #     "<3-5 sentences directly answering the question in plain "
        #     "language. Drawn ONLY from the search results. After every "
        #     "factual claim, add a parenthesised markdown-link citation. "
        #     "The citation's display text is the result's title, the "
        #     "link target is the result's URL — both copied VERBATIM from "
        #     "the CITATION TABLE above. Concrete example (DO NOT copy "
        #     "these literal values, use whatever the table actually says):"
        #     "\n    The iPhone 17 launched on September 12, 2025 "
        #     "([Apple Newsroom](https://www.apple.com/newsroom)).\n"
        #     "If the table is empty or no listed URL applies, OMIT the "
        #     "parenthesised citation rather than making one up.>\n\n"
        #     "## Overview\n"
        #     "<3-5 more sentences giving context — what the topic is, why "
        #     "it matters, any relevant background. Use **bold** for the "
        #     "key terms. Cite supporting facts in the same parenthesised "
        #     "form as Quick answer.>\n\n"
        #     "## Key details\n"
        #     "- <Up to 10 bullets. Each bullet is ONE FULL SENTENCE ending "
        #     "with the same citation form. Bullets should expand on "
        #     "different aspects (specs, dates, numbers, quotes, "
        #     "comparisons) — don't repeat the Quick answer verbatim.>\n"
        #     "- <…>\n\n"
        #     "DO NOT write a `## Sources` section — we add a verified one "
        #     "automatically. Focus on the three sections above.\n\n"
        #     "STRICT URL RULES:\n"
        #     "- The ONLY URLs you may write are the ones in the CITATION "
        #     "TABLE above. Never use example.com, sample.com, or any "
        #     "other placeholder domain.\n"
        #     "- If you cannot find a URL in the CITATION TABLE for a "
        #     "claim, OMIT the parenthesised citation. Do not invent one.\n\n"
        #     "Other rules:\n"
        #     "- Quote any specific date or number EXACTLY as it appears in "
        #     "the search results.\n"
        #     "- If a result says something different from another result, "
        #     "note the disagreement instead of picking one.\n"
        #     "- Don't apologise or hedge about real-time data — you have "
        #     "today's search results in front of you."
        # )

        current_user_msg = f"""
        You are a retrieval-only summarizer.

        Use ONLY the SEARCH RESULTS below.
        Do not use outside knowledge.
        Do not invent facts.
        If a fact is not present, write NOT FOUND.

        SEARCH RESULTS:
        {results_block}

        QUESTION:
        {prompt}

        Return exactly this markdown:

        ## Quick answer
        ...

        ## Overview
        ...

        ## Key details
        - ...
        """

        self._safe_emit(
            status_callback, "summarizing_results", result_count=len(results)
        )

        # Intentionally DROP prior conversation history for the web
        # summarizer. With Mistral 7B, older turns (e.g. a prior chat about
        # Akbar) prime the model to keep producing off-topic / training-data
        # content even when fresh search results are in the prompt. The
        # search results plus the date stamp are sufficient context here.
        messages = [
            {"role": "system", "content": self._SUMMARIZER_SYSTEM},
            {"role": "user", "content": current_user_msg},
        ]
        # Give the summarizer headroom — `num_predict=384` was clipping the
        # response mid-bullet on multi-result queries. 768 lets the model
        # produce all four sections (Quick answer + Overview + Key details +
        # Sources) without truncation, and 6144 ctx fits the larger prompt
        # we build from up to 5 enriched page-bodies.
        text, tokens = self._raw_ollama_chat(
            messages, model, summarizer_temp, num_predict=768, num_ctx=6144
        )

        logger.info(
            f"Summarizer response (first 200 chars): {text[:200]!r}"
        )

        # Refusal path: model bailed out despite the search context.
        if _response_indicates_no_internet(text) or not text.strip():
            logger.info("Summarizer refused; returning raw web results")
            fallback = self._raw_results_fallback(prompt, results)
            return fallback, {
                "prompt_tokens": tokens.get("prompt_tokens", 0),
                "response_tokens": len(fallback.split()),
                "total_tokens": tokens.get("prompt_tokens", 0)
                + len(fallback.split()),
            }

        # Training-data leak path: model quoted an old year that doesn't
        # appear in the search-result snippets. That's the "May 2023 in a
        # 2026 chat" bug — the model ignored the results and answered from
        # its cutoff. Better to show raw results than ship the hallucination.
        if _response_has_stale_year(text, results_block):
            logger.info(
                "Stale-year leak detected; returning raw web results. "
                f"Hallucinated response snippet: {text[:200]!r}"
            )
            fallback = self._raw_results_fallback(prompt, results)
            return fallback, {
                "prompt_tokens": tokens.get("prompt_tokens", 0),
                "response_tokens": len(fallback.split()),
                "total_tokens": tokens.get("prompt_tokens", 0)
                + len(fallback.split()),
            }

        # GUARANTEE URLs in the summary regardless of how the model behaved.
        # The model is unreliable about citations: sometimes it skips the
        # Sources section, sometimes writes bare "[1]" instead of "[Title]
        # (URL)", sometimes invents URLs (example.com / placeholder.com /
        # plausible-looking domains that aren't in our results). Two-stage
        # cleanup:
        #   1. Strip any markdown link in the body whose URL isn't in the
        #      verified set. Visible text is kept so prose isn't damaged.
        #   2. Strip and replace any `## Sources` block with one built
        #      directly from `web_sources_payload` (same data the SSE
        #      source cards use, so the two views stay consistent).
        if web_sources_payload:
            text = self._strip_hallucinated_links(text, web_sources_payload)
            text = self._inject_verified_sources_section(
                text, web_sources_payload
            )

        return text, tokens

    @staticmethod
    def _strip_hallucinated_links(
        text: str, web_sources_payload: List[Dict[str, str]]
    ) -> str:
        """Remove markdown links from `text` whose URL points to a HOST
        that's not in the verified web-sources set. Keeps the visible
        link text so prose isn't damaged.

        Hostname-based matching (not strict-prefix) so the model writing
        `https://apple.com/newsroom` is accepted when the verified result
        was `https://www.apple.com/newsroom/iphone-17`. Both point to the
        same source — stripping the link there was overzealous and looked
        to the user like "no URLs are being added".

        Also strips obvious placeholder bare-URLs (example.com,
        sample.com, placeholder.com, your-source.com, etc.)."""
        from urllib.parse import urlparse

        def _host_of(u: str) -> str:
            try:
                h = urlparse(u).hostname or ""
            except Exception:
                return ""
            return h.lower().lstrip(".").removeprefix("www.")

        allowed_hosts = set()
        for s in web_sources_payload:
            h = _host_of((s.get("url") or "").strip())
            if h:
                allowed_hosts.add(h)

        if not allowed_hosts:
            return text

        def _url_is_allowed(url: str) -> bool:
            return _host_of(url) in allowed_hosts

        # 1) Strip markdown links with disallowed URLs. The substitution
        #    keeps the link's visible text so the sentence still reads.
        def _link_repl(match):
            link_text = match.group(1)
            url = match.group(2)
            return match.group(0) if _url_is_allowed(url) else link_text

        text = re.sub(
            r"\[([^\]\n]+)\]\((https?://[^\s)]+)\)",
            _link_repl,
            text,
        )

        # 2) Strip bare placeholder URLs. These are common hallucinations
        #    when the model isn't sure what to put.
        placeholder_host_rx = re.compile(
            r"\bhttps?://"
            r"(?:www\.)?"
            r"(?:example|sample|placeholder|your-?source|source|url)"
            r"\."
            r"(?:com|org|net|io)"
            r"(?:/[^\s)]*)?",
            re.IGNORECASE,
        )
        text = placeholder_host_rx.sub("", text)

        return text

    @staticmethod
    def _inject_verified_sources_section(
        text: str, web_sources_payload: List[Dict[str, str]]
    ) -> str:
        """Strip any model-emitted `## Sources` section and append our own
        verified one. The model's Sources block is unreliable; this one is
        built directly from the actual scraped results so URLs are correct
        and always present.

        Visually prominent: a horizontal rule above the section, a 🔗
        emoji in the heading, numbered list, and bold titles. The previous
        plain `## Sources` was easy to miss after a long answer."""
        if not web_sources_payload:
            return text

        # Match a `## Sources` (or `### Sources`) heading and everything
        # under it up to the next `##` heading or end of document. Tolerant
        # of "Sources", "sources", "SOURCES", and the new "🔗 Sources" form
        # we ourselves emit — so re-running the injector on already-injected
        # text is idempotent.
        text_without_sources = re.sub(
            r"\n*#{2,3}\s*(?:🔗\s*)?Sources\s*\n.*?(?=\n#{2,3}\s|\Z)",
            "",
            text,
            flags=re.DOTALL | re.IGNORECASE,
        ).rstrip()

        # Build a new Sources block from the verified scraped data. Each
        # line is a real markdown link; the optional one-sentence note
        # comes from the extractive summary the SSE cards also use.
        # Using `-` bullets (not numbered) so the existing frontend
        # SOURCE_LINE_RX picks them up and renders each as a SourceCard.
        #
        # IMPORTANT: there MUST be a blank line between the `## 🔗 Sources`
        # heading and the first bullet. The frontend splits markdown into
        # blocks on `\n{2,}` — without the blank line, heading + bullets
        # land in a single block and the renderer treats the bullets as a
        # paragraph (with <br>s) instead of a bullet list. That was the
        # bug that made source titles render as plain text instead of as
        # clickable cards.
        lines = ["---", "", "## 🔗 Sources", ""]
        for s in web_sources_payload:
            title = (s.get("title") or "").strip() or s.get("url") or ""
            url = (s.get("url") or "").strip()
            summary = (s.get("summary") or "").strip()
            if not url:
                continue
            note = ""
            if summary:
                short = summary[:140].rsplit(" ", 1)[0]
                if len(summary) > 140:
                    short += "…"
                note = f" — {short}"
            lines.append(f"- [{title}]({url}){note}")

        # 4 = ['---', '', '## 🔗 Sources', '']; if no actual entries got
        # added past that, the model gave us nothing to cite — leave the
        # original text alone.
        if len(lines) == 4:
            return text

        return text_without_sources + "\n\n" + "\n".join(lines)

    def _classify_needs_internet(self, prompt: str, model: str) -> bool:
        """Ask Ollama whether answering the prompt requires fresh internet
        information. Returns True / False.

        Design choices for higher recall (the bug we're fixing was "says NO
        when it should say YES"):

        - The prompt explicitly tells the model "when uncertain, answer YES".
          False negatives serve stale training-data answers; false positives
          only cost one extra search round-trip.
        - Diverse few-shots covering ALL the cases the user has hit so far —
          news, weather, scores, prices, product launches, people in office,
          today's date (handled separately, NO), pure coding (NO), and the
          subtle "tell me about <real-world entity>" cases that DO need
          fresh data when the entity is current.
        - On API failure we default to True instead of False, again favoring
          recall over latency.
        """
        classifier_prompt = (
            f"{_current_date_context()}\n\n"
            "TASK: Decide whether answering the user's question requires "
            "fresh information from the internet.\n\n"
            "Answer YES if the question touches any of these:\n"
            "- News, headlines, current events, politics, sports scores\n"
            "- Weather, traffic, flight / train status\n"
            "- Stock / crypto / fuel / commodity prices\n"
            "- Latest / current / recent / today / yesterday / this "
            "week — anything time-sensitive\n"
            "- Real-world people, companies, products, places where the "
            "answer changes over time (who is the current CEO, latest "
            "iPhone, etc.)\n"
            "- Product launches, release dates, schedules, deadlines\n"
            "- Anything where the answer depends on what is true RIGHT NOW\n\n"
            "Answer NO only when the question is purely about:\n"
            "- Math, logic puzzles, coding tasks, writing tasks\n"
            "- Translation between languages\n"
            "- Definitions or explanations of stable concepts (physics, "
            "history, well-known biographies of historical figures)\n"
            "- Asking only the current local time or date (we compute "
            "those without a web search)\n\n"
            "WHEN UNCERTAIN, ANSWER YES. False negatives (no search) "
            "produce stale answers from outdated training data, which is "
            "worse than a wasted search.\n\n"
            "Reply with EXACTLY one word: YES or NO. No other text.\n\n"
            "Examples:\n"
            "Q: What's today's weather in Mumbai?\nA: YES\n"
            "Q: Latest iPhone price\nA: YES\n"
            "Q: Who is the current US president?\nA: YES\n"
            "Q: Tesla stock price\nA: YES\n"
            "Q: Latest cricket match score\nA: YES\n"
            "Q: news from manipur this week\nA: YES\n"
            "Q: When is Diwali this year\nA: YES\n"
            "Q: aaj ne US ke latest news\nA: YES\n"
            "Q: best laptops 2026\nA: YES\n"
            "Q: How is OpenAI doing\nA: YES\n"
            "Q: Tell me about Akbar (Mughal emperor)\nA: NO\n"
            "Q: What is 2+2?\nA: NO\n"
            "Q: Write a Python function to reverse a string\nA: NO\n"
            "Q: Explain quantum entanglement\nA: NO\n"
            "Q: Translate 'hello' to French\nA: NO\n"
            "Q: What time is it?\nA: NO\n"
            "Q: What is today's date?\nA: NO\n\n"
            f"Q: {prompt}\nA:"
        )

        try:
            response = requests.post(
                f"{settings.OLLAMA_API_URL}/api/generate",
                json={
                    "model": model,
                    "prompt": classifier_prompt,
                    "stream": False,
                    "options": {
                        "temperature": 0,
                        "num_predict": 5,
                    },
                },
                timeout=(30, 120),
            )
            if response.status_code != 200:
                logger.warning(
                    f"Internet classifier: status {response.status_code}; "
                    f"defaulting to True (assume search needed)"
                )
                return True
            raw = (response.json().get("response", "") or "").strip().upper()
            first = raw.split()[0].rstrip(".,!?:;") if raw else ""
            decision = first in ("YES", "Y")
            logger.info(
                f"Internet classifier: raw={raw!r} → first={first!r} → "
                f"decision={decision}"
            )
            return decision
        except Exception as e:
            logger.warning(
                f"Internet classifier call failed: {e}; defaulting to "
                f"True (assume search needed — favoring recall over speed)"
            )
            # Bias the failure mode toward MORE searches, not fewer. A
            # spurious search is annoying; a missed search ships stale data.
            return True

    # def _classify_needs_internet(self, prompt: str, model: str) -> bool:
    #     """Ask Ollama itself: does answering this prompt require fresh internet
    #     data? Returns True / False. Few-shot examples make this reliable for
    #     the cases users actually hit (weather, news, scores, prices) without
    #     false-triggering on coding / writing / general-knowledge prompts."""

    #     # classifier_prompt = (
    #     #     f"{_current_date_context()}\n\n"
    #     #     "TASK: Decide whether answering the user's question requires fresh "
    #     #     "information from the internet. Time-sensitive things — current "
    #     #     "weather, news, sports scores, stock or crypto prices, recent "
    #     #     "events, today's headlines — DO need the internet. General "
    #     #     "knowledge, math, writing, coding, definitions and explanations "
    #     #     "do NOT.\n\n"
    #     #     "Reply with EXACTLY one word: YES or NO. No other text.\n\n"
    #     #     "Examples:\n"
    #     #     "Q: What's today's weather in Mumbai?\nA: YES\n"
    #     #     "Q: Who won the cricket match last night?\nA: YES\n"
    #     #     "Q: Current Bitcoin price\nA: YES\n"
    #     #     "Q: Latest news about AI\nA: YES\n"
    #     #     "Q: What is the capital of France?\nA: NO\n"
    #     #     "Q: Write a Python function to reverse a string.\nA: NO\n"
    #     #     "Q: Explain how binary search works\nA: NO\n"
    #     #     "Q: What time is it?\nA: NO\n"
    #     #     "Q: What is today's date?\nA: NO\n\n"
    #     #     f"Q: {prompt}\nA:"
    #     # )

    #     print (f"Classifying internet need for prompt: {prompt}")

    #     classifier_prompt = f"""
    #     f"{_current_date_context()}\n\n"
    #     Determine whether this query needs current internet information.

    #     Return ONLY YES or NO.

    #     Query:
    #     {prompt}
    #     """

    #     try:
    #         response = requests.post(
    #             f"{settings.OLLAMA_API_URL}/api/generate",
    #             json={
    #                 "model": model,
    #                 "prompt": classifier_prompt,
    #                 "stream": False,
    #                 "options": {"temperature": 0, "num_predict": 5},
    #             },
    #             timeout=(30, 120),
    #         )
    #         raw = response.json().get("response", "").strip().upper()
    #         # The model occasionally adds punctuation or a brief explanation;
    #         # take just the first token.
    #         first = raw.split()[0].rstrip(".,!?:;") if raw else ""
    #         logger.info(
    #             f"Internet-needed classifier raw={raw!r} → decision={first!r}"
    #         )
    #         return first in ("YES", "Y")
    #     except Exception as e:
    #         logger.warning(f"Internet classifier call failed: {e}; assuming NO")
    #         return False

    def query_ollama(
        self,
        prompt: str,
        model=None,
        temperature=0.7,
        user_query: Optional[str] = None,
        history: Optional[List[Dict[str, str]]] = None,
        status_callback: Optional[Callable[[str, Dict[str, Any]], None]] = None,
        needs_internet_override: Optional[bool] = None,
    ):
        """Answer-first Ollama flow with automatic web fallback.

        When `history` is provided (multi-turn chat), the LLM is called via
        /api/chat with role-tagged messages so the model's native chat
        template kicks in. /api/generate (single-string transcript) is fine
        for one-shot prompts but causes small models to keep continuing the
        prior topic when there's chat history.

        `prompt`           — the latest user question (string; current turn).
        `user_query`       — explicit latest question; falls back to `prompt`.
                             Used for the YES/NO classifier and the web search.
        `history`          — list of `{"role": "user"|"assistant", "content"}`
                             for prior turns, OR None for single-turn requests.
        `needs_internet_override` — when not None, SKIP the YES/NO classifier
                             and use this value directly. Set by the preview
                             flow which already ran the classifier upstream
                             (in /api/optimize) and doesn't want to pay for
                             the round-trip again.
        """
        model = model or settings.OLLAMA_MODEL
        date_context = _current_date_context()
        latest_question = (user_query or prompt).strip()

        logger.info(
            f"query_ollama: latest_question={latest_question[:120]!r}, "
            f"history_turns={len(history) if history else 0}, "
            f"needs_internet_override={needs_internet_override}"
        )

        # Fast path: "current time in <city>" → compute from zoneinfo. Avoids
        # the wrong-time bug where DDG snippets quoted a stale article time.
        time_lookup = _try_answer_time_in_city(latest_question)
        if time_lookup:
            answer, city, tz_name = time_lookup
            logger.info(
                f"Time query handled deterministically (city={city!r}, "
                f"tz={tz_name!r})"
            )
            self._safe_emit(
                status_callback,
                "time_lookup",
                city=city,
                timezone=tz_name,
            )
            tokens = {
                "prompt_tokens": len(latest_question.split()),
                "response_tokens": len(answer.split()),
            }
            tokens["total_tokens"] = (
                tokens["prompt_tokens"] + tokens["response_tokens"]
            )
            return answer, tokens

        # Honour caller's precomputed decision when given; otherwise run the
        # YES/NO classifier as before.
        if needs_internet_override is not None:
            needs_web = bool(needs_internet_override)
            logger.info(f"Ollama: needs_web={needs_web} (precomputed)")
        else:
            needs_web = self._classify_needs_internet(latest_question, model)
            logger.info(f"Ollama: needs_web={needs_web}")

        if needs_web:
            return self._ollama_with_web_context(
                latest_question, model, temperature, date_context,
                history=history,
                status_callback=status_callback,
            )

        # Classifier said NO — answer directly with the date preamble.
        if history:
            # Multi-turn: use /api/chat with role tags so the model answers
            # the LATEST user message under its chat template instead of
            # continuing the previous topic.
            messages = (
                [{"role": "system", "content": date_context}]
                + list(history)
                + [{"role": "user", "content": latest_question}]
            )
            response_text, tokens = self._raw_ollama_chat(
                messages, model, temperature
            )
        else:
            first_prompt = f"{date_context}\n\n{prompt}"
            response_text, tokens = self._raw_ollama_generate(
                first_prompt, model, temperature
            )

        # Safety net: classifier was wrong and the model bailed out. Search
        # the web and re-ask anyway.
        if _response_indicates_no_internet(response_text):
            logger.info(
                "Classifier said NO but model refused for lack of data; "
                f"falling back to web search. Snippet: {response_text[:120]!r}"
            )
            web_text, web_tokens = self._ollama_with_web_context(
                latest_question, model, temperature, date_context,
                history=history,
                status_callback=status_callback,
            )
            combined = {
                "prompt_tokens": tokens.get("prompt_tokens", 0)
                + web_tokens.get("prompt_tokens", 0),
                "response_tokens": tokens.get("response_tokens", 0)
                + web_tokens.get("response_tokens", 0),
                "total_tokens": tokens.get("total_tokens", 0)
                + web_tokens.get("total_tokens", 0),
            }
            return web_text, combined

        return response_text, tokens

    # def query_ollama(
    #     self, prompt: str, model: Optional[str] = None, temperature: float = 0.7
    # ) -> Tuple[str, Dict[str, int]]:
    #     """Query Ollama local model"""
    #     try:
    #         model = model or settings.OLLAMA_MODEL

    #         response = requests.post(
    #             f"{settings.OLLAMA_API_URL}/api/generate",
    #             json={
    #                 "model": model,
    #                 "prompt": prompt,
    #                 "temperature": temperature,
    #                 "stream": False,
    #             },
    #             timeout=_ollama_timeouts(),
    #         )

    #         if response.status_code == 200:
    #             result = response.json()
    #             response_text = result.get("response", "")

    #             # Estimate tokens
    #             tokens_used = {
    #                 "prompt_tokens": len(prompt.split()),
    #                 "response_tokens": len(response_text.split()),
    #             }
    #             tokens_used["total_tokens"] = (
    #                 tokens_used["prompt_tokens"] + tokens_used["response_tokens"]
    #             )

    #             logger.info(f"Ollama response generated: {tokens_used['total_tokens']} tokens")
    #             return response_text, tokens_used
    #         else:
    #             logger.error(f"Ollama error: {response.status_code}")
    #             raise Exception(f"Ollama error: {response.status_code}")

    #     except (requests.exceptions.ConnectTimeout, requests.exceptions.ConnectionError) as e:
    #         logger.error(_ollama_unreachable_message(e))
    #         raise
    #     except Exception as e:
    #         logger.error(f"Error querying Ollama: {e}")
    #         raise

    def query_openai(
        self,
        prompt: str,
        model: Optional[str] = None,
        temperature: float = 0.7,
        api_key: Optional[str] = None,
    ) -> Tuple[str, Dict[str, int]]:
        """Query OpenAI API"""
        try:
            api_key = api_key or self.openai_key
            if not api_key:
                raise Exception("OpenAI API key not configured")

            model = model or settings.OPENAI_MODEL

            from openai import OpenAI

            client = OpenAI(api_key=api_key)

            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=temperature,
            )

            response_text = response.choices[0].message.content
            tokens_used = {
                "prompt_tokens": response.usage.prompt_tokens,
                "response_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            }

            logger.info(f"OpenAI response generated: {tokens_used['total_tokens']} tokens")
            return response_text, tokens_used

        except Exception as e:
            logger.error(f"Error querying OpenAI: {e}")
            raise

    def query_anthropic(
        self,
        prompt: str,
        model: Optional[str] = None,
        temperature: float = 0.7,
        api_key: Optional[str] = None,
    ) -> Tuple[str, Dict[str, int]]:
        """Query Anthropic Claude API"""
        try:
            api_key = api_key or self.anthropic_key
            if not api_key:
                raise Exception("Anthropic API key not configured")

            model = model or settings.ANTHROPIC_MODEL

            from anthropic import Anthropic

            client = Anthropic(api_key=api_key)

            response = client.messages.create(
                model=model,
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt}],
                temperature=temperature,
            )

            response_text = response.content[0].text
            tokens_used = {
                "prompt_tokens": response.usage.input_tokens,
                "response_tokens": response.usage.output_tokens,
                "total_tokens": response.usage.input_tokens
                + response.usage.output_tokens,
            }

            logger.info(f"Anthropic response generated: {tokens_used['total_tokens']} tokens")
            return response_text, tokens_used

        except Exception as e:
            logger.error(f"Error querying Anthropic: {e}")
            raise

    def query(
        self,
        prompt: str,
        model: str = "ollama",
        temperature: float = 0.7,
        api_key: Optional[str] = None,
    ) -> Tuple[str, Dict[str, int]]:
        """Query appropriate LLM based on model parameter"""
        logger.info(f"Querying {model} with prompt length: {len(prompt)}")

        if model.lower() == "openai" or model.startswith("gpt"):
            return self.query_openai(prompt, model, temperature, api_key=api_key)
        elif model.lower() == "anthropic" or model.startswith("claude"):
            return self.query_anthropic(prompt, model, temperature, api_key=api_key)
        else:
            return self.query_ollama(prompt, model, temperature)

    def list_models(self, provider: str, api_key: Optional[str] = None):
        """Return a list of available models for a given provider.

        Results are cached in-memory for a few minutes per (provider, key) pair
        so opening the chat / API keys page repeatedly doesn't hammer
        api.openai.com or api.anthropic.com.
        """
        provider = provider.lower()
        key_fingerprint = hashlib.sha256(
            (api_key or "").encode()
        ).hexdigest()[:12] if api_key else "none"
        cache_key = f"{provider}:{key_fingerprint}"
        cached = _MODELS_CACHE.get(cache_key)
        if cached and (time.time() - cached[0]) < _MODELS_CACHE_TTL_SECONDS:
            return cached[1]

        def _remember(models: list) -> list:
            """Cache a successful provider response."""
            _MODELS_CACHE[cache_key] = (time.time(), models)
            return models

        try:
            # OpenAI: call REST /v1/models
            if provider == "openai":
                key = api_key or self.openai_key
                if not key:
                    # No key available, return common public defaults
                    return ["gpt-4", "gpt-4o", "gpt-3.5-turbo"]

                resp = requests.get(
                    "https://api.openai.com/v1/models",
                    headers={"Authorization": f"Bearer {key}"},
                    timeout=10,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    names = [m.get("id") for m in data.get("data", []) if m.get("id")]
                    # Strip non-chat models (embeddings, TTS, Whisper, Sora,
                    # image, etc.) — the dropdown is useless with 100+ entries.
                    chat_only = [n for n in names if _is_openai_chat_model(n)]
                    chat_only = _dedupe_dated_variants(chat_only)
                    return _remember(chat_only or names[:10] or ["gpt-4", "gpt-3.5-turbo"])
                logger.warning(f"OpenAI models list returned {resp.status_code}")
                return ["gpt-4", "gpt-3.5-turbo"]

            # Anthropic: many SDKs don't expose a standard list endpoint; return common names
            if provider == "anthropic":
                key = api_key or self.anthropic_key
                if not key:
                    return ["claude-3-opus", "claude-3-sonnet"]
                try:
                    resp = requests.get(
                        "https://api.anthropic.com/v1/models",
                        headers={"x-api-key": key},
                        timeout=10,
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        names = [m.get("model") or m.get("name") for m in data.get("models", [])]
                        return _remember(names or ["claude-3-opus", "claude-3-sonnet"])
                except Exception:
                    pass
                return ["claude-3-opus", "claude-3-sonnet"]

            # Ollama: return local configured model or attempt /api/models
            if provider == "ollama":
                try:
                    resp = requests.get(
                        f"{settings.OLLAMA_API_URL}/api/models",
                        timeout=_ollama_timeouts(read_override=5),
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        names = [m.get("name") or m.get("model") for m in data]
                        return _remember(names or [settings.OLLAMA_MODEL])
                except (requests.exceptions.ConnectTimeout, requests.exceptions.ConnectionError) as e:
                    logger.warning(_ollama_unreachable_message(e))
                except Exception:
                    pass
                return [settings.OLLAMA_MODEL]

            # Unknown provider: return empty list
            return []

        except Exception as e:
            logger.error(f"Error listing models for {provider}: {e}")
            # Fallback lists
            if provider == "openai":
                return ["gpt-4", "gpt-3.5-turbo"]
            if provider == "anthropic":
                return ["claude-3-opus", "claude-3-sonnet"]
            if provider == "ollama":
                return [settings.OLLAMA_MODEL]
            return []
