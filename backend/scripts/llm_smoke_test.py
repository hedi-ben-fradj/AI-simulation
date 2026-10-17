"""Run a small world with real LLM agents and print what they decide and say.

    OPENROUTER_API_KEY=sk-or-...  python scripts/llm_smoke_test.py --provider openrouter \\
        --model google/gemini-2.5-flash --ticks 24
    python scripts/llm_smoke_test.py --provider claude_code --model haiku --ticks 6   # uses your subscription
    ANTHROPIC_API_KEY=sk-ant-...  python scripts/llm_smoke_test.py --provider anthropic --model claude-haiku-5-5

The key is read from the environment (never pass it on the command line). The
world is small, chatty (free messages, sociable agents) and starts with agents
side by side, so a few ticks show conversation, cooperation and the engine
rejecting impossible actions. Ends with a summary of calls, failures and cost.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from collections import Counter

from aisim.agents.service import LLMDecider
from aisim.config import load_config
from aisim.config.setup import COMMUNICATION_COSTS
from aisim.engine import Simulation


def build_config(args):
    return load_config("default", {
        "resource_level": args.resources,
        "simulation": {"population": args.agents, "random_seed": args.seed,
                       "decision_timeout_seconds": args.timeout},
        "world": {"width": 60.0, "height": 60.0},
        "communication": dict(COMMUNICATION_COSTS["cheap"]),
        "personality": {"initial_distribution": "normal", "initial_spread": 0.2,
                        "trait_means": {"sociability": 0.75, "agreeableness": 0.65}},
        "llm": {"provider": args.provider, "model": args.model, "effort": args.effort or None,
                "maximum_world_spend": args.max_spend, "maximum_agent_daily_spend": None,
                "max_concurrent_requests": args.concurrency,
                "claude_code_session_mode": args.session_mode},
    })


async def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--provider", choices=["openrouter", "anthropic", "claude_code", "mock"], default="openrouter")
    p.add_argument("--model", default="google/gemini-2.5-flash")
    p.add_argument("--effort", default="low", help="low | medium | high | '' for the model default")
    p.add_argument("--agents", type=int, default=3)
    p.add_argument("--ticks", type=int, default=12)
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--resources", default="normal")
    p.add_argument("--timeout", type=float, default=60.0, help="decision window per tick (seconds)")
    p.add_argument("--concurrency", type=int, default=3)
    p.add_argument("--max-spend", type=float, default=0.50, help="USD cap for this run")
    p.add_argument("--session-mode", choices=["per_agent", "fresh"], default="fresh")
    args = p.parse_args()

    cfg = build_config(args)
    sim = Simulation.create(cfg, f"smoke-{int(time.time())}")
    # Start everyone together at the gathering place so they meet straight away.
    plaza = next((loc for loc in sim.world.locations.values() if loc.type == "gathering"), None)
    for agent in sim.world.agents.values():
        if plaza:
            agent.x, agent.y = plaza.x, plaza.y
    decider = LLMDecider.from_config(cfg, sim.world.id)
    names = {a.id: a.name for a in sim.world.agents.values()}
    print(f"provider={args.provider} model={decider.provider.model} credential={decider.credential} "
          f"agents={', '.join(names.values())}\n")
    sources: Counter[str] = Counter()
    fallbacks: Counter[str] = Counter()
    rejections: Counter[str] = Counter()
    try:
        for _ in range(args.ticks):
            t0 = time.monotonic()
            requests = sim.begin_tick()
            proposals, meta = await decider.decide(sim, requests)
            sim.apply_decisions(proposals, meta)
            result = sim.advance()
            print(f"── {sim.time_label(result.tick)}  ({time.monotonic() - t0:.1f}s, {len(requests)} decision(s))")
            for d in result.decisions:
                sources[d.source] += 1
                if d.fallback_reason:
                    fallbacks[d.fallback_reason] += 1
                if not d.valid and d.reason:
                    rejections[d.reason] += 1
                flag = "" if d.valid else f"  ✗ rejected: {d.reason}"
                fb = f"  ↺ fallback: {d.fallback_reason}" if d.fallback_reason else ""
                intent = f' — "{d.visible_intention}"' if d.visible_intention else ""
                print(f"   {names.get(d.agent_id, d.agent_id):<6} [{d.source:<8}] {d.proposal.get('action')}"
                      f"{' → ' + str(d.proposal.get('target')) if d.proposal.get('target') else ''}{intent}{flag}{fb}")
            for m in result.messages:
                print(f'   💬 {m.sender_name} → {names.get(m.recipient_id, m.recipient_id)}: "{m.content}"')
            for e in result.events:
                if e.type in ("trade", "give", "theft", "death", "belief_update", "existential_activation"):
                    print(f"   • {e.summary}")
    finally:
        stats = decider.stats()
        await decider.close()
    print("\nSummary")
    print(f"  decisions by source: {dict(sources)}")
    print(f"  LLM requests: {stats['requests']}, failures: {stats['failures']}, timeouts: {stats['timeouts']}")
    print(f"  fallbacks: {dict(fallbacks) or 'none'}")
    print(f"  engine rejections: {dict(rejections) or 'none'}")
    print(f"  spend: ${stats['spend_usd']:.4f}")
    for agent in sim.world.agents.values():
        print(f"  {agent.name}: health {agent.health:.0f}, hunger {agent.hunger:.0f}, tokens {agent.tokens:.1f}, "
              f"mood {agent.current_mood}")
    return 0 if stats["requests"] and stats["failures"] < stats["requests"] else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
