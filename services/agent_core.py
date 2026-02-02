# -*- coding: utf-8 -*-
"""
AgentCore - Núcleo del Asistente IA para Odoo
Arquitectura limpia y optimizada para modelos locales (gemma3:4b)
"""

import json
import re
import logging
from datetime import datetime

from .ollama_service import OllamaService
from .moe_router import MoERouter

_logger = logging.getLogger(__name__)


# ============================================================================
# CONFIGURACIÓN DE HERRAMIENTAS
# ============================================================================

TOOLS = {
    "search_products": {
        "description": "Buscar productos por nombre (vacío = listar todos)",
        "params": ["name"],
    },
    "create_product": {
        "description": "Crear un nuevo producto",
        "params": ["name", "price", "cost", "type"],  # valores: consu, product, service
    },
    "search_mrp_orders": {
        "description": "Buscar órdenes de fabricación",
        "params": ["state"],  # draft, confirmed, progress, done, cancel
    },
    "create_mrp_order": {
        "description": "Crear orden de fabricación",
        "params": ["product_id", "quantity"],
    },
    "create_bom": {
        "description": "Crear lista de materiales (BoM) para un producto",
        "params": [
            "product_id",
            "components",
        ],  # components: [{"product_id": X, "qty": Y}, ...]
    },
    "adjust_stock": {
        "description": "Ajustar inventario de un producto",
        "params": ["product_id", "quantity"],
    },
    "message": {"description": "Responder al usuario con texto", "params": ["content"]},
}


# ============================================================================
# SYSTEM PROMPT (CORTO Y EFECTIVO)
# ============================================================================

SYSTEM_PROMPT = """Eres el asistente de operaciones de Odoo.
Fecha y Hora Actual: {date}

HERRAMIENTAS DISPONIBLES:
- search_products: buscar productos (params: name). Ejemplo: {\"tool\": \"search_products\", \"params\": {\"name\": \"mesa\"}}
- create_product: crear producto (params: name, price, cost). Ejemplo: {\"tool\": \"create_product\", \"params\": {\"name\": \"X\", \"price\": 10, \"cost\": 5}}
- create_bom: crear lista de materiales (params: product_id, components). Components es lista de dicts {\"product_id\": ID, \"qty\": N}.
- search_mrp_orders: buscar órdenes de fabricación (params: state). Ejemplo: {\"tool\": \"search_mrp_orders\", \"params\": {\"state\": \"delayed\"}}
- message: responder texto normal.

REGLAS IMPORTANTES:
1. Si te preguntan la hora, responde con la fecha y hora indicadas arriba.
2. Para consultas de búsqueda (search_products, search_mrp_orders), responde SOLO con el JSON de la herramienta.
3. Para acciones de creación, espera confirmación del usuario.
4. Si faltan datos para una herramienta (ej: precio), PREGUNTA al usuario antes de generar el JSON. NO inventes datos.
5. Si el usuario pide crear algo complejo (BoM), primero busca si existen los componentes.
6. Usa el ID numérico de los productos (ej: [12]) para referirte a ellos en las herramientas.
7. CRÍTICO: Usa EXACTAMENTE \"params\" y NUNCA \"parameters\" en el JSON. Si usas \"parameters\", fallará.

{context}"""


