# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import ValidationError

class AIVectorConfig(models.Model):
    _name = 'ai.vector.config'
    _description = 'Configuración de Base Vectorial (Qdrant)'

    name = fields.Char(string='Nombre', default='Configuración Local', required=True)
    url = fields.Char(string='URL Qdrant', default='http://localhost:6333', required=True)
    collection_name = fields.Char(string='Nombre de Colección', default='odoo_documents', required=True)
    api_key = fields.Char(string='API Key (Opcional)')
    active = fields.Boolean(string='Activo', default=True)

    @api.model
    def create(self, vals_list):
        if isinstance(vals_list, dict):
            vals_list = [vals_list]
        
        for vals in vals_list:
            if vals.get('active'):
                self.search([]).write({'active': False})
                break
        
        return super(AIVectorConfig, self).create(vals_list)

    def write(self, vals):
        if vals.get('active'):
            self.search([('id', 'not in', self.ids)]).write({'active': False})
        return super(AIVectorConfig, self).write(vals)

    def action_test_connection(self):
        self.ensure_one()
        try:
            import requests
            res = requests.get(f"{self.url.rstrip('/')}/readyz", timeout=5)
            if res.status_code == 200:
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Conexión exitosa',
                        'message': f'Qdrant responde correctamente en {self.url}',
                        'type': 'success',
                        'sticky': False,
                    }
                }
        except Exception as e:
            raise ValidationError(f'Error conectando a Qdrant: {str(e)}')
        raise ValidationError('Qdrant no respondió correctamente.')

