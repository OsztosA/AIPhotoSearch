import requests


class LLMError(Exception):
    pass


def _post(base: str, key: str, endpoint: str, payload: dict, timeout: int) -> dict:
    try:
        r = requests.post(
            base.rstrip("/") + endpoint,
            json=payload,
            headers={"Authorization": f"Bearer {key}"},
            timeout=timeout,
        )
        if not r.ok:
            raise LLMError(f"{endpoint}: {r.status_code} {r.text[:500]}")
        return r.json()
    except (requests.RequestException, ValueError) as e:
        raise LLMError(f"{endpoint}: {e}") from e


def chat(cfg: dict, system: str, user: str) -> str:
    data = _post(cfg["llm_base_url"], cfg["llm_api_key"], "/chat/completions", {
        "model": cfg["llm_model"],
        "temperature": cfg["llm_temperature"],
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
    }, cfg["request_timeout"])
    try:
        return data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError) as e:
        raise LLMError(f"unexpected chat response: {data}") from e


def embed(cfg: dict, texts: list[str]) -> list[list[float]]:
    data = _post(cfg["embed_base_url"], cfg["embed_api_key"], "/embeddings", {
        "model": cfg["embed_model"],
        "input": texts,
    }, cfg["request_timeout"])
    try:
        items = sorted(data["data"], key=lambda d: d.get("index", 0))
        return [d["embedding"] for d in items]
    except (KeyError, TypeError) as e:
        raise LLMError(f"unexpected embeddings response: {data}") from e
