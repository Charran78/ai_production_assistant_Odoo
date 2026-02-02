# -*- coding: utf-8 -*-
from odoo import models, fields, api


class AIPromptWizard(models.TransientModel):
    _name = "ai.prompt.wizard"
    _description = "Ventana emergente para consultas rápidas"

    prompt = fields.Text(string="¿Qué desea consultar?", required=True)

    context_ref = fields.Reference(
        selection="_selection_target_model",
        string="Referencia a Registro",
        help="Opcional: Especifica un Cliente, Orden de Venta, etc., para enfocar la consulta.",
    )

    model_id = fields.Many2one(
        "ai.ollama.model",
        string="Modelo de IA",
        domain=[("active", "=", True)],
        help="Selecciona un modelo especializado del catálogo.",
    )

    @api.model
    def _selection_target_model(self):
        model_records = self.env["ir.model"].search(
            [("transient", "=", False)], limit=100
        )
        return [(model.model, model.name) for model in model_records]

    def action_confirm(self):
        active_id = self.env.context.get("active_id")
        if active_id:
            session = self.env["ai.assistant.session"].browse(active_id)
            session.action_ask_ai_async(
                prompt=self.prompt,
                context_ref=self.context_ref,
                model_id=self.model_id,
            )
        return {"type": "ir.actions.act_window_close"}
