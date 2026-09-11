"""
Web grounding for BRIEF, using the OpenAI Responses API web_search tool.

The archaeology agent calls retrieve(). A reasoning model (default gpt-5.4-mini,
medium reasoning effort) plans sub-queries, searches the live web, reads pages,
and returns a synthesised answer with url_citation annotations. This matches the
agentic retrieval that the original Foundry IQ knowledge base provided.

Contract:
  retrieve(query) -> {"grounded": bool, "answer": str,
                      "citations": [{"title": str, "url": str, "snippet": str}]}

Fails soft. On any error it returns an empty result and the archaeology agent
falls back to model-only analysis.
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import config
from llm import client, parse_json

log = logging.getLogger("brief.grounding")

GROUNDING_MODEL = config.GROUNDING_MODEL
GROUNDING_EFFORT = config.GROUNDING_EFFORT
RETRIEVE_TIMEOUT = config.GROUNDING_TIMEOUT_SECONDS

# URL fragments that mark a page as low value for evidence (about pages, marketing).
LOW_VALUE_URL_MARKERS = ("/about", "about-us", "about_us", "/o-nas", "/ueber-uns", "/uber-uns",
                         "who-we-are", "/contact", "/careers", "/press-release", "/imprint", "/impressum")


def _clean_url(url: str) -> str:
    """Remove tracking parameters such as utm_source so citations are clean."""
    try:
        parts = urlsplit(url)
        query = [(k, v) for k, v in parse_qsl(parts.query) if not k.lower().startswith("utm_")]
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))
    except Exception:
        return url


_MD_LINK = re.compile(r"\(?\[([^\]]*)\]\((https?://[^)\s]+)\)\)?")
_BARE_UTM = re.compile(r"\?utm_source=\w+")


def _clean_prose(text: str) -> str:
    """Strip markdown links, tracking parameters and stray symbols the model puts in findings."""
    text = _MD_LINK.sub("", text)
    text = _BARE_UTM.sub("", text)
    text = re.sub(r"[\u2500-\u25ff\U0001F000-\U0001FFFF]", "", text)  # box-drawing, blocks, emoji
    return re.sub(r"\s+", " ", text).strip(" .;,") + ("." if text.strip() and not text.strip().endswith((".", "!", "?")) else "")


def is_configured() -> bool:
    if not config.ENABLE_WEB_GROUNDING:
        log.info("Web grounding is disabled by policy.")
        return False
    if not config.OPENAI_API_KEY:
        log.warning("OPENAI_API_KEY is missing; web grounding disabled.")
        return False
    return True


def retrieve(query: str, max_subqueries: int = 4, instructions: str | None = None) -> dict[str, Any]:
    empty = {"grounded": False, "answer": "", "citations": []}
    if not is_configured():
        return empty

    instructions = instructions or (
        "You are a research librarian. Search the web before you answer. "
        f"Run several distinct searches (up to {max_subqueries}) that cover industry, "
        "media and academic sources. Name the specific publications, institutions "
        "and report types you find. Cite every claim with a source URL."
    )

    try:
        response = client.with_options(timeout=RETRIEVE_TIMEOUT).responses.create(
            model=GROUNDING_MODEL,
            reasoning={"effort": GROUNDING_EFFORT},
            tools=[{"type": "web_search"}],
            instructions=instructions,
            input=query,
            store=False,
        )
    except Exception as e:
        log.warning("grounding call failed: %s: %s", type(e).__name__, e)
        return empty

    answer_text = ""
    citations = []
    searches = 0
    try:
        for item in response.output:
            item_type = getattr(item, "type", "")
            if item_type == "web_search_call":
                searches += 1
                continue
            if item_type != "message":
                continue
            for part in item.content:
                if getattr(part, "type", "") != "output_text":
                    continue
                text = part.text or ""
                answer_text += text
                for ann in getattr(part, "annotations", []) or []:
                    if getattr(ann, "type", "") != "url_citation":
                        continue
                    start = getattr(ann, "start_index", 0) or 0
                    end = getattr(ann, "end_index", 0) or 0
                    snippet = text[max(0, start - 160):end].strip()
                    citations.append({
                        "title": " ".join((getattr(ann, "title", "") or "Source").split())[:120],
                        "url": _clean_url(getattr(ann, "url", "") or ""),
                        "snippet": snippet[:280],
                        "retrieved_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                        "review_status": "unverified",
                    })
    except Exception as e:
        log.warning("could not read grounding output: %s", e)

    seen = set()
    deduped = []
    for c in citations:
        low = c["url"].lower()
        if any(marker in low for marker in LOW_VALUE_URL_MARKERS):
            continue
        key = c["url"] or c["title"]
        if key in seen:
            continue
        seen.add(key)
        deduped.append(c)
    deduped = deduped[:8]

    answer_text = answer_text.strip()
    grounded = bool(answer_text and deduped)
    log.info("model=%s effort=%s searches=%s grounded=%s citations=%s",
             GROUNDING_MODEL, GROUNDING_EFFORT, searches, grounded, len(deduped))
    return {"grounded": grounded, "answer": answer_text, "citations": deduped}


def retrieve_hypothesis_evidence(hypothesis: str, audience: str, geography: str, max_countries: int = 4) -> dict[str, Any]:
    """
    Grounded, structured evidence for and against one client hypothesis.
    Returns:
      {"grounded": bool, "hypothesis": str, "verdict": str, "summary": str,
       "countries": [{"country", "verdict", "for": [{"finding","source","url","year"}],
                      "against": [...]}],
       "citations": [{"title","url","snippet"}]}
    """
    instructions = (
        "You are a research librarian writing for a market research team. Search the web "
        "before you answer. Prefer surveys, regulator and government data, academic studies "
        "and industry reports. Skip 'about us' pages and marketing copy. Write in British "
        "English. Do not use the first person. Do not offer further help. "
        "Return ONLY a JSON object with this exact structure and nothing else:\n"
        "{\n"
        '  "verdict": "supported | partly supported | not supported | insufficient evidence",\n'
        '  "summary": "two or three plain sentences on what the published evidence says overall",\n'
        '  "countries": [\n'
        "    {\n"
        '      "country": "name",\n'
        '      "verdict": "supported | partly supported | not supported | insufficient evidence",\n'
        '      "for": [{"finding": "what the source found, one sentence", "source": "publisher and title", "url": "https://...", "year": "2024"}],\n'
        '      "against": [{"finding": "...", "source": "...", "url": "https://...", "year": "..."}]\n'
        "    }\n"
        "  ]\n"
        "}\n"
        f"Cover each country in the geography separately, up to {max_countries}. Two or three "
        "findings per list where evidence exists. Keep to at most six searches in total. Every finding needs a real URL you found. "
        "If the sources do not isolate the stated audience, say so in the finding."
    )
    query = (
        f'Client hypothesis: "{hypothesis}"\nAudience: {audience}\nGeography: {geography}\n'
        "Find published evidence for and against this hypothesis in each country."
    )
    raw = retrieve(query, instructions=instructions)
    result = {
        "grounded": False, "hypothesis": hypothesis, "verdict": "insufficient evidence",
        "summary": "", "countries": [], "citations": raw.get("citations", []),
    }
    if not raw.get("answer"):
        return result
    data = parse_json(raw["answer"])
    if not isinstance(data, dict) or "raw" in data:
        # Fall back to prose so nothing is lost
        result["summary"] = raw["answer"][:1500]
        result["grounded"] = bool(raw.get("citations"))
        return result
    countries = []
    for c in data.get("countries", []) or []:
        if not isinstance(c, dict):
            continue
        def clean(items):
            out = []
            for it in items or []:
                if not isinstance(it, dict) or not it.get("finding"):
                    continue
                out.append({
                    "finding": _clean_prose(str(it.get("finding", "")))[:700],
                    "source": str(it.get("source", ""))[:160],
                    "url": _clean_url(str(it.get("url", ""))),
                    "year": str(it.get("year", ""))[:4],
                    "review_status": "unverified",
                })
            return out[:4]
        countries.append({
            "country": str(c.get("country", ""))[:60],
            "verdict": str(c.get("verdict", ""))[:40],
            "for": clean(c.get("for")),
            "against": clean(c.get("against")),
        })
    result.update({
        "verdict": str(data.get("verdict", result["verdict"]))[:40],
        "summary": _clean_prose(str(data.get("summary", "")))[:1200],
        "countries": countries,
    })
    result["grounded"] = bool(countries and any(c["for"] or c["against"] for c in countries))
    log.info("hypothesis evidence: %s countries, grounded=%s", len(countries), result["grounded"])
    return result
