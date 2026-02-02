# -*- coding: utf-8 -*-
import json
import logging

from odoo import models, fields, api

_logger = logging.getLogger(__name__)


class AIPendingAction(models.Model):
    _name = "ai.pending.action"
    _description = "Acción de IA Pendiente de Aprobación"
    _order = "create_date desc"

    message_id = fields.Many2one(
        "ai.assistant.message",
        string="Mensaje Origen",
        required=True,
        ondelete="cascade",
    )
    session_id = fields.Many2one(
        "ai.assistant.session", related="message_id.session_id", store=True
    )

    model_name = fields.Char(string="Modelo Objetivo", required=True)
    function = fields.Selection(
        [("create", "Crear"), ("write", "Modificar")],
        string="Operación",
        required=True,
        default="create",
    )

    vals_json = fields.Text(string="Valores Técnicos (JSON)", required=True)

    state = fields.Selection(
        [
            ("pending", "Pendiente"),
            ("approved", "Aprobado"),
            ("rejected", "Rechazado"),
            ("executed", "Ejecutado"),
            ("error", "Error"),
        ],
        default="pending",
        string="Estado",
    )

    execution_result = fields.Text(string="Resultado ejecución")
    display_name_suggested = fields.Char(
        string="Descripción Acción", compute="_compute_display_name_suggested"
    )

    @api.depends("model_name", "function", "vals_json")
    def _compute_display_name_suggested(self):
        for rec in self:
            try:
                vals = json.loads(rec.vals_json)
                action = (
                    rec.env._("Crear")
                    if rec.function == "create"
                    else rec.env._("Actualizar")
                )
                # Intentar sacar nombre del producto o referencia
                name = (
                    vals.get("name")
                    or vals.get("display_name")
                    or vals.get("product_id")
                    or ""
                )
                rec.display_name_suggested = f"{action} {rec.model_name}: {name}"
            except Exception as e:
                _logger.warning(
                    "No se pudo construir display_name_suggested para %s: %s",
                    rec.model_name,
                    str(e),
                )
                rec.display_name_suggested = f"{rec.function} {rec.model_name}"

    def action_approve_and_execute(self):
        """Aprueba y ejecuta la acción usando el método perform_ai_action de la sesión."""
        self.ensure_one()

        try:
            action_data = {
                "model": self.model_name,
                "function": self.function,
                "vals": json.loads(self.vals_json),
            }
            res = self.session_id.perform_ai_action(action_data)

            if res.get("success"):
                self.write(
                    {
                        "state": "executed",
                        "execution_result": f"Éxito: Registro {res.get('res_id')} ({res.get('display_name')})",
                    }
                )
            else:
                self.write(
                    {
                        "state": "error",
                        "execution_result": res.get("error", "Error desconocido"),
                    }
                )
        except Exception as e:
            self.write({"state": "error", "execution_result": str(e)})

    def action_reject(self):
        self.write({"state": "rejected"})
