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

    # NUEVO: Referencia a registro específico para contexto enfocado
    context_ref = fields.Reference(
        selection='_selection_target_model',
        string="Referencia a Registro",
        help="Opcional: Especifica un Cliente, Orden de Venta, etc., para enfocar la consulta."
    )

    # NUEVO: Selección de modelo específico
    model_id = fields.Many2one(
        'ai.ollama.model',
        string='Modelo de IA',
        domain=[('active', '=', True)],
        help="Selecciona un modelo especializado del catálogo."
    )

    @api.model
    def _selection_target_model(self):
        """Devuelve modelos relevantes para el contexto."""
        models = self.env['ir.model'].search([('transient', '=', False)], limit=100)
        return [(model.model, model.name) for model in models]

    def action_confirm(self):
        """ Envía la consulta a la sesión pasando los nuevos parámetros. """
        active_id = self.env.context.get('active_id')
        if active_id:
            session = self.env['ai.assistant.session'].browse(active_id)
            # Pasamos estilo, contexto extra y modelo específico
            session.action_ask_ai_async(
                prompt=self.prompt, 
                output_style=self.output_style,
                context_ref=self.context_ref,
                model_id=self.model_id
            )
        return {'type': 'ir.actions.act_window_close'}
