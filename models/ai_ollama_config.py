# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import ValidationError

class AIOllamaConfig(models.Model):
    _name = 'ai.ollama.config'
    _description = 'Configuración del servidor Ollama'
    
    name = fields.Char(string='Nombre', default='Servidor Local', required=True)
    url = fields.Char(string='URL de Ollama', default='http://localhost:11434', required=True)
    timeout = fields.Integer(string='Timeout (segundos)', default=30)
    active = fields.Boolean(string='Activo', default=True)
    
    @api.model
    def create(self, vals):
        # Si ya hay una configuración activa, desactivarla
        if vals.get('active'):
            self.search([]).write({'active': False})
        return super(AIOllamaConfig, self).create(vals)
    
    def write(self, vals):
        # Si se está activando una configuración, desactivar las demás
        if vals.get('active'):
            self.search([('id', 'not in', self.ids)]).write({'active': False})
        return super(AIOllamaConfig, self).write(vals)
    
    def action_test_connection(self):
        """Prueba la conexión con el servidor Ollama."""
        self.ensure_one()
        try:
            import requests
            response = requests.get(f"{self.url.rstrip('/')}/api/tags", timeout=self.timeout)
            response.raise_for_status()
            
            # Si la conexión es exitosa, devolver una notificación
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Conexión exitosa',
                    'message': f'Conexión establecida con Ollama en {self.url}',
                    'type': 'success',
                    'sticky': False,
                }
            }
        except Exception as e:
            raise ValidationError(f'Error conectando a Ollama: {str(e)}')