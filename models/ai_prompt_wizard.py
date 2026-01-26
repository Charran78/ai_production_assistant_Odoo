# -*- coding: utf-8 -*-
from odoo import models, fields, api

class AIPromptWizard(models.TransientModel):
    _name = 'ai.prompt.wizard'
    _description = 'Ventana emergente para consultas rápidas'

    prompt = fields.Text(string="¿Qué desea consultar?", required=True)
    output_style = fields.Selection([
        ('concise', 'Respuesta Rápida'),
        ('table', 'Tabla de Datos'),
        ('report', 'Informe Ejecutivo'),
        ('plan', 'Plan de Acción')
    ], string='Tipo de Respuesta', default='concise', required=True)

    def action_confirm(self):
        """ Este wizard permite una entrada de datos limpia y procesa la respuesta. """
        active_id = self.env.context.get('active_id')
        if active_id:
            session = self.env['ai.assistant.session'].browse(active_id)
            session.action_ask_ai(self.prompt, output_style=self.output_style)
        return {'type': 'ir.actions.act_window_close'}
