import json
import re
from datetime import date

import llm
from metadata import TIME_OF_DAY
from database import ExifDB, VectorDB

PARSE_SYSTEM = (
    "Today is {today}. Convert the user's photo request into JSON with keys: "
    "\"query\": a short description of the requested subjects and places, with a few synonym keywords. Do not put "
    "dates or times in this description; "
    "\"years\": list of integer years explicitly or relatively mentioned (resolve 'last year' etc.), else []; "
    "\"months\": list of month numbers 1-12 mentioned (a season expands to its months), else []; "
    "\"time_of_day\": list chosen from {tods} if the time of day is mentioned, else []. "
    "Only add a date or time filter when the user explicitly requests one. If no date is specified, years and months "
    "must be empty so photos from any date can match. Use today's date only to resolve an explicit relative date "
    "such as 'last year'. Output only the JSON object."
)
RERANK_SYSTEM = (
    "You select photos matching a user request from numbered candidate descriptions. "
    "Reply ONLY with a JSON array of the matching candidate numbers, best first, e.g. [3,1]. "
    "Use [] if none match."
)


def _ints(v, lo, hi):
    if not isinstance(v, list):
        return []
    return sorted({i for i in v if isinstance(i, int) and not isinstance(i, bool) and lo <= i <= hi})


def build_where(parsed: dict):
    conds = []
    for key, vals in (("year", _ints(parsed.get("years"), 1800, 3000)),
                      ("month", _ints(parsed.get("months"), 1, 12))):
        if vals:
            conds.append({key: {"$in": vals}})
    tods = [t for t in parsed.get("time_of_day") or [] if t in TIME_OF_DAY]
    if tods:
        conds.append({"time_of_day": {"$in": tods}})
    if not conds:
        return None
    return conds[0] if len(conds) == 1 else {"$and": conds}


def parse_request(cfg: dict, query: str, today: str, log):
    try:
        out = llm.chat(cfg, PARSE_SYSTEM.format(today=today, tods=TIME_OF_DAY), query)
        m = re.search(r"\{.*\}", out, re.S)
        parsed = json.loads(m.group(0)) if m else {}
        if isinstance(parsed, dict):
            q = parsed.get("query")
            return (q if isinstance(q, str) and q.strip() else query), build_where(parsed)
    except (llm.LLMError, ValueError) as e:
        log(f"[query parsing skipped] {e}")
    return query, None


def search(cfg: dict, db: ExifDB, vdb: VectorDB, query: str, log=lambda m: None) -> list[dict]:
    today = date.today().strftime("%Y. %B %d")
    q, where = parse_request(cfg, query, today, log)
    log(f"Query: {q}\nFilter: {where}")

    total = vdb.col.count()
    if total == 0:
        return []
    n = min(int(cfg["search_candidates"]), total)
    vec = llm.embed(cfg, ["search_query: " + q])[0]
    res = vdb.col.query(query_embeddings=[vec], n_results=n, where=where)
    cands = []
    for path, doc, dist in zip(res["ids"][0], res["documents"][0], res["distances"][0]):
        row = db.by_path(path)
        cands.append({"path": path, "name": row[1] if row else path, "description": doc, "distance": dist})

    limit = int(cfg["search_max_results"])
    if cfg["use_llm_rerank"] and cands:
        listing = "\n".join(f"{i + 1}. {c['description']}" for i, c in enumerate(cands))
        try:
            out = llm.chat(cfg, RERANK_SYSTEM, f"Request: {query}\n\nCandidates:\n{listing}")
            m = re.search(r"\[[\d,\s]*\]", out)
            picked = json.loads(m.group(0)) if m else None
            if picked is not None:
                chosen = [cands[i - 1] for i in picked if isinstance(i, int) and 1 <= i <= len(cands)]
                return chosen[:limit]
        except (llm.LLMError, ValueError) as e:
            log(f"[rerank skipped] {e}")
    return cands[:limit]
