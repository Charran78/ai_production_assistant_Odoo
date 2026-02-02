# -*- coding: utf-8 -*-
from odoo import models, fields


class AiNotification(models.Model):
    _name = "ai.notification"
    _description = "Notificación del Asistente IA"
    _order = "create_date desc"

    name = fields.Char(string="Título", required=True)
    body = fields.Html(string="Contenido", sanitize=False)
    notification_type = fields.Selection(
        [
            ("info", "Información"),
            ("warning", "Advertencia"),
            ("error", "Error"),
            ("action", "Acción Requerida"),
        ],
        default="info",
        string="Tipo",
    )

    action_payload = fields.Text(
        string="Payload de Acción (JSON)",
        help="JSON para ejecutar acción al hacer click",
    )

    is_read = fields.Boolean(default=False, string="Leído")
    is_dismissed = fields.Boolean(default=False, string="Descartado")

    user_id = fields.Many2one(
        "res.users", string="Usuario", default=lambda self: self.env.user, required=True
    )

    def action_mark_read(self):
        self.write({"is_read": True})

    def action_dismiss(self):
        self.write({"is_dismissed": True})
