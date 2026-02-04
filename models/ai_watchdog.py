# -*- coding: utf-8 -*-
import logging

from odoo import models, fields, api
from odoo.tools.safe_eval import safe_eval

from ..services.agent_core import AgentCore

_logger = logging.getLogger(__name__)


class AiWatchdog(models.Model):
    _name = "ai.watchdog"
    _description = "Vigilante Proactivo IA"

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    model_id = fields.Many2one(
        "ir.model", string="Modelo a Vigilar", required=True, ondelete="cascade"
    )
    check_type = fields.Selection(
        [
            ("date_delay", "Retraso de Fechas"),
            ("stock_level", "Nivel de Stock"),
            ("custom_domain", "Dominio Personalizado"),
        ],
        required=True,
    )

    domain_filter = fields.Char(string="Filtro Adicional (Dominio)")
    warning_threshold = fields.Integer(string="Umbral (días/cantidad)", default=0)

    last_check = fields.Datetime(string="Última Verificación")

    @api.model
    def _cron_run_watchdogs(self):
        """Ejecuta todos los watchdogs activos."""
        watchdogs = self.search([("active", "=", True)])
        for watchdog in watchdogs:
            try:
                watchdog.run_check()
            except Exception as e:
                _logger.error("Error en watchdog %s: %s", watchdog.name, str(e))

    def run_check(self):
        self._run_check()

    def _run_check(self):
        """Ejecuta la verificación de un watchdog específico."""
        self.ensure_one()
        agent = AgentCore(self.env)

        if self.check_type == "date_delay":
            self._check_delays(agent)
        elif self.check_type == "stock_level":
            self._check_stock(agent)
        elif self.check_type == "custom_domain":
            self._check_custom(agent)

        self.last_check = fields.Datetime.now()

    def _check_delays(self, agent):
        """Verifica retrasos en modelos con fecha límite."""
        model_name = self.model_id.model
        domain = []

        if self.domain_filter:
            try:
                domain += safe_eval(self.domain_filter)
            except Exception as e:
                _logger.warning("Dominio inválido en watchdog %s: %s", self.name, str(e))

        records = self.env[model_name].search(domain)
        delayed = []
        today = fields.Date.today()
        date_fields = ["date_deadline", "commitment_date", "date_planned"]

        for rec in records:
            for field in date_fields:
                if field in rec._fields and rec[field]:
                    date_value = rec[field]
                    if hasattr(date_value, "date"):
                        date_value = date_value.date()
                    if date_value < today:
                        delayed.append(rec)
                    break

        if delayed:
            count = len(delayed)
            names = ", ".join([r.display_name for r in delayed[:3]])
            title = f"⚠️ {count} Retrasos en {self.name}"
            body = f"<p>Se han detectado {count} registros retrasados: <b>{names}</b>...</p>"

            users = self.env["res.users"].search([("share", "=", False)])
            action_payload = self._action_payload_for_model(model_name)
            for user in users:
                agent.create_notification(
                    user.id,
                    title,
                    body,
                    notification_type="warning",
                    action_payload=action_payload,
                )

    def _check_stock(self, agent):
        model_name = self.model_id.model
        domain = []
        if self.domain_filter:
            try:
                domain += safe_eval(self.domain_filter)
            except Exception as e:
                _logger.warning("Dominio inválido en watchdog %s: %s", self.name, str(e))

        records = self.env[model_name].search(domain)
        low_stock = []
        threshold = self.warning_threshold or 0

        for rec in records:
            qty_field = "qty_available" if "qty_available" in rec._fields else None
            if not qty_field and "quantity" in rec._fields:
                qty_field = "quantity"
            if qty_field:
                if rec[qty_field] <= threshold:
                    low_stock.append(rec)

        if low_stock:
            count = len(low_stock)
            names = ", ".join([r.display_name for r in low_stock[:3]])
            title = f"⚠️ Stock crítico en {self.name}"
            body = f"<p>{count} registros con stock ≤ {threshold}: <b>{names}</b>...</p>"
            users = self.env["res.users"].search([("share", "=", False)])
            for user in users:
                agent.create_notification(
                    user.id,
                    title,
                    body,
                    notification_type="warning",
                    action_payload={"tool": "search_products", "params": {"name": ""}},
                )

    def _check_custom(self, agent):
        model_name = self.model_id.model
        domain = []
        if self.domain_filter:
            try:
                domain += safe_eval(self.domain_filter)
            except Exception as e:
                _logger.warning("Dominio inválido en watchdog %s: %s", self.name, str(e))

        records = self.env[model_name].search(domain)
        if records:
            count = len(records)
            names = ", ".join([r.display_name for r in records[:3]])
            title = f"⚠️ Alerta en {self.name}"
            body = f"<p>{count} registros cumplen el dominio: <b>{names}</b>...</p>"
            users = self.env["res.users"].search([("share", "=", False)])
            for user in users:
                agent.create_notification(
                    user.id,
                    title,
                    body,
                    notification_type="warning",
                )

    def _action_payload_for_model(self, model_name):
        if model_name == "mrp.production":
            return {"tool": "search_mrp_orders", "params": {"state": "delayed"}}
        if model_name == "sale.order":
            return {"tool": "search_sale_orders", "params": {"state": "sale"}}
        if model_name == "purchase.order":
            return {"tool": "search_purchase_orders", "params": {"state": "purchase"}}
        if model_name == "product.product":
            return {"tool": "search_products", "params": {"name": ""}}
        return None