def parse_create_product_prompt(prompt):
    if not prompt:
        return None
    text = prompt.strip()
    lower = text.lower()
    if "crear" not in lower and "crea" not in lower:
        return None

    normalized = (
        lower.replace("¿", " ")
        .replace("?", " ")
        .replace("¡", " ")
        .replace("!", " ")
        .replace("“", '"')
        .replace("”", '"')
        .replace("’", "'")
        .replace("‘", "'")
        .replace("=", ":")
    )
    normalized = re.sub(r"\s+", " ", normalized).strip()

    def _extract_quoted_name(source):
        matches = re.findall(r"\"([^\"]+)\"|'([^']+)'", source)
        for m in matches:
            candidate = m[0] or m[1]
            candidate = candidate.strip(" .,-;:")
            if candidate:
                return candidate
        return None

    def _extract_number(keywords):
        pattern = r"(?:" + "|".join(keywords) + r")\s*[:=]?\s*([0-9]+(?:[\.,][0-9]+)?)"
        match = re.search(pattern, normalized)
        if not match:
            return None
        value = match.group(1).replace(",", ".")
        try:
            return float(value)
        except Exception:
            return None

    price = _extract_number(["venta", "precio", "pvp", "importe"])
    cost = _extract_number(["coste", "costo", "cost"])

    if price is None or cost is None:
        return None

    name = None
    name = _extract_quoted_name(text)
    if not name:
        name_match = re.search(
            r"\b(?:nombre|name|producto)\s*[:=]?\s*([^,;]+)",
            normalized,
            flags=re.IGNORECASE,
        )
        if name_match:
            name = name_match.group(1).strip(" .,-;:")

    if not name:
        name_part = re.sub(r"\b(crear|crea|producto|un|una)\b", "", text, flags=re.IGNORECASE).strip()
        split_match = re.split(
            r"\b(venta|precio|pvp|coste|costo|cost|cantidad|tipo)\b",
            name_part,
            flags=re.IGNORECASE,
        )
        name = (
            split_match[0].strip(" ,.-") if split_match else name_part.strip(" ,.-")
        )
    if not name:
        return None

    if any(k in normalized for k in ["alimento", "aliment", "comida", "pan", "pastel"]):
        product_type = "alimento"
    elif any(k in normalized for k in ["servicio", "service"]):
        product_type = "servicio"
    elif any(k in normalized for k in ["producto", "almacenable", "stock"]):
        product_type = "producto"
    else:
        product_type = "consu"

    return {
        "tool": "create_product",
        "params": {"name": name, "price": price, "cost": cost, "type": product_type},
    }


