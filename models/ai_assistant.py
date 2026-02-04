# -*- coding: utf-8 -*-
"""
Modelos del Asistente IA - Arquitectura limpia
"""

import json
import logging

from odoo import models, fields, api

from ..services.agent_core import AgentCore, get_minimal_context

_logger = logging.getLogger(__name__)


class AIAssistantSession(models.Model):
    _name = "ai.assistant.session"
    _description = "Sesión de Asistente IA"
    _order = "create_date desc"

    name = fields.Char(string="Título", default="Nueva Conversación", required=True)
    active = fields.Boolean(default=True)
    user_id = fields.Many2one(
        "res.users", string="Usuario", default=lambda self: self.env.user
    )
    model_ollama = fields.Char(string="Modelo Ollama", default="gemma3:4b")
    message_ids = fields.One2many(
        "ai.assistant.message", "session_id", string="Mensajes"
    )

    def action_ask_ai_async(self, prompt, context_ref=None, model_id=None):
        """
        Crea un mensaje del usuario y prepara un mensaje pendiente para el asistente.
        """
        self.ensure_one()
        if context_ref:
            prompt = "%s\nContexto: %s" % (prompt, context_ref.display_name)
        # 1. Crear el mensaje del usuario
        self.env["ai.assistant.message"].create({
            "session_id": self.id,
            "role": "user",
            "content": f"<p>{prompt.replace(chr(10), '<br>')}</p>",
            "state": "done",
        })

        # 2. Crear el mensaje pendiente del asistente
        model_name = model_id.name if model_id else self.model_ollama
        pending_msg = self.env["ai.assistant.message"].create({
            "session_id": self.id,
            "role": "assistant",
            "content": "<p><i>Procesando consulta...</i></p>",
            "state": "pending",
            "raw_prompt": prompt,
            "expert_name": f"Expert ({model_name})",
        })

        # 3. Procesar inmediatamente o dejar para el cron
        # Lo procesamos inmediatamente en este hilo para que el usuario vea respuesta
        pending_msg.process_message()

        return True

    @api.model
    def action_process_pending(self):
        """Procesa mensajes pendientes de esta sesión."""
        self.ensure_one()
        pending = self.message_ids.filtered(lambda m: m.state == "pending")
        for msg in pending:
            msg.process_message()

    @api.model
    def execute_action_payload(self, payload):
        """
        Ejecuta una acción definida en un JSON payload.
        Útil para notificaciones inteligentes.
        """
        if isinstance(payload, str):
            payload = json.loads(payload)

        tool = payload.get("tool")
        params = payload.get("params", {})

        agent = AgentCore(self.env)

        # Validar y ejecutar
        # Por seguridad, solo permitimos ciertas herramientas automáticamente
        safe_tools = [
            "search_products",
            "search_mrp_orders",
            "adjust_stock",
            "create_mrp_order",
            "create_purchase_order",
        ]

        if tool not in safe_tools:
            return {"error": f"Herramienta {tool} no permitida en ejecución automática"}

        result = agent.execute_tool(tool, params)
        return result


class AIAssistantMessage(models.Model):
    _name = "ai.assistant.message"
    _description = "Mensaje del Asistente"
    _order = "create_date asc"

    session_id = fields.Many2one(
        "ai.assistant.session", required=True, ondelete="cascade"
    )
    role = fields.Selection([("user", "Usuario"), ("assistant", "IA")], required=True)
    content = fields.Html(string="Contenido", sanitize=False)
    state = fields.Selection(
        [("done", "Procesado"), ("pending", "Pendiente"), ("error", "Error")],
        default="done",
    )
    # Para mensajes pendientes
    raw_prompt = fields.Text(string="Prompt Original")
    pending_action = fields.Text(string="Acción Pendiente (JSON)")
    expert_name = fields.Char(string="Experto MoE")

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for record in records:
            record._send_bus_notification()
        return records

    def write(self, vals):
        res = super().write(vals)
        if "content" in vals or "state" in vals or "pending_action" in vals:
            for record in self:
                record._send_bus_notification()
        return res

    def _send_bus_notification(self):
        """Envía una notificación al bus de Odoo para actualizar el chat en tiempo real."""
        self.ensure_one()
        try:
            # Canal por usuario
            channel = f"ai.assistant.message.{self.session_id.user_id.id}"
            payload = {
                "type": "new_message",
                "session_id": self.session_id.id,
                "message_id": self.id,
            }
            self.env["bus.bus"]._sendone(channel, "ai_message", payload)
        except Exception as e:
            _logger.error("Error enviando notificación al bus: %s", str(e))

    def process_message(self):
        """Procesa un mensaje pendiente con AgentCore."""
        self.ensure_one()

        if self.state != "pending" or not self.raw_prompt:
            return

        try:
            agent = AgentCore(self.env)
            context = get_minimal_context(self.env, self.raw_prompt)
            result = agent.process(self.raw_prompt, context)

            response_text = result.get("response", str(result))

            # Si hay acción pendiente, guardarla
            if result.get("action"):
                self.pending_action = json.dumps(result["action"])

            self.write({"content": self._format_html(response_text), "state": "done"})

        except Exception as e:
            _logger.error("Error procesando mensaje %s: %s", self.id, str(e))
            self.write({"content": f"<p>Error: {str(e)}</p>", "state": "error"})

    def _format_html(self, text):
        """Convierte texto a HTML básico."""
        if not text:
            return "<p>Sin respuesta</p>"

        # Convertir saltos de línea a <br>
        html = text.replace("\n", "<br>")
        return f"<p>{html}</p>"

    @api.model
    def _cron_process_ai_queue(self):
        """Cron job para procesar mensajes pendientes."""
        pending = self.search([("state", "=", "pending")], limit=5)
        for msg in pending:
            try:
                msg.process_message()
            except Exception as e:
                _logger.error("Error en cron para mensaje %s: %s", msg.id, str(e))
                msg.write({"state": "error", "content": f"<p>Error: {str(e)}</p>"})

    def _process_message(self):
        return self.process_message()
