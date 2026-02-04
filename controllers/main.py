# -*- coding: utf-8 -*-
"""
Controller simplificado para el Asistente IA
"""

import json
import logging

from odoo import http, fields
from odoo.http import request, Response

from ..services import AgentCore, get_minimal_context, OllamaService
from ..services.agent_core import parse_create_product_prompt, parse_inventory_prompt
from ..services.sales_purchase_tools import (
    parse_purchase_orders_prompt,
    parse_sale_orders_prompt,
)
from ..services.rag_service import parse_docs_prompt, parse_mail_prompt

_logger = logging.getLogger(__name__)


class AiController(http.Controller):

    @http.route("/ai_assistant/ask", type="http", auth="user", cors="*", csrf=False)
    def ask(self, **kwargs):
        """Endpoint principal para consultas al asistente."""
        try:
            # Soporte para JSON body o parámetros URL
            if request.httprequest.data:
                data = json.loads(request.httprequest.data)
            else:
                data = kwargs

            prompt = data.get("prompt", "").strip()
            model = data.get("model", "").strip()  # Modelo del frontend

            if not prompt:
                return Response(
                    json.dumps({"error": "Prompt vacío"}),
                    status=400,
                    content_type="application/json",
                )

            _logger.info("AI Request: prompt='%s', model='%s'", prompt[:50], model)

        except Exception as e:
            _logger.error("Error parseando request: %s", str(e))
            return Response(
                json.dumps({"error": "Request inválido"}),
                status=400,
                content_type="application/json",
            )

        # Procesar con AgentCore
        try:
            env = request.env

            # 1. Buscar o crear sesión (server-side safety)
            session = env["ai.assistant.session"].search(
                [("user_id", "=", env.user.id), ("active", "=", True)],
                limit=1,
                order="write_date desc",
            )

            if not session:
                session = env["ai.assistant.session"].create(
                    {  # type: ignore
                        "name": f"Chat {fields.Date.today()}",
                        "user_id": env.user.id,
                        "model_ollama": model or "gemma3:4b",
                    }
                )

            # 2. Guardar mensaje del usuario (PERSISTENCIA IMMEDIATA)
            env["ai.assistant.message"].create(
                {  # type: ignore
                    "session_id": session.id,
                    "role": "user",
                    "content": prompt.replace("\n", "<br>"),
                    "state": "done",
                }
            )
            agent = AgentCore(request.env)
            if model:
                ollama = OllamaService(request.env)
                ollama.model = model

            prompt_lower = (prompt or "").lower()
            
            # La auto-aprobación por palabras clave es arriesgada. 
            # Se deshabilita para favorcer el uso de botones en la UI o comandos explícitos.
            auto_approval = False

            pending_msg = env["ai.assistant.message"].search(
                [
                    ("session_id", "=", session.id),
                    ("role", "=", "assistant"),
                    ("pending_action", "!=", False),
                ],
                order="create_date desc",
                limit=1,
            )

            if pending_msg and auto_approval:
                try:
                    action_data = json.loads(pending_msg.pending_action)
                    exec_result = agent.execute_approved_action(action_data)
                    response_content = (
                        exec_result.get("response")
                        or exec_result.get("message")
                        or "Acción ejecutada"
                    )
                    if exec_result.get("error"):
                        response_content = f"❌ {exec_result.get('error')}"
                    pending_msg.write({"pending_action": False})
                    env["ai.assistant.message"].create(
                        {  # type: ignore
                            "session_id": session.id,
                            "role": "assistant",
                            "content": response_content.replace("\n", "<br>"),
                            "state": "done",
                            "expert_name": pending_msg.expert_name or "Assistant",
                        }
                    )
                    result = {
                        "response": response_content,
                        "expert_name": pending_msg.expert_name or "Assistant",
                        "model_used": model or "default",
                    }
                    return Response(json.dumps(result), content_type="application/json")
                except Exception as e:
                    _logger.error("Error ejecutando aprobación directa: %s", str(e))

            # 3. Llamar al Agente con HISTORIAL

            inventory_action = parse_inventory_prompt(prompt)
            if inventory_action:
                response_content = "[search_products] Preparando consulta..."
                action_json = json.dumps(inventory_action)
                message = env["ai.assistant.message"].create(
                    {  # type: ignore
                        "session_id": session.id,
                        "role": "assistant",
                        "content": response_content.replace("\n", "<br>"),
                        "state": "done",
                        "pending_action": action_json,
                        "expert_name": "Assistant",
                    }
                )
                try:
                    auto_result = agent.execute_approved_action(inventory_action)
                    response_content = auto_result.get("response", response_content)
                    message.write(
                        {
                            "content": response_content.replace("\n", "<br>"),
                            "pending_action": False,
                        }
                    )
                except Exception as e:
                    _logger.error("Error en auto-ejecución inventario: %s", str(e))

                result = {
                    "response": response_content,
                    "expert_name": "Assistant",
                    "model_used": model or "default",
                }
                return Response(json.dumps(result), content_type="application/json")

            prompt_lower = (prompt or "").lower()
            production_terms = [
                "orden",
                "órden",
                "ordenes",
                "órdenes",
                "fabricación",
                "fabricacion",
                "mrp",
                "producción",
                "produccion",
            ]
            if any(term in prompt_lower for term in production_terms):
                state = "delayed" if "retras" in prompt_lower else ""
                production_action = {
                    "tool": "search_mrp_orders",
                    "params": {"state": state},
                }
                response_content = "[search_mrp_orders] Preparando consulta..."
                action_json = json.dumps(production_action)
                message = env["ai.assistant.message"].create(
                    {  # type: ignore
                        "session_id": session.id,
                        "role": "assistant",
                        "content": response_content.replace("\n", "<br>"),
                        "state": "done",
                        "pending_action": action_json,
                        "expert_name": "Assistant",
                    }
                )
                try:
                    auto_result = agent.execute_approved_action(production_action)
                    response_content = auto_result.get("response", response_content)
                    message.write(
                        {
                            "content": response_content.replace("\n", "<br>"),
                            "pending_action": False,
                        }
                    )
                except Exception as e:
                    _logger.error("Error en auto-ejecución producción: %s", str(e))

                result = {
                    "response": response_content,
                    "expert_name": "Assistant",
                    "model_used": model or "default",
                }
                return Response(json.dumps(result), content_type="application/json")

            sale_action = parse_sale_orders_prompt(prompt)
            if sale_action:
                response_content = "[search_sale_orders] Preparando consulta..."
                action_json = json.dumps(sale_action)
                message = env["ai.assistant.message"].create(
                    {
                        "session_id": session.id,
                        "role": "assistant",
                        "content": response_content.replace("\n", "<br>"),
                        "state": "done",
                        "pending_action": action_json,
                        "expert_name": "SalesExpert",
                    }
                )
                try:
                    auto_result = agent.execute_approved_action(sale_action)
                    response_content = auto_result.get("response", response_content)
                    message.write(
                        {
                            "content": response_content.replace("\n", "<br>"),
                            "pending_action": False,
                        }
                    )
                except Exception as e:
                    _logger.error("Error en auto-ejecución ventas: %s", str(e))

                return Response(
                    json.dumps({
                        "response": response_content,
                        "expert_name": "SalesExpert",
                        "model_used": model or "default",
                    }),
                    content_type="application/json",
                )

            purchase_action = parse_purchase_orders_prompt(prompt)
            if purchase_action:
                response_content = "[search_purchase_orders] Preparando consulta..."
                action_json = json.dumps(purchase_action)
                message = env["ai.assistant.message"].create(
                    {
                        "session_id": session.id,
                        "role": "assistant",
                        "content": response_content.replace("\n", "<br>"),
                        "state": "done",
                        "pending_action": action_json,
                        "expert_name": "PurchaseExpert",
                    }
                )
                try:
                    auto_result = agent.execute_approved_action(purchase_action)
                    response_content = auto_result.get("response", response_content)
                    message.write(
                        {
                            "content": response_content.replace("\n", "<br>"),
                            "pending_action": False,
                        }
                    )
                except Exception as e:
                    _logger.error("Error en auto-ejecución compras: %s", str(e))

                return Response(
                    json.dumps({
                        "response": response_content,
                        "expert_name": "PurchaseExpert",
                        "model_used": model or "default",
                    }),
                    content_type="application/json",
                )

            docs_action = parse_docs_prompt(prompt)
            if docs_action:
                response_content = "[search_docs] Preparando consulta..."
                action_json = json.dumps(docs_action)
                message = env["ai.assistant.message"].create(
                    {
                        "session_id": session.id,
                        "role": "assistant",
                        "content": response_content.replace("\n", "<br>"),
                        "state": "done",
                        "pending_action": action_json,
                        "expert_name": "DocsExpert",
                    }
                )
                try:
                    auto_result = agent.execute_approved_action(docs_action)
                    response_content = auto_result.get("response", response_content)
                    message.write(
                        {
                            "content": response_content.replace("\n", "<br>"),
                            "pending_action": False,
                        }
                    )
                except Exception as e:
                    _logger.error("Error en auto-ejecución docs: %s", str(e))

                return Response(
                    json.dumps({
                        "response": response_content,
                        "expert_name": "DocsExpert",
                        "model_used": model or "default",
                    }),
                    content_type="application/json",
                )

            mail_action = parse_mail_prompt(prompt)
            if mail_action:
                response_content = "[search_mail] Preparando consulta..."
                action_json = json.dumps(mail_action)
                message = env["ai.assistant.message"].create(
                    {
                        "session_id": session.id,
                        "role": "assistant",
                        "content": response_content.replace("\n", "<br>"),
                        "state": "done",
                        "pending_action": action_json,
                        "expert_name": "MailExpert",
                    }
                )
                try:
                    auto_result = agent.execute_approved_action(mail_action)
                    response_content = auto_result.get("response", response_content)
                    message.write(
                        {
                            "content": response_content.replace("\n", "<br>"),
                            "pending_action": False,
                        }
                    )
                except Exception as e:
                    _logger.error("Error en auto-ejecución correo: %s", str(e))

                return Response(
                    json.dumps({
                        "response": response_content,
                        "expert_name": "MailExpert",
                        "model_used": model or "default",
                    }),
                    content_type="application/json",
                )

            direct_action = parse_create_product_prompt(prompt)
            if direct_action:
                if auto_approval:
                    exec_result = agent.execute_approved_action(direct_action)
                    response_content = (
                        exec_result.get("response")
                        or exec_result.get("message")
                        or "Acción ejecutada"
                    )
                    if exec_result.get("error"):
                        response_content = f"❌ {exec_result.get('error')}"
                    env["ai.assistant.message"].create(
                        {  # type: ignore
                            "session_id": session.id,
                            "role": "assistant",
                            "content": response_content.replace("\n", "<br>"),
                            "state": "done",
                            "expert_name": "Assistant",
                        }
                    )
                    result = {
                        "response": response_content,
                        "expert_name": "Assistant",
                        "model_used": model or "default",
                    }
                    return Response(
                        json.dumps(result), content_type="application/json"
                    )

                response_content = "He preparado esta acción. ¿Deseas proceder?"
                action_json = json.dumps(direct_action)
                env["ai.assistant.message"].create(
                    {  # type: ignore
                        "session_id": session.id,
                        "role": "assistant",
                        "content": response_content.replace("\n", "<br>"),
                        "state": "done",
                        "pending_action": action_json,
                        "expert_name": "Assistant",
                    }
                )
                result = {
                    "response": response_content,
                    "action": direct_action,
                    "expert_name": "Assistant",
                    "model_used": model or "default",
                }
                return Response(json.dumps(result), content_type="application/json")

            context = get_minimal_context(request.env, prompt)

            # Recuperar historial de conversación reciente (memoria a corto plazo)
            last_msgs = env["ai.assistant.message"].search(
                [
                    ("session_id", "=", session.id),
                    ("role", "in", ["user", "assistant"]),
                ],
                order="create_date desc",
                limit=10,
            )  # 5 turnos de diálogo

            history = []
            for msg in reversed(last_msgs):  # Reordenar cronológicamente
                role_label = "Usuario" if msg.role == "user" else "Asistente"
                # Limpiar contenido de posibles JSONs antiguos
                content = msg.content or ""
                if content.strip().startswith("{") and '"tool":' in content:
                    continue  # Omitir mensajes técnicos/tools del historial para no confundir
                history.append(f"{role_label}: {content}")

            # Procesar
            result = agent.process(prompt, context, model=model, history=history)

            # 5. Guardar respuesta del asistente (PERSISTENCIA CHECKPOINT)
            response_content = result.get("response", "")
            action_json = (
                json.dumps(result["action"]) if result.get("action") else False
            )
            expert_name = result.get("expert_name", "Assistant")

            if not response_content:
                if result.get("action"):
                    response_content = "He preparado esta acción. ¿Deseas proceder?"
                else:
                    response_content = "No obtuve respuesta. Intenta nuevamente."

            # Guardar el mensaje inicial con la acción pendiente
            message = env["ai.assistant.message"].create(
                {  # type: ignore
                    "session_id": session.id,
                    "role": "assistant",
                    "content": response_content.replace("\n", "<br>"),
                    "state": "done",
                    "pending_action": action_json,
                    "expert_name": expert_name,
                }
            )

            # EJECUCIÓN AUTOMÁTICA: Si hay una acción pendiente de una herramienta segura, ejecutarla DESPUÉS de guardar
            action_tool = result.get("action", {}).get("tool") if result else None
            if action_tool in ["search_products", "search_mrp_orders"]:
                try:
                    _logger.info(
                        "Ejecutando automáticamente acción: %s",
                        result["action"],
                    )
                    auto_result = agent.execute_approved_action(result["action"])

                    # Actualizar el mensaje con el resultado de la ejecución automática
                    response_content = auto_result.get("response", response_content)
                    message.write(
                        {
                            "content": response_content.replace("\n", "<br>"),
                            "pending_action": False,  # Limpiar la acción pendiente
                        }
                    )

                    _logger.info(
                        "Auto-ejecución completada: %s...",
                        response_content[:100],
                    )
                except Exception as e:
                    _logger.error("Error en auto-ejecución: %s", str(e))
                    # Si falla, mantener el mensigo original con la acción pendiente para ejecución manual

            if auto_approval and action_tool in [
                "create_product",
                "create_mrp_order",
                "adjust_stock",
                "create_bom",
            ]:
                try:
                    _logger.info(
                        "Ejecutando automáticamente acción aprobada: %s",
                        result["action"],
                    )
                    auto_result = agent.execute_approved_action(result["action"])
                    response_content = auto_result.get("response", response_content)
                    message.write(
                        {
                            "content": response_content.replace("\n", "<br>"),
                            "pending_action": False,
                        }
                    )
                    _logger.info(
                        "Auto-ejecución aprobada completada: %s...",
                        response_content[:100],
                    )
                except Exception as e:
                    _logger.error(
                        "Error en auto-ejecución aprobada: %s", str(e)
                    )

            # Añadir info del modelo usado para el frontend
            result["model_used"] = model or "default"

            return Response(json.dumps(result), content_type="application/json")

        except Exception as e:
            _logger.error("Error en AgentCore: %s", str(e))
            return Response(
                json.dumps({"error": str(e)}),
                status=500,
                content_type="application/json",
            )

    @http.route(
        "/ai_assistant/ask_stream", type="http", auth="user", cors="*", csrf=False
    )
    def ask_stream(self, **kwargs):
        """Alias para compatibilidad con frontend existente."""
        return self.ask(**kwargs)

    @http.route(
        "/ai_assistant/execute_action",
        type="jsonrpc",
        auth="user",
        cors="*",
        csrf=False,
    )
    def execute_action(self, **kwargs):
        """Ejecuta una acción aprobada por el usuario."""
        action_data = kwargs.get("action_data")
        message_id = kwargs.get("message_id")

        if not action_data:
            return {"error": "No hay datos de acción"}

        try:
            agent = AgentCore(request.env)
            result = agent.execute_approved_action(action_data)
            response_content = (
                result.get("response") or result.get("message") or "Acción ejecutada"
            )

            if result.get("error"):
                return {"error": result.get("error")}

            if message_id:
                msg = request.env["ai.assistant.message"].browse(int(message_id))
                if msg.exists():
                    msg.write({"pending_action": False})
                    request.env["ai.assistant.message"].create(
                        {  # type: ignore
                            "session_id": msg.session_id.id,
                            "role": "assistant",
                            "content": response_content.replace("\n", "<br>"),
                            "state": "done",
                            "expert_name": msg.expert_name or "Assistant",
                        }
                    )

            return {"response": response_content}

        except Exception as e:
            _logger.error("Error ejecutando acción: %s", str(e))
            return {"error": str(e)}

    @http.route("/ai_assistant/test", type="http", auth="user", cors="*", csrf=False)
    def test(self, **kwargs):
        """Endpoint de prueba para verificar que el servicio funciona."""
        kwargs = kwargs or {}
        ollama = OllamaService(request.env)
        result = ollama.test_connection()

        return Response(json.dumps(result), content_type="application/json")
