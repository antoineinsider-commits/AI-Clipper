"""
Thin wrapper around llama-cpp-python so the rest of the pipeline can just
call `llm.ask(prompt)` and get text back, with JSON extraction helpers.
Fully local -- no network calls, no API keys.
"""
import json
import os
import re

_MODEL = None


def _get_model():
    global _MODEL
    if _MODEL is None:
        from llama_cpp import Llama

        model_path = os.environ.get("LLM_MODEL_PATH", "models/llm.gguf")
        # n_ctx large enough to hold a full transcript + prompt scaffolding.
        # n_threads=0 lets llama.cpp auto-detect available CPU cores.
        _MODEL = Llama(
            model_path=model_path,
            n_ctx=16384,
            n_threads=os.cpu_count() or 4,
            verbose=False,
        )
    return _MODEL


def ask(prompt: str, max_tokens: int = 1500, temperature: float = 0.4) -> str:
    """Send a prompt to the local LLM and return the raw text response."""
    model = _get_model()

    # Safety net: if the prompt is too big for the context window even after
    # upstream sampling, trim it from the middle (keep the start and end,
    # which usually carry the most structurally important content) rather
    # than crashing.
    n_ctx = model.n_ctx()
    tokens = model.tokenize(prompt.encode("utf-8"))
    available = n_ctx - max_tokens - 32  # safety margin
    if len(tokens) > available:
        head_take = available // 2
        tail_take = available - head_take
        trimmed_tokens = tokens[:head_take] + tokens[-tail_take:]
        prompt = model.detokenize(trimmed_tokens).decode("utf-8", errors="ignore")

    result = model(
        prompt,
        max_tokens=max_tokens,
        temperature=temperature,
        stop=["</s>", "<|im_end|>"],
    )
    return result["choices"][0]["text"].strip()


def ask_json(prompt: str, max_tokens: int = 1500, temperature: float = 0.3) -> dict:
    """
    Ask the model for JSON and robustly extract it, even if the model wraps
    it in prose or markdown code fences (small local models often do).
    """
    raw = ask(prompt, max_tokens=max_tokens, temperature=temperature)
    # Strip markdown code fences if present.
    fenced = re.search(r"```(?:json)?\s*(\{.*\}|\[.*\])\s*```", raw, re.DOTALL)
    candidate = fenced.group(1) if fenced else raw

    # If there's still leading/trailing prose, grab the first {...} or [...] block.
    if not fenced:
        brace_match = re.search(r"(\{.*\}|\[.*\])", raw, re.DOTALL)
        if brace_match:
            candidate = brace_match.group(1)

    try:
        return json.loads(candidate)
    except json.JSONDecodeError as e:
        raise ValueError(
            f"Local LLM did not return valid JSON. Raw output:\n{raw}"
        ) from e
