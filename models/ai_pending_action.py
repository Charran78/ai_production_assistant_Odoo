# -*- coding: utf-8 -*-
from odoo import models, fields, api, _

class AIPendingAction(models.Model):
    _name = 'ai.pending.action'
    _description = 'Acción de IA Pendiente de Aprobación'
    _order = 'create_date desc'

    message_id = fields.Many2one('ai.assistant.message', string='Mensaje Origen', required=True, ondelete='cascade')
    session_id = fields.Many2one('ai.assistant.session', related='message_id.session_id', store=True)
    
    model_name = fields.Char(string='Modelo Objetivo', required=True)
    function = fields.Selection([
        ('create', 'Crear'),
        ('write', 'Modificar')
    ], string='Operación', required=True, default='create')
    
    vals_json = fields.Text(string='Valores Técnicos (JSON)', required=True)
    
    state = fields.Selection([
        ('pending', 'Pendiente'),
        ('approved', 'Aprobado'),
        ('rejected', 'Rechazado'),
        ('executed', 'Ejecutado'),
        ('error', 'Error')
    ], default='pending', string='Estado')
    
    execution_result = fields.Text(string='Resultado ejecución')

    def action_approve_and_execute(self):
        """ Aprueba y ejecuta la acción usando el método perform_ai_action de la sesión. """
        self.ensure_one()
        import json
        try:
            action_data = {
                'model': self.model_name,
                'function': self.function,
                'vals': json.loads(self.vals_json)
            }
            res = self.session_id.perform_ai_action(action_data)
            
            if res.get('success'):
                self.write({
                    'state': 'executed',
                    'execution_result': f"Éxito: Registro {res.get('res_id')} ({res.get('display_name')})"
                })
            else:
                self.write({
                    'state': 'error',
                    'execution_result': res.get('error', 'Error desconocido')
                })
        except Exception as e:
            self.write({
                'state': 'error',
                'execution_result': str(e)
            })

    def action_reject(self):
        self.write({'state': 'rejected'})
