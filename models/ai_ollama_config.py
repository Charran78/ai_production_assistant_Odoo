# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import ValidationError

class AIOllamaConfig(models.Model):
    _name = 'ai.ollama.config'
    _description = 'Configuración del servidor Ollama'
    
    name = fields.Char(string='Nombre', default='Servidor Local', required=True)
    url = fields.Char(string='URL de Ollama', default='http://localhost:11434', required=True)
    timeout = fields.Integer(string='Timeout (segundos)', default=120)
    
    # Parámetros de Rendimiento
    num_ctx = fields.Integer(string='Ventana de Contexto', default=2048, 
                           help="Tamaño de la memoria de conversación. Reducir a 1024 o 512 mejora drásticamente la velocidad en hardware modesto.")
    temperature = fields.Float(string='Creatividad (Temperatura)', default=0.7, 
                             help="Valor entre 0 y 1. Menor es más preciso, mayor es más creativo.")
    
    active = fields.Boolean(string='Activo', default=True)
    
    @api.model
    def create(self, vals_list):
        # Si ya hay una configuración activa, desactivarla
        if isinstance(vals_list, dict):
            vals_list = [vals_list]
        
        for vals in vals_list:
            if vals.get('active'):
                self.search([]).write({'active': False})
                break
        
        return super(AIOllamaConfig, self).create(vals_list)
    
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