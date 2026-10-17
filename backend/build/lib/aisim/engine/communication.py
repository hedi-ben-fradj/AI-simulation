"""In-world communication and its costs.

Sending a message costs the sender tokens, time within the tick, energy and a
little attention; reading it costs the receiver energy and attention. These are
*simulated* costs, tracked separately from real API spend.

    token_cost = base_token_cost
               + token_cost_per_message_token * message_tokens
               + distance_cost_per_unit * distance
               + interference_cost * messages_already_sent_this_tick
    time_cost  = base_processing_time + message_tokens / max(bandwidth, minimum_bandwidth)
    sender_energy   = sender_energy_per_token * message_tokens
    receiver_energy = receiver_energy_per_token * message_tokens

Messages are delivered ``delivery_delay_ticks`` later into a bounded inbox.
Each tick an agent processes at most ``max_incoming_messages_processed_per_tick``
messages (and only as many as its attention allows); unread messages wait and
expire after ``message_expiry_ticks``. When the inbox is full the oldest
message is dropped.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .actions import distance
from .state import Agent

CHARS_PER_TOKEN = 4


def estimate_tokens(text: str) -> int:
    return max(1, math.ceil(len(text) / CHARS_PER_TOKEN))


def truncate_to_tokens(text: str, max_tokens: int) -> tuple[str, bool]:
    limit = max_tokens * CHARS_PER_TOKEN
    if len(text) <= limit:
        return text, False
    return text[: max(0, limit - 1)].rstrip() + "…", True


@dataclass
class MessagePlan:
    recipient_id: str
    content: str
    tokens: int
    token_cost: float
    time_cost: float
    sender_energy: float
    attention_cost: float
    truncated: bool


def plan_message(sim, sender: Agent, recipient: Agent, content: str, sent_so_far: int) -> MessagePlan:
    cc = sim.config.communication
    content, truncated = truncate_to_tokens(content.strip(), sim.config.capacity.max_message_tokens)
    tokens = estimate_tokens(content)
    dist = distance(sender.x, sender.y, recipient.x, recipient.y)
    token_cost = (
        cc.base_token_cost
        + cc.token_cost_per_message_token * tokens
        + cc.distance_cost_per_unit * dist
        + cc.interference_cost * (sim.world.messages_this_tick + sent_so_far)
    )
    bandwidth = max(cc.bandwidth_tokens_per_tick, cc.minimum_bandwidth)
    return MessagePlan(
        recipient_id=recipient.id,
        content=content,
        tokens=tokens,
        token_cost=round(token_cost, 5),
        time_cost=round(cc.base_processing_time + tokens / bandwidth, 5),
        sender_energy=round(cc.sender_energy_per_token * tokens, 5),
        attention_cost=sim.config.capacity.message_attention_cost * 0.5,
        truncated=truncated,
    )
