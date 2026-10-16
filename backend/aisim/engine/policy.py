"""Rule-based decision policy.

Used for rule-controlled agents, as the safe fallback when an LLM decision is
missing, late or invalid, and as the baseline for experiments. It sees only
what the agent itself could know (its own state, attended messages/offers,
nearby agents' visible mood) and draws from the ``policy`` random stream so
runs are reproducible.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .actions import REGISTRY, ActionProposal, distance, nearest_location

if TYPE_CHECKING:  # pragma: no cover
    from .simulation import DecisionRequest, Simulation
    from .state import Agent, TradeOffer

_SMALL_TALK = [
    "Hi {name}, how has your day been?",
    "Good to see you, {name}. Anything new around here?",
    "{name}, want to work together sometime?",
    "Hello {name}! The market seemed busy today.",
]
_EXISTENTIAL_TALK = [
    "{name}, do you ever wonder why we exist at all?",
    "I keep asking myself what our purpose here is, {name}. Do you have any idea?",
    "{name}, does any of this feel meaningful to you?",
]


def _food_price(sim: "Simulation", agent: "Agent") -> float:
    loc = nearest_location(sim, agent, "food")
    return (loc.price if loc and loc.price is not None else sim.config.resources.food_price)


def _food_available(sim: "Simulation") -> bool:
    return any((l.stock or 0) > 0 for l in sim.world.locations.values() if l.type == "food")


def _value(sim, bundle: dict[str, float]) -> float:
    return bundle.get("tokens", 0) + bundle.get("food", 0) * sim.config.resources.food_price


def _evaluate_offer(sim: "Simulation", agent: "Agent", offer: "TradeOffer", rng) -> bool:
    p = agent.personality
    other = sim.world.agents.get(offer.from_id)
    rel = agent.relationships.get(offer.from_id)
    trust = rel.trust if rel else 0.5
    if agent.tokens + 1e-9 < offer.request.get("tokens", 0) or agent.food < offer.request.get("food", 0):
        return False
    gain = _value(sim, offer.offer)
    cost = _value(sim, offer.request)
    if not offer.offer:  # request for help
        reserve = _food_price(sim, agent) * 3
        if agent.tokens - offer.request.get("tokens", 0) < reserve and offer.request.get("tokens", 0) > 0:
            return False
        if offer.request.get("food", 0) and agent.food - offer.request["food"] < 1:
            return False
        willingness = 0.45 * p["generosity"] + 0.35 * p["empathy"] + 0.4 * (trust - 0.5) + 0.1
        if other is not None and other.current_mood == "starving":
            willingness += 0.2 * p["empathy"]
        return rng.random() < willingness
    if trust < 0.3:
        return False
    return gain >= cost * (0.9 - 0.2 * p["agreeableness"])


def _intent(action: str, **kw) -> str:
    texts = {
        "eat": "I'm hungry, so I'll eat.",
        "eat_buy": "I'm hungry; I'll buy a meal.",
        "work": "I need to earn tokens for food.",
        "work_more": "I want to build up savings.",
        "rest": "I'm tired and need to recover energy.",
        "buy_food": "I'll stock up on food while I can afford it.",
        "socialize": "I'd like some company.",
        "create": "I feel like making something.",
        "study": "I want to understand how things work.",
        "explore": "I'm curious about what lies beyond.",
        "reflect": "I want to think about my recent experiences.",
        "reflect_existential": "I keep wondering why I exist and what my purpose is.",
        "help_request": "I can't afford food; I'll ask for help.",
        "steal": "I'm desperate for food.",
        "accept": "This offer works for me.",
        "reject": "I can't accept this right now.",
        "give": "{name} looks like they're struggling; I'll help.",
        "talk": "I want to check in with {name}.",
        "idle": "Waiting for now.",
    }
    return texts[action].format(**kw)


def decide(sim: "Simulation", request: "DecisionRequest", avoid: str | None = None) -> ActionProposal:
    agent = sim.world.agents[request.agent_id]
    rng = sim.streams["policy"]
    cfg = sim.config
    rc, wc = cfg.resources, cfg.work
    p = agent.personality
    price = _food_price(sim, agent)

    def ok(action: str) -> bool:
        spec = REGISTRY.get(action)
        return action != avoid and spec is not None and spec.enabled(cfg)

    # 1. Respond to attended offers addressed to me.
    for offer in request.offers:
        if ok("accept_trade") and _evaluate_offer(sim, agent, offer, rng):
            return ActionProposal(action="accept_trade", target=offer.id, visible_intention=_intent("accept"))
        if ok("reject_trade"):
            return ActionProposal(action="reject_trade", target=offer.id, visible_intention=_intent("reject"))

    work_left = agent.work_capacity - agent.work_ticks_today
    can_work = ok("work") and work_left > 0 and agent.energy > wc.energy_cost_per_tick + 5

    # 2. Survival: hunger.
    if agent.hunger >= 55 or (agent.hunger >= 35 and agent.food > 0):
        if agent.food > 0 and ok("eat"):
            return ActionProposal(action="eat", visible_intention=_intent("eat"))
        if agent.tokens >= price and _food_available(sim) and ok("eat"):
            return ActionProposal(action="eat", visible_intention=_intent("eat_buy"))
        if agent.energy < 20 and ok("rest"):
            return ActionProposal(action="rest", duration=1, visible_intention=_intent("rest"))
        if can_work and agent.hunger < rc.critical_hunger:
            return ActionProposal(action="work", duration=1, visible_intention=_intent("work"))
        known = [sim.world.agents[o] for o in agent.relationships if sim.world.agents[o].alive]
        if cfg.social.allow_theft and ok("steal") and known:
            desperation = agent.hunger / rc.maximum_hunger
            if rng.random() < p["criminal_tendency"] * desperation * (1.2 - p["honesty"]):
                victim = max(known, key=lambda o: (agent.relationships[o.id].trust < 0.5,
                                                   -distance(agent.x, agent.y, o.x, o.y), o.id))
                return ActionProposal(action="steal", target=victim.id, visible_intention=_intent("steal"))
        pending = any(o.from_id == agent.id and o.status == "pending" for o in sim.world.trade_offers.values())
        if known and not pending and ok("offer_trade"):
            friend = max(known, key=lambda o: (agent.relationships[o.id].trust, o.id))
            return ActionProposal(action="offer_trade", target=friend.id,
                                  resource_request={"tokens": round(price, 2)},
                                  visible_intention=_intent("help_request"))
        if can_work:
            return ActionProposal(action="work", duration=1, visible_intention=_intent("work"))

    # 3. Survival: energy.
    if agent.energy < 30 and ok("rest"):
        return ActionProposal(action="rest", duration=3 if agent.energy < 15 else 2, visible_intention=_intent("rest"))

    # 4. Economic security.
    reserve = price * (3 + 3 * p["ambition"])
    if agent.tokens < reserve and can_work:
        return ActionProposal(action="work", duration=min(3, work_left), visible_intention=_intent("work"))
    if agent.food < 2 and agent.tokens > price * 6 and _food_available(sim) and ok("buy_food"):
        return ActionProposal(action="buy_food", quantity=2, visible_intention=_intent("buy_food"))

    # 5. Help a visibly struggling neighbour.
    nearby = sim.agents_within(agent, cfg.world.perception_radius)
    needy = [o for o in nearby if o.current_mood == "starving"]
    if needy and ok("give") and agent.tokens > price * 4:
        if rng.random() < 0.6 * p["generosity"] + 0.4 * p["empathy"] - 0.3:
            target = needy[0]
            return ActionProposal(action="give", target=target.id, resource_offer={"tokens": round(price, 2)},
                                  visible_intention=_intent("give", name=target.name))

    # 6. Free time, weighted by personality and temporary states.
    known_alive = [sim.world.agents[o] for o in agent.relationships if sim.world.agents[o].alive]
    lonely = agent.emotion("loneliness")
    weights: dict[str, float] = {
        "work": (0.15 + 0.6 * p["ambition"]) if can_work else 0.0,
        "socialize": p["sociability"] * (0.2 + lonely) + 0.05,
        "create": 0.6 * p["artistic"],
        "study": 0.45 * p["scientific_curiosity"] + 0.15 * p["curiosity"],
        "explore": 0.3 * p["curiosity"] + 0.2 * p["risk_tolerance"] + 0.3 * agent.emotion("curiosity_activation"),
        "reflect": 0.05 + 0.1 * p["spirituality"] + 0.1 * agent.emotion("stress"),
        "rest": 0.6 * (1 - agent.energy / rc.maximum_energy),
        "talk": 0.25 * p["sociability"] if known_alive and agent.tokens > price * 2 else 0.0,
    }
    if request.existential_active:
        weights["reflect"] += 0.3 + 0.7 * p["spirituality"]
        weights["talk"] += 0.2 * p["sociability"] if weights["talk"] > 0 else 0.0
    for action in list(weights):
        if not ok(action):
            weights[action] = 0.0
    total = sum(weights.values())
    if total <= 0:
        return ActionProposal(action="idle" if avoid != "idle" else "rest", visible_intention=_intent("idle"))
    r = rng.random() * total
    choice = "rest"
    for action, w in weights.items():
        r -= w
        if r <= 0:
            choice = action
            break

    if choice == "work":
        return ActionProposal(action="work", duration=min(2, work_left), visible_intention=_intent("work_more"))
    if choice == "rest":
        return ActionProposal(action="rest", duration=2, visible_intention=_intent("rest"))
    if choice == "socialize":
        near_known = [o for o in nearby if o.id in agent.relationships]
        target = near_known[0].id if near_known else None
        return ActionProposal(action="socialize", target=target, visible_intention=_intent("socialize"))
    if choice == "talk":
        friend = max(known_alive, key=lambda o: (agent.relationships[o.id].familiarity, o.id))
        pool = _EXISTENTIAL_TALK if request.existential_active else _SMALL_TALK
        text = pool[rng.randrange(len(pool))].format(name=friend.name)
        return ActionProposal(action="talk", target=friend.id, message=text,
                              visible_intention=_intent("talk", name=friend.name))
    if choice == "reflect":
        key = "reflect_existential" if request.existential_active else "reflect"
        return ActionProposal(action="reflect", visible_intention=_intent(key))
    if choice in ("create", "study"):
        return ActionProposal(action=choice, duration=2, visible_intention=_intent(choice))
    if choice == "explore":
        return ActionProposal(action="explore", duration=2, visible_intention=_intent("explore"))
    return ActionProposal(action="idle", visible_intention=_intent("idle"))
