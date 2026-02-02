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

        # Lógica específica por tipo
        if self.check_type == "date_delay":
            self._check_delays(agent)

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

        # Buscar retrasos
        records = self.env[model_name].search(domain)
        delayed = []
        today = fields.Date.today()

        for rec in records:
            if (
                "date_deadline" in rec
                and rec.date_deadline
                and rec.date_deadline < today
            ):
                delayed.append(rec)

        if delayed:
            count = len(delayed)
            names = ", ".join([r.display_name for r in delayed[:3]])
            title = f"⚠️ {count} Retrasos en {self.name}"
            body = f"<p>Se han detectado {count} registros retrasados: <b>{names}</b>...</p>"

            # Notificar a todos los usuarios internos (o mejora: configurar a quién)
            users = self.env["res.users"].search([("share", "=", False)])
            for user in users:
                agent.create_notification(
                    user.id,
                    title,
                    body,
                    notification_type="warning",
                    action_payload={
                        "tool": "search_mrp_orders",
                        "params": {"state": "confirmed"},
                    },  # Ejemplo genérico
                )
