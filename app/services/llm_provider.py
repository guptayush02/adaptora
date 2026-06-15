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
    if not text:
        return False
    t = text.lower()
    return any(p in t for p in _NO_INTERNET_PATTERNS)

def _response_has_stale_year(text: str, results_block: str) -> bool:
    if not text:
        return False
    current_year = datetime.now().year
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

_CITY_TIMEZONES: Dict[str, str] = {
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
    "sao paulo": "America/Sao_Paulo",
    "rio de janeiro": "America/Sao_Paulo",
    "buenos aires": "America/Argentina/Buenos_Aires",
    "lima": "America/Lima",
    "bogota": "America/Bogota",
    "santiago": "America/Santiago",
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
    "cairo": "Africa/Cairo",
    "johannesburg": "Africa/Johannesburg",
    "cape town": "Africa/Johannesburg",
    "lagos": "Africa/Lagos",
    "nairobi": "Africa/Nairobi",
    "casablanca": "Africa/Casablanca",
    "accra": "Africa/Accra",
    "sydney": "Australia/Sydney",
    "melbourne": "Australia/Melbourne",
    "brisbane": "Australia/Brisbane",
    "perth": "Australia/Perth",
    "adelaide": "Australia/Adelaide",
    "auckland": "Pacific/Auckland",
    "wellington": "Pacific/Auckland",
}

_CITY_TIMEZONE_ITEMS = sorted(
    _CITY_TIMEZONES.items(), key=lambda kv: -len(kv[0])
)

_TIME_QUERY_DISQUALIFIERS = (
    "history", "historical", "ago", "before", "yesterday", "tomorrow",
    "last week", "next week", "last month", "next month",
    "last year", "next year", "year ago", "years ago",
    "minutes ago", "hours ago",
)

def _try_answer_time_in_city(prompt: str) -> Optional[Tuple[str, str, str]]:
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
        from zoneinfo import ZoneInfo
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

_MODELS_CACHE: Dict[str, Tuple[float, list]] = {}
_MODELS_CACHE_TTL_SECONDS = 300

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
    m = (model_id or "").lower()
    if any(kw in m for kw in _OPENAI_NON_CHAT_KEYWORDS):
        return False
    return m.startswith(_OPENAI_CHAT_PREFIXES)

def _dedupe_dated_variants(models: list) -> list:
    import re as _re

    base_set = set(models)
    date_pattern = _re.compile(r"-\d{4,}(?:-\d+)*$")
    pruned = []
    for m in models:
        stripped = date_pattern.sub("", m)
        if stripped != m and stripped in base_set:
            continue
        pruned.append(m)
    return pruned