class AgentCore:
    """Núcleo del agente IA - una llamada, una respuesta."""

    def __init__(self, env):
        self.env = env

    def parse_response(self, raw_response):
        return self._parse_response(raw_response)

    def handle_action(self, action, raw_response, tools_config=None):
        return self._handle_action(action, raw_response, tools_config)

    def execute_tool(self, tool, params):
        return self._execute_tool(tool, params)

    def _parse_response(self, raw_response):
        """Intenta extraer JSON de la respuesta del modelo."""
        parsed = None
        _logger.info("Raw response: %s...", raw_response[:200])

        try:

            def _try_parse(candidate):
                try:
                    return json.loads(candidate)
                except Exception:
                    return None

            def _find_json(text):
                blocks = re.findall(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
                for block in blocks:
                    parsed_block = _try_parse(block)
                    if parsed_block is not None:
                        return parsed_block

                starts = [i for i, ch in enumerate(text) if ch in "{["]
                for start in starts:
                    stack = []
                    in_string = False
                    escape = False
                    for i in range(start, len(text)):
                        ch = text[i]
                        if in_string:
                            if escape:
                                escape = False
                            elif ch == "\\":
                                escape = True
                            elif ch == '"':
                                in_string = False
                            continue
                        if ch == '"':
                            in_string = True
                            continue
                        if ch in "{[":
                            stack.append(ch)
                        elif ch in "}]":
                            if not stack:
                                break
                            last = stack[-1]
                            if (last == "{" and ch == "}") or (
                                last == "[" and ch == "]"
                            ):
                                stack.pop()
                                if not stack:
                                    snippet = text[start : i + 1]
                                    parsed_snippet = _try_parse(snippet)
                                    if parsed_snippet is not None:
                                        return parsed_snippet
                                    break
                            else:
                                break
                return None

            parsed = _find_json(raw_response)

        except Exception as e:
            _logger.error("General error parsing response: %s", e)

        if parsed:
            _logger.info("Parsed successfully: %s", parsed)
            # NORMALIZACIÓN
            if isinstance(parsed, dict):
                if (
                    parsed.get("tool") == "message"
                    and "params" in parsed
                    and isinstance(parsed["params"], dict)
                ):
                    if "text" in parsed["params"] and "content" not in parsed["params"]:
                        parsed["params"]["content"] = parsed["params"].pop("text")
                # Caso especial: {"message": "..."}
                if "message" in parsed and "tool" not in parsed:
                    # Limpiar el contenido del mensaje de cualquier resto de JSON o markdown
                    content = parsed["message"]
                    return {"tool": "message", "params": {"content": content}}

                # Si el modelo usó "parameters" en lugar de "params", convertirlo
                if "parameters" in parsed and "params" not in parsed:
                    parsed["params"] = parsed.pop("parameters")
                    _logger.info("Converted 'parameters' to 'params': %s", parsed)

                # También verificar si hay "parameters" dentro de "params" (caso anidado)
                if (
                    "params" in parsed
                    and isinstance(parsed["params"], dict)
                    and "parameters" in parsed["params"]
                ):
                    parsed["params"] = parsed["params"].pop("parameters")
                    _logger.info(
                        "Converted nested 'parameters' to 'params': %s", parsed
                    )

                # Asegurar que tool y params existan
                if "tool" in parsed and "params" in parsed:
                    return parsed

            if (
                isinstance(parsed, list)
                and len(parsed) > 0
                and isinstance(parsed[0], dict)
            ):
                first = parsed[0]
                if (
                    first.get("tool") == "message"
                    and "params" in first
                    and isinstance(first["params"], dict)
                ):
                    if "text" in first["params"] and "content" not in first["params"]:
                        first["params"]["content"] = first["params"].pop("text")
                if "message" in first and "tool" not in first:
                    content = first["message"]
                    return {"tool": "message", "params": {"content": content}}

                # Si el modelo usó "parameters" en lugar de "params", convertirlo
                if "parameters" in first and "params" not in first:
                    first["params"] = first.pop("parameters")
                    _logger.info(
                        "Converted 'parameters' to 'params' in array: %s", first
                    )

                # También verificar si hay "parameters" dentro de "params" (caso anidado)
                if (
                    "params" in first
                    and isinstance(first["params"], dict)
                    and "parameters" in first["params"]
                ):
                    first["params"] = first["params"].pop("parameters")
                    _logger.info(
                        "Converted nested 'parameters' to 'params' in array: %s",
                        first,
                    )

                # Asegurar que tool y params existan
                if "tool" in first and "params" in first:
                    return first

            # Si llegamos aquí, parsed no tiene la estructura esperada
            _logger.warning("Parsed JSON but invalid structure: %s", parsed)

        # Si no hay JSON, asumir que es texto plano (esto soluciona el problema de que hable en JSON)
        # El modelo simplemente respondió texto, así que lo envolvemos nosotros.
        # Limpieza agresiva de bloques de código markdown residuales si no se detectaron como JSON
        clean_response = re.sub(r"^```(?:json)?\s*", "", raw_response).strip()
        clean_response = re.sub(r"\s*```$", "", clean_response).strip()

        _logger.info("Returning as message: %s...", clean_response[:100])
        return {"tool": "message", "params": {"content": clean_response}}

    def process(self, query, context="", model=None, history=None):
        """
        Procesa una consulta del usuario, opcionalmente con historial.
        Args:
            query: Pregunta del usuario
            context: Contexto adicional
            model: Modelo Ollama a usar (opcional)
            history: Lista de strings con historial previo
        Returns: dict con 'response' (texto) o 'action' (para aprobar)
        """
        ollama = OllamaService(self.env)
        router = MoERouter(self.env)

        # 1. Enrutamiento MoE (Mixture of Experts)
        expert_name, system_prompt_template, expert_tools = router.route(query)
        _logger.info("MoE Router: Query='%s' -> Expert='%s'", query, expert_name)

        # Usar modelo especificado o el default
        target_model = model if model else ollama.model

        # Construir prompt
        # Incluir FECHA y HORA
        now = datetime.now()
        ctx_section = f"CONTEXTO RECUPERADO:\n{context}" if context else ""

        # Formatear el System Prompt del experto
        tools_desc = "\n".join([f"- {k}: {v}" for k, v in expert_tools.items()])

        # Construir el prompt final dinámicamente
        system = f"""{system_prompt_template}
Fecha y Hora Actual: {now.strftime('%d/%m/%Y %H:%M')}

HERRAMIENTAS DISPONIBLES:
{tools_desc}

REGLAS GLOBALES - OBLIGATORIAS:
1. Si te preguntan la hora, responde con la fecha y hora indicadas arriba.
2. Para consultas de búsqueda (search_products, search_mrp_orders), responde SOLO con el JSON de la herramienta.
3. Para acciones de creación, espera confirmación del usuario.
4. Si faltan datos para una herramienta (ej: precio), PREGUNTA al usuario antes de generar el JSON. NO inventes datos.
5. Usa el ID numérico de los productos (ej: [12]) para referirte a ellos en las herramientas.

REGLA CRÍTICA - INCUMPLIMIENTO CAUSA ERROR:
6. **USAR EXACTAMENTE ESTA ESTRUCTURA JSON**: {{"tool": "nombre_herramienta", "params": {{"parametro": "valor"}}}}
7. **NUNCA uses "parameters"** - Usa SIEMPRE "params" (sin errores de tipeo)
8. **Verifica tu JSON antes de enviar** - Si tiene "parameters", reemplázalo por "params"

{ctx_section}"""

        # Construir sección de historial
        history_section = ""
        if history:
            history_str = "\n".join(history)
            history_section = f"HISTORIAL CHAT:\n{history_str}\n"  # Se añade al prompt

        full_prompt = (
            f"{system}\n\n{history_section}Usuario: {query}\nRespuesta (JSON o Texto):"
        )

        # Llamar a Ollama con el modelo especificado
        raw_response = ollama.generate(prompt=full_prompt, model=target_model)

        clean_raw = (raw_response or "").strip()
        if (
            not clean_raw
            or clean_raw.startswith("Error")
            or clean_raw.startswith("❌")
            or clean_raw.startswith("⏱️")
        ):
            return {"response": clean_raw or "Error de conexión con Ollama"}

        # Parsear respuesta
        action = self._parse_response(raw_response)

        # Ejecutar acción o devolver respuesta
        # Pasamos expert_tools para que _handle_action sepa qué validar si es necesario
        result = self._handle_action(action, clean_raw, expert_tools)
        result["expert_name"] = expert_name
        return result

    def _handle_action(self, action, raw_response, _tools_config=None):
        """Ejecuta la acción o devuelve respuesta, con validación de parámetros."""
        tool = action.get("tool", "message")
        params = action.get("params", {})

        # Si es mensaje, devolver el contenido limpio SIN JSON
        if tool == "message":
            content = params.get("content", raw_response)
            # Limpieza defensiva de JSON residual en content
            if (
                isinstance(content, str)
                and content.strip().startswith("{")
                and '"tool":' in content
            ):
                try:
                    inner = json.loads(content)
                    if inner.get("tool") == "message":
                        content = inner["params"].get("content", content)
                except Exception as e:
                    _logger.warning("Error limpiando contenido de tool message: %s", e)
            return {"response": content}

        # ACCIONES DE CONSULTA: Marcar como seguras para auto-ejecución
        safe_tools = ["search_products", "search_mrp_orders"]
        if tool in safe_tools:
            # Devolver la acción para que el controlador la ejecute automáticamente
            return {"response": f"[{tool}] Preparando consulta...", "action": action}

        # ACCIONES DE CREACIÓN/MODIFICACIÓN: Requerir aprobación
        return {
            "response": f"[{tool}] He preparado esta acción. ¿Deseas proceder?",
            "action": action,
        }

    def _execute_tool(self, tool, params):
        """Ejecuta una herramienta y devuelve resultado."""

        if tool == "search_products":
            name = params.get("name", "")
            domain = [("name", "ilike", name)] if name else []
            products = self.env["product.product"].search_read(
                domain,
                ["id", "name", "qty_available", "list_price", "standard_price"],
                limit=15,
            )
            if products:
                lines = [f"📦 Encontré {len(products)} productos:"]
                for p in products:
                    stock_info = (
                        f"Stock: {p['qty_available']}"
                        if p["qty_available"]
                        else "Sin stock"
                    )
                    lines.append(
                        f"• [{p['id']}] {p['name']} - {stock_info} - Precio: {p['list_price']}€"
                    )
                return {"response": "\n".join(lines)}
            if name:
                return {"response": f"No encontré productos con '{name}'"}
            return {"response": "No hay productos en el sistema. ¿Quieres crear uno?"}

        if tool == "create_product":
            name = params.get("name")
            price = params.get("price", 0)
            cost = params.get("cost", 0)
            product_type = params.get("type", "consu")
            type_map = {
                "consu": "consu",
                "consumible": "consu",
                "alimento": "consu",
                "alimenticio": "consu",
                "product": "product",
                "producto": "product",
                "almacenable": "product",
                "stock": "product",
                "service": "service",
                "servicio": "service",
            }
            product_type = type_map.get(str(product_type).lower(), "consu")

            if not name:
                return {"response": "❌ Necesito el nombre del producto"}

            # Crear producto
            vals = {
                "name": name,
                "list_price": float(price) if price else 0,
                "standard_price": float(cost) if cost else 0,
                "type": product_type,
                "sale_ok": True,
                "purchase_ok": True,
            }

            try:
                product = self.env["product.product"].create(vals)
                response = (
                    "✅ Producto creado:\n• ID: %s\n• Nombre: %s\n• Precio: %s€\n• Coste: %s€"
                    % (
                        product.id,
                        product.name,
                        product.list_price,
                        product.standard_price,
                    )
                )
                return {
                    "response": response,
                    "created_id": product.id,
                }
            except Exception as e:
                return {"response": f"❌ Error creando producto: {str(e)}"}

        elif tool == "create_bom":
            product_id = params.get("product_id")
            components = params.get("components", [])

            if not product_id:
                return {"response": "❌ Necesito el ID del producto para crear la BoM"}

            if not components:
                return {"response": "❌ Necesito la lista de componentes"}

            try:
                product = self.env["product.product"].browse(int(product_id))
                if not product.exists():
                    return {"response": f"❌ Producto {product_id} no existe"}

                # Crear BoM
                bom_lines = []
                for comp in components:
                    comp_id = comp.get("product_id")
                    qty = comp.get("qty", 1)
                    if comp_id:
                        bom_lines.append(
                            (
                                0,
                                0,
                                {
                                    "product_id": int(comp_id),
                                    "product_qty": float(qty),
                                },
                            )
                        )

                bom = self.env["mrp.bom"].create(
                    {
                        "product_id": product.id,
                        "product_tmpl_id": product.product_tmpl_id.id,
                        "product_qty": 1,
                        "bom_line_ids": bom_lines,
                    }
                )

                response = (
                    "✅ Lista de materiales creada:\n• BoM ID: %s\n• Producto: %s\n"
                    "• Componentes: %s"
                    % (bom.id, product.name, len(bom_lines))
                )
                return {"response": response, "created_id": bom.id}
            except Exception as e:
                return {"response": f"❌ Error creando BoM: {str(e)}"}

        elif tool == "search_mrp_orders":
            state = params.get("state", "")
            domain = []

            if state == "delayed":
                domain = [
                    ("state", "in", ["confirmed", "progress"]),
                    ("date_deadline", "<", datetime.now()),
                ]
            elif state:
                domain = [("state", "=", state)]

            orders = self.env["mrp.production"].search_read(
                domain,
                ["id", "name", "product_id", "product_qty", "state", "date_deadline"],
                limit=10,
            )
            if orders:
                status_label = " retrasadas" if state == "delayed" else ""
                lines = [
                    "🏭 Encontré %s órdenes%s:" % (len(orders), status_label)
                ]
                for o in orders:
                    product_name = o["product_id"][1] if o["product_id"] else "N/A"
                    deadline = o.get("date_deadline") or "Sin fecha"
                    lines.append(
                        "• [%s] %s - %s x%s (%s) - Límite: %s"
                        % (
                            o["id"],
                            o["name"],
                            product_name,
                            o["product_qty"],
                            o["state"],
                            deadline,
                        )
                    )
                return {"response": "\n".join(lines)}
            if state == "delayed":
                return {"response": "✅ No hay órdenes retrasadas."}
            if state:
                return {
                    "response": f"No hay órdenes de fabricación en estado '{state}'"
                }
            return {"response": "No hay órdenes de fabricación en el sistema"}

        elif tool == "create_mrp_order":
            product_id = params.get("product_id")
            quantity = params.get("quantity", 1)

            if not product_id:
                return {
                    "response": "❌ Necesito el ID del producto para crear la orden"
                }

            try:
                product = self.env["product.product"].browse(int(product_id))
                if not product.exists():
                    return {"response": f"❌ Producto {product_id} no existe"}

                # Buscar BoM
                bom = self.env["mrp.bom"].search(
                    [
                        "|",
                        ("product_id", "=", product.id),
                        ("product_tmpl_id", "=", product.product_tmpl_id.id),
                    ],
                    limit=1,
                )

                vals = {
                    "product_id": product.id,
                    "product_qty": float(quantity),
                    "product_uom_id": product.uom_id.id,
                }
                if bom:
                    vals["bom_id"] = bom.id

                mo = self.env["mrp.production"].create(vals)
                response = (
                    "✅ Orden de fabricación creada:\n• %s\n• Producto: %s\n• Cantidad: %s"
                    % (mo.name, product.name, quantity)
                )
                return {"response": response, "created_id": mo.id}
            except Exception as e:
                return {"response": f"❌ Error creando orden: {str(e)}"}

        elif tool == "adjust_stock":
            product_id = params.get("product_id")
            quantity = params.get("quantity")

            if not product_id or quantity is None:
                return {
                    "response": "❌ Necesito product_id y quantity para ajustar stock"
                }

            try:
                product = self.env["product.product"].browse(int(product_id))
                if not product.exists():
                    return {"response": f"❌ Producto {product_id} no existe"}

                # Buscar ubicación principal
                location = self.env["stock.location"].search(
                    [("usage", "=", "internal")], limit=1
                )

                if not location:
                    return {"response": "❌ No hay ubicaciones de almacén configuradas"}

                # Buscar o crear quant
                quant = self.env["stock.quant"].search(
                    [
                        ("product_id", "=", product.id),
                        ("location_id", "=", location.id),
                    ],
                    limit=1,
                )

                if quant:
                    quant.write({"inventory_quantity": float(quantity)})
                    quant.action_apply_inventory()
                else:
                    self.env["stock.quant"].create(
                        {
                            "product_id": product.id,
                            "location_id": location.id,
                            "inventory_quantity": float(quantity),
                        }
                    ).action_apply_inventory()

                return {
                    "response": f"✅ Stock ajustado:\n• Producto: {product.name}\n• Nueva cantidad: {quantity}"
                }
            except Exception as e:
                return {"response": f"❌ Error ajustando stock: {str(e)}"}

        return {"response": f"Herramienta '{tool}' no implementada"}

    def execute_approved_action(self, action_data):
        """Ejecuta una acción previamente aprobada por el usuario."""
        # action_data puede venir como 'type' (legacy) o 'tool' (standard)
        tool_name = action_data.get("tool") or action_data.get("type")
        params = action_data.get("params") or action_data

        try:
            return self._execute_tool(tool_name, params)
        except Exception as e:
            _logger.error("Error ejecutando acción aprobada: %s", str(e))
            return {"error": str(e)}


def get_minimal_context(env, query=""):
    """Obtiene contexto mínimo para el modelo."""
    lines = []

    query_lower = query.lower() if query else ""

    # Detectar intención y obtener datos relevantes
    if any(
        w in query_lower
        for w in ["producto", "productos", "stock", "inventario", "qué hay", "listar"]
    ):
        products = env["product.product"].search_read(
            [], ["id", "name", "qty_available"], limit=5, order="write_date desc"
        )
        if products:
            lines.append("Productos recientes:")
            for p in products:
                lines.append(f"- [{p['id']}] {p['name']}: {p['qty_available']} uds")

    elif any(
        w in query_lower
        for w in ["fabricación", "producción", "orden", "mrp", "retras"]
    ):
        orders = env["mrp.production"].search_read(
            [("state", "in", ["confirmed", "progress"])],
            ["id", "name", "product_id", "state"],
            limit=5,
        )
        if orders:
            lines.append("Órdenes activas:")
            for o in orders:
                prod = o["product_id"][1] if o["product_id"] else "N/A"
                lines.append(f"- [{o['id']}] {o['name']}: {prod} ({o['state']})")

    return "\n".join(lines) if lines else ""
