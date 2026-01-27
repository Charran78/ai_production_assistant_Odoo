# -*- coding: utf-8 -*-
import requests
import json
import logging
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

class AIOllamaModel(models.Model):
    _name = 'ai.ollama.model'
    _description = 'Modelo de Ollama (Catálogo)'
    _order = 'name asc'

    name = fields.Char(string='Nombre en Ollama', required=True, index=True, help="Ej: 'llama3.2' o 'asistente-produccion'")
    is_custom = fields.Boolean(string='Es Personalizado', compute='_compute_is_custom', store=True, help="True si fue creado con 'ollama create'")
    size_mb = fields.Float(string='Tamaño (MB)', readonly=True, digits=(16,2))
    details = fields.Text(string='Detalles Técnicos', readonly=True)
    active = fields.Boolean(default=True)
    
    # Campo CRÍTICO: asociar un Modelfile personalizado
    modelfile = fields.Text(string='Modelfile Personalizado', 
                            help="Contenido del Modelfile para crear una variante especializada. Déjalo vacío para usar el modelo base.")
    custom_model_name = fields.Char(string='Nombre del Modelo Personalizado', 
                                    help="Si se llena, se usará este nombre para crear una variante con el Modelfile. Ej: 'asistente-produccion'")



    @api.depends('name')
    def _compute_is_custom(self):
        """Heurística simple: si no contiene ':' y no es un nombre conocido, probablemente sea custom."""
        known_base_models = {'llama3.2', 'phi3', 'mistral', 'mixtral'}
        for rec in self:
            rec.is_custom = ':' not in rec.name and (rec.name not in known_base_models)

    @api.model
    def action_sync_models(self):
        """Sincroniza modelos desde el servidor Ollama configurado."""
        config = self.env['ir.config_parameter'].sudo()
        ollama_url = config.get_param('ai.ollama_url', 'http://localhost:11434')
        url = f"{ollama_url.rstrip('/')}/api/tags"
        
        _logger.info("Sincronizando modelos desde %s", url)
        
        try:
            response = requests.get(url, timeout=30)
            response.raise_for_status() 
            data = response.json()
            models_data = data.get('models', [])
            
            existing_models = {m.name: m for m in self.search([])}
            fetched_names = set()
            
            for model_info in models_data:
                name = model_info.get('name')
                if not name:
                    continue
                    
                fetched_names.add(name)
                size = model_info.get('size', 0) / (1024 * 1024)  # Bytes a MB
                details = json.dumps(model_info.get('details', {}), indent=2)
                
                if name in existing_models:
                    existing_models[name].write({
                        'size_mb': size,
                        'details': details,
                        'active': True
                    })
                else:
                    self.create({
                        'name': name,
                        'size_mb': size,
                        'details': details
                    })
            
            # Desactivar modelos que ya no están en Ollama
            missing = set(existing_models.keys()) - fetched_names
            for name in missing:
                existing_models[name].write({'active': False})
            
            _logger.info("Sincronización completada. %s modelos encontrados.", len(models_data))
            return {'model_count': len(models_data), 'deactivated': len(missing)}
            
        except requests.exceptions.ConnectionError:
            _logger.error("No se pudo conectar a Ollama en %s", url)
            raise UserError(_("No se pudo conectar con Ollama. Verifica que el servidor esté ejecutándose."))
        except requests.exceptions.Timeout:
            _logger.error("Timeout al conectar con Ollama")
            raise UserError(_("Timeout al conectar con Ollama. El servidor puede estar lento."))
        except Exception as e:
            _logger.exception("Error inesperado sincronizando modelos")
            raise UserError(_("Error sincronizando modelos: %s") % str(e))
