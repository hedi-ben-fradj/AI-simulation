"""Social actions: socialising, talking, gifts, trade, refusal and theft.

All transfers are executed atomically by the engine at the moment they happen,
after re-checking that both sides still hold the resources involved. Trust
changes only for agents that took part in or witnessed an interaction.
"""

from __future__ import annotations

from .actions import ActionSpec, distance, register

RESOURCES = ("tokens", "food")


def _clean_bundle(bundle: dict | None) -> dict[str, float]:
    out: dict[str, float] = {}
    for key, value in (bundle or {}).items():
        if key not in RESOURCES:
            continue
        try:
            v = float(value)
        except (TypeError, ValueError):
            continue
        if v > 0:
            out[key] = int(v) if key == "food" else round(v, 3)
    return out


def _has(agent, bundle: dict[str, float]) -> bool:
    return agent.tokens + 1e-9 >= bundle.get("tokens", 0) and agent.food >= bundle.get("food", 0)


def _transfer(giver, receiver, bundle: dict[str, float]) -> None:
    t = bundle.get("tokens", 0)
    f = int(bundle.get("food", 0))
    giver.tokens = round(giver.tokens - t, 4)
    receiver.tokens = round(receiver.tokens + t, 4)
    giver.food -= f
    receiver.food += f


def _describe(bundle: dict[str, float]) -> str:
    if not bundle:
        return "nothing"
    parts = []
    if bundle.get("tokens"):
        parts.append(f"{bundle['tokens']:g} tokens")
    if bundle.get("food"):
        parts.append(f"{int(bundle['food'])} food")
    return " and ".join(parts)


def _value(sim, bundle: dict[str, float]) -> float:
    return bundle.get("tokens", 0) + bundle.get("food", 0) * sim.config.resources.food_price


def _near(sim, a, b) -> bool:
    return distance(a.x, a.y, b.x, b.y) <= sim.config.world.interaction_radius + 1e-6


# --------------------------------------------------------------------------
# socialize / talk
# --------------------------------------------------------------------------

def _tick_socialize(sim, agent, task, time_fraction):
    sc = sim.config.social
    radius = sim.config.world.interaction_radius
    if task.target:
        other = sim.world.agents.get(task.target)
        if other is None or not other.alive:
            return "failed:target_unavailable"
        if not _near(sim, agent, other):
            return "failed:target_out_of_reach"
        partners = [other]
    else:
        partners = [o for o in sim.agents_within(agent, radius)]
    agent.bump_stat("socialize_ticks")
    if not partners:
        sim.adjust_emotion(agent, "loneliness", 0.02)
        return "continue"
    for other in partners:
        for a, b in ((agent, other), (other, agent)):
            sim.adjust_emotion(a, "loneliness", -sc.socialize_loneliness_relief * time_fraction)
            sim.adjust_emotion(a, "happiness", 0.03)
            rel = sim.relationship(a, b)
            rel.familiarity += 1
            rel.affinity = round(min(1.0, rel.affinity + 0.03), 4)
            rel.interactions["socialize"] = rel.interactions.get("socialize", 0) + 1
            rel.last_interaction_tick = sim.world.tick
            sim.trust_evidence(a, b, True, 0.15, "pleasant_interaction")
    names = ", ".join(o.name for o in partners)
    sim.emit("socialize", f"{agent.name} spent time with {names}", agent=agent,
             target=partners[0].id if len(partners) == 1 else None,
             data={"partners": [o.id for o in partners], "intention": task.intention}, importance=0.25)
    lonely = agent.emotion("loneliness")
    sim.record_trait_evidence(agent, "sociability", 1.0, 0.2 * (1 - lonely))
    return "continue"


def _check_talk(sim, agent, proposal, task):
    if not (proposal.message and proposal.message.strip()):
        return "message_required"
    return None


def _tick_talk(sim, agent, task, time_fraction):
    agent.bump_stat("talk_ticks")
    sim.adjust_emotion(agent, "loneliness", -0.05)
    return "done"


# --------------------------------------------------------------------------
# give / help
# --------------------------------------------------------------------------

def _check_give(sim, agent, proposal, task):
    bundle = _clean_bundle(proposal.resource_offer)
    if not bundle:
        return "nothing_offered"
    if not _has(agent, bundle):
        return "insufficient_resources"
    task.params["bundle"] = bundle
    return None