class LLMProvider:

    def __init__(self):
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
        response = requests.post(
            f"{settings.OLLAMA_API_URL}/api/generate",
            json={
                "model": model,
                "prompt": full_prompt,
                "stream": False,
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
        response = requests.post(
            f"{settings.OLLAMA_API_URL}/api/chat",
            json={
                "model": model,
                "messages": messages,
                "stream": False,
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
            print(f"results from google search: {results}")
            return results
        except Exception as e:
            print(f"Google search error: {e}")
            return []

    _TAVILY_OVERALL_TIMEOUT_SECONDS = 15

    def _search_tavily(
        self, query: str, max_results: int = 5
    ) -> Optional[list]:
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
                search_depth="basic",
                include_answer=False,
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
            raw_items = data.get("results") or data.get("data") or []
            items = []
            for item in raw_items[:max_results]:
                body = (
                    item.get("content")
                    or item.get("snippet")
                    or item.get("body")
                    or ""
                )
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
                    "num": max(1, min(max_results, 10)),
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

        ddg_results = self._search_duckduckgo(query, max_results)
        return ddg_results, "duckduckgo"

    @staticmethod
    def _format_results_block(results: list) -> str:
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

    @classmethod
    def _fetch_url_content(
        cls,
        url: str,
        timeout: float = 6.0,
        max_bytes: int = 800_000,
        max_chars: int = 8000,
    ) -> Optional[str]:
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

    _ENRICH_BODY_CHAR_THRESHOLD = 500

    def _enrich_results_with_page_content(
        self,
        results: list,
        max_to_fetch: int = 5,
        per_url_timeout: float = 6.0,
        overall_timeout: float = 15.0,
    ) -> list:
        import concurrent.futures

        if not results:
            return results

        targets = []
        skipped_existing = 0
        for idx, r in enumerate(results[:max_to_fetch]):
            body_len = len(r.get("body") or "")
            if body_len >= self._ENRICH_BODY_CHAR_THRESHOLD:
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
        if not text:
            return ""
        cleaned = re.sub(r"\s+", " ", text).strip()
        if not cleaned:
            return ""
        if len(cleaned) <= max_chars:
            return cleaned
        sentences = re.split(r"(?<=[.!?])\s+", cleaned)
        acc = ""
        for s in sentences:
            candidate = (acc + " " + s).strip() if acc else s
            if len(candidate) > max_chars:
                if not acc:
                    return s[:max_chars].rsplit(" ", 1)[0] + "…"
                break
            acc = candidate
        return acc or cleaned[:max_chars].rsplit(" ", 1)[0] + "…"

    @staticmethod
    def _raw_results_fallback(prompt: str, results: list) -> str:
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
        date_context: Optional[str] = None,
        history: Optional[List[Dict[str, str]]] = None,
        status_callback: Optional[Callable[[str, Dict[str, Any]], None]] = None,
    ) -> Tuple[str, Dict[str, int]]:
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

        print(f"Web search results for {prompt!r}: {results}")

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

        citation_lookup_lines = []
        for i, r in enumerate(results[:5], start=1):
            t = (r.get("title") or "").strip().replace("\n", " ")
            u = (r.get("url") or "").strip()
            if not u:
                continue
            if len(t) > 80:
                t = t[:77].rsplit(" ", 1)[0] + "…"
            citation_lookup_lines.append(f"[{i}] title={t!r} url={u}")
        citation_lookup_block = (
            "\n".join(citation_lookup_lines) or "(no citable results)"
        )

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

        ...

        ...

        - ...Remove markdown links from `text` whose URL points to a HOST
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

        def _link_repl(match):
            link_text = match.group(1)
            url = match.group(2)
            return match.group(0) if _url_is_allowed(url) else link_text

        text = re.sub(
            r"\[([^\]\n]+)\]\((https?://[^\s)]+)\)",
            _link_repl,
            text,
        )

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
        if not web_sources_payload:
            return text

        text_without_sources = re.sub(
            r"\n*
            "",
            text,
            flags=re.DOTALL | re.IGNORECASE,
        ).rstrip()

        lines = ["---", "", "
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

        if len(lines) == 4:
            return text

        return text_without_sources + "\n\n" + "\n".join(lines)

    def _classify_needs_internet(self, prompt: str, model: str) -> bool:
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
            return True

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
        model = model or settings.OLLAMA_MODEL
        date_context = _current_date_context()
        latest_question = (user_query or prompt).strip()

        logger.info(
            f"query_ollama: latest_question={latest_question[:120]!r}, "
            f"history_turns={len(history) if history else 0}, "
            f"needs_internet_override={needs_internet_override}"
        )

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

        if history:
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

    def query_openai(
        self,
        prompt: str,
        model: Optional[str] = None,
        temperature: float = 0.7,
        api_key: Optional[str] = None,
    ) -> Tuple[str, Dict[str, int]]:
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
        logger.info(f"Querying {model} with prompt length: {len(prompt)}")

        if model.lower() == "openai" or model.startswith("gpt"):
            return self.query_openai(prompt, model, temperature, api_key=api_key)
        elif model.lower() == "anthropic" or model.startswith("claude"):
            return self.query_anthropic(prompt, model, temperature, api_key=api_key)
        else:
            return self.query_ollama(prompt, model, temperature)

    def list_models(self, provider: str, api_key: Optional[str] = None):
        provider = provider.lower()
        key_fingerprint = hashlib.sha256(
            (api_key or "").encode()
        ).hexdigest()[:12] if api_key else "none"
        cache_key = f"{provider}:{key_fingerprint}"
        cached = _MODELS_CACHE.get(cache_key)
        if cached and (time.time() - cached[0]) < _MODELS_CACHE_TTL_SECONDS:
            return cached[1]

        def _remember(models: list) -> list:
            _MODELS_CACHE[cache_key] = (time.time(), models)
            return models

        try:
            if provider == "openai":
                key = api_key or self.openai_key
                if not key:
                    return ["gpt-4", "gpt-4o", "gpt-3.5-turbo"]

                resp = requests.get(
                    "https://api.openai.com/v1/models",
                    headers={"Authorization": f"Bearer {key}"},
                    timeout=10,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    names = [m.get("id") for m in data.get("data", []) if m.get("id")]
                    chat_only = [n for n in names if _is_openai_chat_model(n)]
                    chat_only = _dedupe_dated_variants(chat_only)
                    return _remember(chat_only or names[:10] or ["gpt-4", "gpt-3.5-turbo"])
                logger.warning(f"OpenAI models list returned {resp.status_code}")
                return ["gpt-4", "gpt-3.5-turbo"]

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

            return []

        except Exception as e:
            logger.error(f"Error listing models for {provider}: {e}")
            if provider == "openai":
                return ["gpt-4", "gpt-3.5-turbo"]
            if provider == "anthropic":
                return ["claude-3-opus", "claude-3-sonnet"]
            if provider == "ollama":
                return [settings.OLLAMA_MODEL]
            return []
