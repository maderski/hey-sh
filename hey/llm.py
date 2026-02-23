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