def _tick_give(sim, agent, task, time_fraction):
    other = sim.world.agents.get(task.target)
    bundle = task.params.get("bundle", {})
    if other is None or not other.alive:
        return "failed:target_unavailable"
    if not _near(sim, agent, other):
        return "failed:target_out_of_reach"
    if not _has(agent, bundle):
        return "failed:insufficient_resources"
    need_before = sim.need_pressure(agent)
    _transfer(agent, other, bundle)
    value = _value(sim, bundle)
    what = _describe(bundle)
    agent.bump_stat("gifts_given")
    agent.bump_stat("value_given", value)
    other.bump_stat("gifts_received")
    weight = min(1.0, 0.4 + value / (3 * sim.config.resources.food_price))
    sim.trust_evidence(other, agent, True, weight, "gift_received")
    rel = sim.relationship(other, agent)
    rel.affinity = round(min(1.0, rel.affinity + 0.1), 4)
    rel.interactions["gift_received"] = rel.interactions.get("gift_received", 0) + 1
    sim.relationship(agent, other).interactions["gift_given"] = (
        sim.relationship(agent, other).interactions.get("gift_given", 0) + 1)
    sim.adjust_emotion(agent, "happiness", 0.04)
    sim.adjust_emotion(other, "happiness", 0.06)
    sim.emit("give", f"{agent.name} gave {what} to {other.name}", agent=agent, target=other.id,
             data={"bundle": bundle, "value": value}, importance=0.5)
    sim.remember(other, f"{agent.name} gave me {what}.", kind="event", importance=0.6,
                 related=[agent.id], tags=["gift"])
    sim.remember(agent, f"I gave {what} to {other.name}.", kind="event", importance=0.4,
                 related=[other.id], tags=["gift"])
    # Costly generosity is stronger evidence than giving from surplus.
    sim.record_trait_evidence(agent, "generosity", 1.0, 0.4 + 0.4 * need_before)
    sim.record_trait_evidence(agent, "empathy", 1.0, 0.3)
    return "done"


# --------------------------------------------------------------------------
# trade
# --------------------------------------------------------------------------

def _check_offer(sim, agent, proposal, task):
    offer = _clean_bundle(proposal.resource_offer)
    request = _clean_bundle(proposal.resource_request)
    if not offer and not request:
        return "empty_trade"
    if not _has(agent, offer):
        return "insufficient_resources"
    pending = [o for o in sim.world.trade_offers.values() if o.from_id == agent.id and o.status == "pending"]
    if len(pending) >= 3:
        return "too_many_pending_offers"
    task.params["offer"] = offer
    task.params["request"] = request
    return None


def _tick_offer(sim, agent, task, time_fraction):
    other = sim.world.agents.get(task.target)
    if other is None or not other.alive:
        return "failed:target_unavailable"
    offer = sim.create_trade_offer(agent, other, task.params.get("offer", {}), task.params.get("request", {}),
                                   note=task.intention)
    agent.bump_stat("trade_offers")
    kind = "help request" if not offer.offer else "trade offer"
    sim.emit("trade_offer", f"{agent.name} sent a {kind} to {other.name}: gives {_describe(offer.offer)}, "
             f"wants {_describe(offer.request)}", agent=agent, target=other.id,
             data={"offer_id": offer.id, "offer": offer.offer, "request": offer.request},
             visibility="private", participants=[agent.id, other.id], importance=0.4)
    return "done"


def _resolve_offer(sim, agent, proposal, task):
    offer = sim.world.trade_offers.get(task.target or "")
    if offer is None or offer.to_id != agent.id:
        return None, "invalid_target"
    if offer.status != "pending":
        return None, "offer_not_pending"
    return offer, None


def _check_accept(sim, agent, proposal, task):
    offer, err = _resolve_offer(sim, agent, proposal, task)
    if err:
        return err
    if not _has(agent, offer.request):
        return "insufficient_resources"
    return None


