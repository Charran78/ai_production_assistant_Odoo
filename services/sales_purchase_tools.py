# -*- coding: utf-8 -*-

import re
from datetime import datetime, timedelta


def resolve_date_range(text):
    if not text:
        return None
    lower = text.lower()
    today = datetime.now().date()

    if "hoy" in lower:
        return {"date_from": today.isoformat(), "date_to": today.isoformat()}

    match = re.search(r"(últimos|ultimos)\s+(\d+)\s+d[ií]as", lower)
    if match:
        days = int(match.group(2))
        start = today - timedelta(days=days)
        return {"date_from": start.isoformat(), "date_to": today.isoformat()}

    if "este mes" in lower or "mes actual" in lower:
        start = today.replace(day=1)
        return {"date_from": start.isoformat(), "date_to": today.isoformat()}

    if "trimestre" in lower:
        month = ((today.month - 1) // 3) * 3 + 1
        start = today.replace(month=month, day=1)
        return {"date_from": start.isoformat(), "date_to": today.isoformat()}

    return None


def _extract_partner(text, keyword):
    pattern = rf"{keyword}\s*[:=]?\s*\"([^\"]+)\"|{keyword}\s*[:=]?\s*'([^']+)'|{keyword}\s+([^,;\n]+)"
    match = re.search(pattern, text, flags=re.IGNORECASE)
    if not match:
        return None
    name = match.group(1) or match.group(2) or match.group(3)
    if not name:
        return None
    name = re.sub(
        r"\b(este mes|mes actual|trimestre|hoy|últimos?\s+\d+\s+d[ií]as)\b",
        "",
        name,
        flags=re.IGNORECASE,
    )
    name = name.strip(" .,-;:")
    return name or None


def parse_sale_orders_prompt(prompt):
    if not prompt:
        return None
    text = prompt.strip()
    lower = text.lower()
    keywords = ["venta", "ventas", "pedido de venta", "cotización", "cotizacion"]
    if not any(k in lower for k in keywords):
        return None

    params = {"state": ""}
    date_range = resolve_date_range(lower)
    if date_range:
        params.update(date_range)

    partner = _extract_partner(text, "cliente")
    if partner:
        params["partner_name"] = partner

    if "pendiente" in lower or "pendientes" in lower:
        params["state"] = ["draft", "sent"]
    elif "borrador" in lower or "draft" in lower:
        params["state"] = "draft"
    elif "enviado" in lower or "enviadas" in lower or "sent" in lower:
        params["state"] = "sent"
    elif "confirmad" in lower or "confirmadas" in lower:
        params["state"] = "sale"
    elif "aprob" in lower:
        params["state"] = "sale"
    elif "hecho" in lower or "done" in lower:
        params["state"] = "done"
    elif "cancel" in lower or "cancelad" in lower:
        params["state"] = "cancel"

    return {"tool": "search_sale_orders", "params": params}


def parse_purchase_orders_prompt(prompt):
    if not prompt:
        return None
    text = prompt.strip()
    lower = text.lower()
    keywords = ["compra", "compras", "pedido de compra", "proveedor"]
    if not any(k in lower for k in keywords):
        return None

    params = {"state": ""}
    date_range = resolve_date_range(lower)
    if date_range:
        params.update(date_range)

    partner = _extract_partner(text, "proveedor")
    if partner:
        params["partner_name"] = partner

    if "pendiente" in lower or "pendientes" in lower:
        params["state"] = ["draft", "sent", "to approve"]
    elif "borrador" in lower or "draft" in lower:
        params["state"] = "draft"
    elif "enviado" in lower or "enviadas" in lower or "sent" in lower:
        params["state"] = "sent"
    elif "aprob" in lower or "confirmad" in lower or "confirmadas" in lower:
        params["state"] = "purchase"
    elif "hecho" in lower or "done" in lower or "recibid" in lower:
        params["state"] = "done"
    elif "cancel" in lower or "cancelad" in lower:
        params["state"] = "cancel"

    return {"tool": "search_purchase_orders", "params": params}


def execute_sale_orders(env, params):
    state = params.get("state", "")
    date_from = params.get("date_from")
    date_to = params.get("date_to")
    partner_name = params.get("partner_name")
    domain = []
    if isinstance(state, list):
        domain.append(("state", "in", state))
    elif state:
        domain.append(("state", "=", state))
    if date_from:
        domain.append(("date_order", ">=", date_from))
    if date_to:
        domain.append(("date_order", "<=", date_to))
    if partner_name:
        domain.append(("partner_id", "ilike", partner_name))

    total_amount_group = env["sale.order"].read_group(
        domain, ["amount_total:sum"], []
    )
    total_amount = (
        total_amount_group[0].get("amount_total", 0)
        if total_amount_group
        else 0
    )
    state_groups = env["sale.order"].read_group(domain, ["state"], ["state"])
    state_map = {g["state"]: g.get("__count", 0) for g in state_groups}
    total_count = sum(state_map.values())

    today = datetime.now().date()
    delay_domain = list(domain) + [
        ("commitment_date", "!=", False),
        ("commitment_date", "<", today),
        ("state", "in", ["sale"]),
    ]
    delayed_count = env["sale.order"].search_count(delay_domain)

    delayed_orders = env["sale.order"].search_read(
        delay_domain,
        ["id", "name", "partner_id", "commitment_date", "amount_total"],
        order="commitment_date asc",
        limit=10,
    )

    top_orders = env["sale.order"].search_read(
        domain,
        ["id", "name", "partner_id", "amount_total", "state"],
        order="amount_total desc",
        limit=10,
    )

    lines = [
        "🧾 Ventas: %s pedidos" % total_count,
        "💶 Total importe: %s" % total_amount,
        "⚠️ Retrasadas: %s" % delayed_count,
        "Estados:",
    ]
    for k in ["draft", "sent", "sale", "done", "cancel"]:
        if k in state_map:
            lines.append("• %s: %s" % (k, state_map[k]))
    if top_orders:
        lines.append("Top por importe:")
        for o in top_orders:
            partner = o["partner_id"][1] if o.get("partner_id") else "N/A"
            lines.append(
                "• [%s] %s - %s - %s"
                % (
                    o["id"],
                    o["name"],
                    partner,
                    o.get("amount_total", 0),
                )
            )
    if delayed_orders:
        lines.append("Top por retraso:")
        for o in delayed_orders:
            partner = o["partner_id"][1] if o.get("partner_id") else "N/A"
            lines.append(
                "• [%s] %s - %s - %s"
                % (
                    o["id"],
                    o["name"],
                    partner,
                    o.get("commitment_date"),
                )
            )
    return "\n".join(lines)


def execute_purchase_orders(env, params):
    state = params.get("state", "")
    date_from = params.get("date_from")
    date_to = params.get("date_to")
    partner_name = params.get("partner_name")
    domain = []
    if isinstance(state, list):
        domain.append(("state", "in", state))
    elif state:
        domain.append(("state", "=", state))
    if date_from:
        domain.append(("date_order", ">=", date_from))
    if date_to:
        domain.append(("date_order", "<=", date_to))
    if partner_name:
        domain.append(("partner_id", "ilike", partner_name))

    total_amount_group = env["purchase.order"].read_group(
        domain, ["amount_total:sum"], []
    )
    total_amount = (
        total_amount_group[0].get("amount_total", 0)
        if total_amount_group
        else 0
    )
    state_groups = env["purchase.order"].read_group(
        domain, ["state"], ["state"]
    )
    state_map = {g["state"]: g.get("__count", 0) for g in state_groups}
    total_count = sum(state_map.values())

    today = datetime.now().date()
    delay_domain = list(domain) + [
        ("date_planned", "!=", False),
        ("date_planned", "<", today),
        ("state", "in", ["purchase", "to approve"]),
    ]
    delayed_count = env["purchase.order"].search_count(delay_domain)

    delayed_orders = env["purchase.order"].search_read(
        delay_domain,
        ["id", "name", "partner_id", "date_planned", "amount_total"],
        order="date_planned asc",
        limit=10,
    )

    top_orders = env["purchase.order"].search_read(
        domain,
        ["id", "name", "partner_id", "amount_total", "state"],
        order="amount_total desc",
        limit=10,
    )

    lines = [
        "🧾 Compras: %s pedidos" % total_count,
        "💶 Total importe: %s" % total_amount,
        "⚠️ Retrasadas: %s" % delayed_count,
        "Estados:",
    ]
    for k in ["draft", "sent", "to approve", "purchase", "done", "cancel"]:
        if k in state_map:
            lines.append("• %s: %s" % (k, state_map[k]))
    if top_orders:
        lines.append("Top por importe:")
        for o in top_orders:
            partner = o["partner_id"][1] if o.get("partner_id") else "N/A"
            lines.append(
                "• [%s] %s - %s - %s"
                % (
                    o["id"],
                    o["name"],
                    partner,
                    o.get("amount_total", 0),
                )
            )
    if delayed_orders:
        lines.append("Top por retraso:")
        for o in delayed_orders:
            partner = o["partner_id"][1] if o.get("partner_id") else "N/A"
            lines.append(
                "• [%s] %s - %s - %s"
                % (
                    o["id"],
                    o["name"],
                    partner,
                    o.get("date_planned"),
                )
            )
    return "\n".join(lines)
