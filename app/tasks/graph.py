"""Navegación del FlowGraph: outcomes del spec → say / task / final."""
from __future__ import annotations

from typing import Any, Optional

from loguru import logger

_MAX_HOPS = 12


def nodes_of(flow: dict[str, Any]) -> dict[str, Any]:
    return (flow.get("flow_graph") or {}).get("nodes") or {}


def has_node(flow: dict[str, Any], node_id: Optional[str]) -> bool:
    return bool(node_id) and node_id in nodes_of(flow)


def edge_for(flow: dict[str, Any], node_id: str, label: str) -> dict[str, Any]:
    node = nodes_of(flow).get(node_id) or {}
    on = node.get("on") or {}
    edge = on.get(label)
    if isinstance(edge, dict):
        return edge
    return {}


def goto_for(flow: dict[str, Any], node_id: str, label: str) -> Optional[str]:
    edge = edge_for(flow, node_id, label)
    goto = edge.get("goto")
    return str(goto) if goto else None


def first_existing(flow: dict[str, Any], candidates: list[str]) -> Optional[str]:
    for cid in candidates:
        if has_node(flow, cid):
            return cid
    return None


def identity_success_goto(flow: dict[str, Any]) -> str:
    goto = goto_for(flow, "task.identity_verification", "Entregado")
    if goto and has_node(flow, goto):
        return goto
    found = first_existing(
        flow,
        [
            "intent.opening",
            "intent.opening_preventiva",
            "intent.opening_vigente",
            "intent.opening_multi",
            "intent.opening_afectado",
        ],
    )
    return found or "intent.opening"


def follow_always(flow: dict[str, Any], node_id: str) -> Optional[str]:
    edge = edge_for(flow, node_id, "always")
    goto = edge.get("goto")
    return str(goto) if goto else None


def negotiation_task_node(flow: dict[str, Any], current: str = "") -> str:
    ns = nodes_of(flow)
    cur = ns.get(current) or {}
    if cur.get("type") == "task" and cur.get("task_type") not in {
        "IdentityVerificationTask",
        None,
        "",
    }:
        return current

    identity_edge = edge_for(flow, "task.identity_verification", "Entregado")
    express = identity_edge.get("express_route_next")
    if isinstance(express, str) and has_node(flow, express):
        return express

    opening = identity_success_goto(flow)
    nxt = opening
    for _ in range(_MAX_HOPS):
        if not nxt or not has_node(flow, nxt):
            break
        node = ns[nxt]
        if node.get("type") == "task" and node.get("task_type") != "IdentityVerificationTask":
            return nxt
        nxt = follow_always(flow, nxt)

    if has_node(flow, "task.negotiation"):
        return "task.negotiation"
    for nid, node in ns.items():
        if node.get("type") == "task" and node.get("task_type") not in {
            "IdentityVerificationTask",
            "FieldVerificationTask",
            "KBATask",
        }:
            return nid
    return "task.negotiation"


def vertical_of(flow: dict[str, Any]) -> str:
    cfg = flow.get("flow_config") or {}
    meta = (flow.get("flow_catalog") or {}).get("meta") or {}
    return str(cfg.get("vertical") or meta.get("vertical") or "sanatorio")


async def advance_graph(
    *,
    flow: dict[str, Any],
    session: Any,
    from_node: str,
    label: str,
    say_node,
    set_phase,
) -> Optional[str]:
    """Avanza por `on[label]`: set_status, say intentions con always, task o final."""
    ns = nodes_of(flow)
    edge = edge_for(flow, from_node, label)
    if not edge:
        logger.warning("no edge node={} label={}", from_node, label)
        return None

    status = edge.get("status")
    if edge.get("action") == "set_status" and status:
        session.final_status = str(status)
    elif status:
        session.final_status = str(status)

    goto = edge.get("goto")
    hops = 0
    last: Optional[str] = None
    while goto and hops < _MAX_HOPS:
        hops += 1
        node_id = str(goto)
        if node_id not in ns:
            logger.warning("goto missing {}", node_id)
            break
        node = ns[node_id]
        ntype = node.get("type")
        last = node_id
        session.current_node_id = node_id

        if ntype == "final":
            await say_node(node_id)
            await set_phase("done")
            return node_id

        if ntype == "task":
            await set_phase(
                "identity" if node.get("task_type") == "IdentityVerificationTask" else "negotiation"
            )
            return node_id

        if ntype == "intention":
            if node.get("prompt") or node.get("prompt_by"):
                await say_node(node_id)
            always = follow_always(flow, node_id)
            if always:
                goto = always
                continue
            # Decision node: el LLM sigue con la task activa.
            return node_id

        break

    return last