def _tick_accept(sim, agent, task, time_fraction):
    offer = sim.world.trade_offers.get(task.target or "")
    if offer is None or offer.status != "pending":
        return "failed:offer_not_pending"
    proposer = sim.world.agents.get(offer.from_id)
    if proposer is None or not proposer.alive:
        offer.status = "failed"
        return "failed:target_unavailable"
    if not _has(agent, offer.request):
        offer.status = "failed"
        return "failed:insufficient_resources"
    if not _has(proposer, offer.offer):
        # The proposer can no longer honour the offer: evidence of unreliability.
        offer.status = "failed"
        sim.trust_evidence(agent, proposer, False, 0.5, "unreliable_offer")
        sim.emit("trade_failed", f"{proposer.name} could not honour the trade with {agent.name}",
                 agent=proposer, target=agent.id, data={"offer_id": offer.id},
                 visibility="private", participants=[agent.id, proposer.id], importance=0.5)
        sim.remember(agent, f"{proposer.name} offered a trade but could not deliver.", kind="event",
                     importance=0.6, related=[proposer.id], tags=["trade", "unreliable"])
        return "done"
    _transfer(proposer, agent, offer.offer)
    _transfer(agent, proposer, offer.request)
    offer.status = "accepted"
    help_given = not offer.offer
    for a, b in ((agent, proposer), (proposer, agent)):
        sim.trust_evidence(a, b, True, 0.5, "trade_completed")
        rel = sim.relationship(a, b)
        rel.interactions["trade"] = rel.interactions.get("trade", 0) + 1
        rel.affinity = round(min(1.0, rel.affinity + 0.05), 4)
        a.bump_stat("trades_completed")
        sim.record_trait_evidence(a, "agreeableness", 1.0, 0.2)
    if help_given:
        sim.trust_evidence(proposer, agent, True, 0.5, "help_given")
        sim.record_trait_evidence(agent, "generosity", 1.0, 0.4 + 0.4 * sim.need_pressure(agent))
        agent.bump_stat("gifts_given")
    summary = (f"{agent.name} helped {proposer.name} with {_describe(offer.request)}" if help_given else
               f"{agent.name} traded with {proposer.name}: {_describe(offer.request)} for {_describe(offer.offer)}")
    sim.emit("trade", summary, agent=agent, target=proposer.id,
             data={"offer_id": offer.id, "offer": offer.offer, "request": offer.request, "help": help_given},
             importance=0.5)
    sim.remember(agent, summary + ".", kind="event", importance=0.5, related=[proposer.id], tags=["trade"])
    sim.remember(proposer, summary + ".", kind="event", importance=0.5, related=[agent.id], tags=["trade"])
    return "done"


def _check_reject(sim, agent, proposal, task):
    _, err = _resolve_offer(sim, agent, proposal, task)
    return err


def _tick_reject(sim, agent, task, time_fraction):
    offer = sim.world.trade_offers.get(task.target or "")
    if offer is None or offer.status != "pending":
        return "failed:offer_not_pending"
    offer.status = "rejected"
    proposer = sim.world.agents.get(offer.from_id)
    help_request = not offer.offer
    if proposer is not None:
        sim.trust_evidence(proposer, agent, False, 0.2 if help_request else 0.1, "refusal")
        sim.observe(proposer, "refusal", f"{agent.name} turned down my {'request' if help_request else 'offer'}.",
                    related=[agent.id], importance=0.5)
        sim.remember(proposer, f"{agent.name} refused my {'request for help' if help_request else 'trade offer'}.",
                     kind="event", importance=0.4, related=[agent.id], tags=["refusal"])
    if help_request:
        # Refusing from surplus is evidence of low generosity; refusing while needy is not.
        surplus = 1 - sim.need_pressure(agent)
        sim.record_trait_evidence(agent, "generosity", 0.0, 0.3 * surplus)
    agent.bump_stat("refusals")
    sim.emit("trade_rejected", f"{agent.name} refused {offer.from_name}'s "
             f"{'request' if help_request else 'offer'}", agent=agent, target=offer.from_id,
             data={"offer_id": offer.id, "help_request": help_request},
             visibility="private", participants=[agent.id, offer.from_id], importance=0.4)
    return "done"


# --------------------------------------------------------------------------
# theft (conflict)
# --------------------------------------------------------------------------

