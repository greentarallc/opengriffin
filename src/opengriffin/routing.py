"""Provider Routing Auctions — pick the cheapest provider that can answer.

Lightweight regex+heuristic classifier scores each prompt 0–3:
  0 = trivial    → cheapest tier (Cerebras/Groq/Ollama)
  1 = simple     → mid tier (gpt-4o-mini, claude-haiku, deepseek-chat)
  2 = standard   → strong tier (gpt-4o, claude-sonnet)
  3 = hard       → premium tier (claude-opus, o1, deepseek-reasoner)

The router doesn't replace the active provider — it ANNOTATES the prompt
with a recommended tier, which the caller can use to pick a model. Easy
to wire into per-chat /model selection or auto-routing modes.

Hard prompts come back as 3 even if they look short ("solve P=NP" is short).
"""

from __future__ import annotations

from typing import Annotated

from claude_agent_sdk import create_sdk_mcp_server, tool

# Tier → ordered fallback chain (provider, model)
TIER_CHAINS = {
    0: [("groq", "llama-3.3-70b-versatile"), ("cerebras", "llama-3.3-70b"), ("ollama", "llama3.1")],
    1: [
        ("openai", "gpt-4o-mini"),
        ("anthropic", "claude-haiku-4-5"),
        ("deepseek", "deepseek-chat"),
        ("gemini", "gemini-1.5-flash"),
    ],
    2: [("anthropic", "claude-sonnet-4-6"), ("openai", "gpt-4o"), ("gemini", "gemini-1.5-pro")],
    3: [("anthropic", "claude-opus-4-7"), ("openai", "o1"), ("deepseek", "deepseek-reasoner")],
}


def classify(prompt: str) -> tuple[int, str]:
    """Return (tier, reason)."""
    p = prompt.strip().lower()
    n_words = len(p.split())

    # Hard signals
    hard_kws = [
        "prove",
        "derive",
        "formal proof",
        "complexity class",
        "design a system",
        "architect",
        "research paper",
        "analyze the trade-offs",
        "phd",
        "olympiad",
        "imo",
        "aime",
        "competitive programming",
        "explain step-by-step the math",
        "rigorously",
    ]
    if any(k in p for k in hard_kws):
        return 3, "hard keyword present"

    # Simple signals
    if n_words <= 8 and not any(c in p for c in (" why ", " how ", " explain ", "analyze")):
        return 0, "very short, likely lookup"
    if any(k in p for k in ("hello", "hi ", "thanks", "thank you", "ok", "got it")):
        return 0, "social"
    if any(k in p for k in ("convert", "format", "list", "summarize")):
        return 1, "simple structured task"

    # Length-based default
    if n_words > 200:
        return 2, "long prompt, standard tier"
    if n_words > 60:
        return 2, "medium prompt, standard tier"
    return 1, "short prompt, simple tier"


def pick(prompt: str, tier_floor: int = 0) -> tuple[int, list[tuple[str, str]], str]:
    """Pick a tier (>= floor) and return its fallback chain."""
    tier, reason = classify(prompt)
    tier = max(tier, tier_floor)
    return tier, TIER_CHAINS[tier], reason


@tool(
    "routing_classify",
    "Classify a prompt into a routing tier (0=trivial through 3=hard). Returns the recommended provider/model fallback chain.",
    {"prompt": Annotated[str, "Prompt to classify"]},
)
async def _classify(args: dict) -> dict:
    tier, chain, reason = pick(args["prompt"])
    text = f"tier {tier} ({reason})\nfallback chain: {chain}"
    return {"content": [{"type": "text", "text": text}]}


ROUTING_SERVER = create_sdk_mcp_server(
    name="routing",
    version="1.0.0",
    tools=[_classify],
)
