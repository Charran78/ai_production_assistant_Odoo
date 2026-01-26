# -*- coding: utf-8 -*-
import requests
from odoo import models, fields, api, _
from odoo.exceptions import UserError

class AIOllamaModel(models.Model):
    _name = 'ai.ollama.model'
    _description = 'Ollama Model'
    _order = 'name asc'

    name = fields.Char(string='Nombre del Modelo', required=True, index=True)
    size_mb = fields.Float(string='Tamaño (MB)', readonly=True)
    details = fields.Text(string='Detalles Técnicos', readonly=True)
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ('name_uniq', 'unique (name)', 'El nombre del modelo debe ser único.')
    ]

    @api.model
    def action_sync_models(self):
        """ Conecta con Ollama local y sincroniza los modelos disponibles. """
        url = "http://localhost:11434/api/tags"
        try:
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                data = response.json()
                models_data = data.get('models', [])
                
                # Obtener nombres existentes
                existing_models = self.search([])
                existing_names = existing_models.mapped('name')
                
                # Crear o actualizar
                for model in models_data:
                    name = model.get('name')
                    size = model.get('size', 0) / (1024 * 1024) # Convertir a MB
                    details = str(model.get('details', {}))
                    
                    if name in existing_names:
                        # Actualizar existente
                        rec = existing_models.filtered(lambda m: m.name == name)
                        rec.write({'size_mb': size, 'details': details, 'active': True})
                    else:
                        # Crear nuevo
                        self.create({
                            'name': name,
                            'size_mb': size,
                            'details': details
                        })
                
                # Desactivar los que ya no existen (opcional, por seguridad solo desactivamos)
                fetched_names = [m.get('name') for m in models_data]
                to_deactivate = existing_models.filtered(lambda m: m.name not in fetched_names)
                to_deactivate.write({'active': False})

                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Sincronización Completada',
                        'message': f'Se han encontrado {len(models_data)} modelos.',
                        'type': 'success',
                        'sticky': False,
                    }
                }
            else:
                raise UserError(f"Ollama respondió con error: {response.status_code}")
        except requests.exceptions.ConnectionError:
            raise UserError("No se pudo conectar con Ollama. Asegúrate de que está corriendo en localhost:11434")
        except Exception as e:
            raise UserError(f"Error desconocido: {str(e)}")
