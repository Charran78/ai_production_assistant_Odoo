# -*- coding: utf-8 -*-
import requests

from odoo import models, fields, api
from odoo.exceptions import ValidationError


class AIVectorConfig(models.Model):
    _name = "ai.vector.config"
    _description = "Configuración de Base Vectorial (Qdrant)"

    name = fields.Char(string="Nombre", default="Configuración Local", required=True)
    url = fields.Char(
        string="URL Qdrant", default="http://localhost:6333", required=True
    )
    collection_name = fields.Char(
        string="Nombre de Colección", default="odoo_documents", required=True
    )
    api_key = fields.Char(string="API Key (Opcional)")
    active = fields.Boolean(string="Activo", default=True)

    @api.model
    def create(self, vals_list):
        if isinstance(vals_list, dict):
            vals_list = [vals_list]

        for vals in vals_list:
            if vals.get("active"):
                self.search([("active", "=", True)]).write({"active": False})
                break

        return super().create(vals_list)

    def write(self, vals):
        if vals.get("active"):
            self.search([("id", "not in", self.ids)]).write({"active": False})
        return super().write(vals)

    def action_test_connection(self):
        self.ensure_one()
        try:
            res = requests.get(f"{self.url.rstrip('/')}/readyz", timeout=5)
            if res.status_code == 200:
                return {
                    "type": "ir.actions.client",
                    "tag": "display_notification",
                    "params": {
                        "title": self.env._("Conexión exitosa"),
                        "message": self.env._(
                            "Qdrant responde correctamente en %s"
                        )
                        % self.url,
                        "type": "success",
                        "sticky": False,
                    },
                }
        except Exception as e:
            raise ValidationError(
                self.env._("Error conectando a Qdrant: %s") % str(e)
            ) from e
        raise ValidationError(self.env._("Qdrant no respondió correctamente."))
