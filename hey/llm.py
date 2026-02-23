import time

import httpx

SYSTEM_PROMPT = (
    "You are a shell command expert. Return only the command the user needs, "
    "no markdown, no explanation unless asked. Prefer POSIX-compatible commands "
    "unless the user specifies otherwise."
)

EXPLAIN_SYSTEM_PROMPT = (
    "You are a shell command expert. Output the exact command on its own first line, "
    "then a concise explanation of each part on subsequent lines. No markdown fences. "
    "Prefer POSIX-compatible commands unless the user specifies otherwise."
)


def query_llm(
    prompt: str,
    explain: bool,
    shell: str,
    endpoint: str,
    model: str,
) -> str:
    base = EXPLAIN_SYSTEM_PROMPT if explain else SYSTEM_PROMPT
    system = f"{base} The user's shell is {shell}."

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.1,
        "max_tokens": 512,
    }

    with httpx.Client(timeout=30.0) as client:
        response = client.post(endpoint, json=payload)
        response.raise_for_status()

    data = response.json()
    return data["choices"][0]["message"]["content"]


def ping_llm(endpoint: str, model: str) -> dict:
    """Send a minimal request to verify the endpoint is reachable.

    Returns a dict with keys: ok, elapsed_ms, model, error.
    """
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "hi"}],
        "max_tokens": 1,
    }
    t0 = time.monotonic()
    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.post(endpoint, json=payload)
            response.raise_for_status()
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        data = response.json()
        returned_model = data.get("model", model)
        return {"ok": True, "elapsed_ms": elapsed_ms, "model": returned_model, "error": None}
    except httpx.ConnectError:
        return {"ok": False, "elapsed_ms": None, "model": None, "error": f"Could not connect to {endpoint}"}
    except httpx.TimeoutException:
        return {"ok": False, "elapsed_ms": None, "model": None, "error": "Connection timed out after 10s"}
    except httpx.HTTPStatusError as exc:
        return {"ok": False, "elapsed_ms": None, "model": None, "error": f"HTTP {exc.response.status_code}: {exc.response.text[:120]}"}
    except Exception as exc:
        return {"ok": False, "elapsed_ms": None, "model": None, "error": str(exc)}