def _tick_steal(sim, agent, task, time_fraction):
    sc = sim.config.social
    rng = sim.streams["social"]
    victim = sim.world.agents.get(task.target)
    if victim is None or not victim.alive:
        return "failed:target_unavailable"
    if not _near(sim, agent, victim):
        return "failed:target_out_of_reach"
    need = sim.need_pressure(agent)
    success = rng.random() < sc.theft_base_success
    stolen: dict[str, float] = {}
    if success:
        if victim.tokens > 0:
            stolen["tokens"] = round(min(sc.theft_max_tokens, victim.tokens), 3)
        elif victim.food > 0:
            stolen["food"] = 1
        if stolen:
            _transfer(victim, agent, stolen)
        else:
            success = False
    detected = (not success) or rng.random() < sc.theft_detection_probability
    agent.bump_stat("thefts_attempted")
    if success:
        agent.bump_stat("thefts_succeeded")
        victim.bump_stat("times_robbed")
    sim.record_trait_evidence(agent, "criminal_tendency", 1.0, 0.1 + 0.5 * (1 - need))
    sim.record_trait_evidence(agent, "honesty", 0.0, 0.3)
    what = _describe(stolen)
    summary = (f"{agent.name} stole {what} from {victim.name}" if success
               else f"{agent.name} tried to steal from {victim.name} and failed")
    witnesses = [w for w in sim.agents_within(agent, sim.config.world.perception_radius) if w.id != victim.id]
    seen_by = [w for w in witnesses if rng.random() < sc.theft_detection_probability]
    participants = [agent.id] + ([victim.id] if detected else []) + [w.id for w in seen_by]
    sim.emit("theft", summary, agent=agent, target=victim.id,
             data={"success": success, "stolen": stolen, "detected": detected,
                   "witnesses": [w.id for w in seen_by]},
             visibility="private", participants=participants, importance=0.8)
    sim.remember(agent, summary.replace(agent.name, "I", 1) + ".", kind="event", importance=0.6,
                 related=[victim.id], tags=["theft"])
    if detected:
        sim.trust_evidence(victim, agent, False, 1.0, "theft")
        rel = sim.relationship(victim, agent)
        rel.affinity = round(max(-1.0, rel.affinity - 0.3), 4)
        rel.interactions["theft_suffered"] = rel.interactions.get("theft_suffered", 0) + 1
        sim.adjust_emotion(victim, "safety", -0.3)
        sim.adjust_emotion(victim, "frustration", 0.3)
        sim.remember(victim, f"{agent.name} {'stole ' + what + ' from me' if success else 'tried to rob me'}.",
                     kind="event", importance=0.9, related=[agent.id], tags=["theft", "betrayal"])
        sim.record_trait_evidence(victim, "agreeableness", 0.0, 0.2)
    elif success:
        sim.observe(victim, "loss", f"I noticed {what} missing.", importance=0.6)
        sim.adjust_emotion(victim, "safety", -0.1)
    for w in seen_by:
        sim.trust_evidence(w, agent, False, 0.5, "witnessed_theft")
        sim.remember(w, f"I saw {summary}.", kind="event", importance=0.7, related=[agent.id, victim.id],
                     tags=["theft", "witness"])
    return "done"


def register_social_actions() -> None:
    register(ActionSpec(
        "socialize", "Spend time with a nearby agent (target) or at a gathering place. Eases loneliness.",
        _tick_socialize, target_kind="agent", proximity=True, location_fallback="gathering",
        max_duration=2, energy_per_tick=1.0, category="social",
    ))
    register(ActionSpec(
        "talk", "Send a message to an agent anywhere (requires 'message'). Costs tokens by length and distance.",
        _tick_talk, target_kind="agent", target_required=True, requires_message=True, check=_check_talk,
        category="social", enabled=lambda c: c.communication.enabled,
    ))
    register(ActionSpec(
        "give", "Give resources (resource_offer: tokens/food) to a nearby agent.", _tick_give,
        target_kind="agent", target_required=True, proximity=True, check=_check_give, category="social",
    ))
    register(ActionSpec(
        "offer_trade", "Propose an exchange to an agent: resource_offer (what you give) and resource_request "
        "(what you want). An empty offer is a request for help.", _tick_offer, target_kind="agent",
        target_required=True, check=_check_offer, category="social",
    ))
    register(ActionSpec(
        "accept_trade", "Accept a pending trade offer addressed to you (target = offer id).", _tick_accept,
        target_kind="offer", target_required=True, check=_check_accept, category="social",
    ))
    register(ActionSpec(
        "reject_trade", "Decline a pending trade offer or request (target = offer id).", _tick_reject,
        target_kind="offer", target_required=True, check=_check_reject, category="social",
    ))
    register(ActionSpec(
        "steal", "Try to take tokens or food from a nearby agent. May fail, may be seen, damages trust.",
        _tick_steal, target_kind="agent", target_required=True, proximity=True, category="social",
        energy_per_tick=2.0, enabled=lambda c: c.social.allow_theft,
    ))


register_social_actions()
