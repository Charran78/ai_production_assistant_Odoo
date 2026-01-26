# -*- coding: utf-8 -*-
import requests
import json
import logging
from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

class AIVectorConfig(models.Model):
    _name = 'ai.vector.config'
    _description = 'Configuración de Base Vectorial (Qdrant)'

    name = fields.Char(string='Nombre', default='Configuración Local', required=True)
    url = fields.Char(string='URL Qdrant', default='http://localhost:6333', required=True)
    collection_name = fields.Char(string='Nombre de Colección', default='odoo_data', required=True)
    api_key = fields.Char(string='API Key (Opcional)')
    active = fields.Boolean(default=True)

class AIAssistantSession(models.Model):
    _name = 'ai.assistant.session'
    _description = 'Sesión de Asistente IA'
    _order = 'create_date desc'

    name = fields.Char(string='Título', default='Nueva Conversación', required=True)
    active = fields.Boolean(default=True, help="Permite archivar la conversación")
    user_id = fields.Many2one('res.users', string='Usuario', default=lambda self: self.env.user)
    
    # Contexto Dinámico
    model_id = fields.Many2one(
        'ir.model', 
        string='Contexto (Modelo)', 
        help="Elige sobre qué datos debe responder la IA",
        domain=[('transient', '=', False)]
    )
    
    # Cambiado a Many2one si tienes un modelo de configuración, 
    # o mantenlo como Char si es texto libre. Aquí lo dejo como Char para evitar errores de relación.
    model_ollama = fields.Char(string='Modelo Ollama', default='llama3.2')
    message_ids = fields.One2many('ai.assistant.message', 'session_id', string='Mensajes')

    def action_ask_ai_async(self):
        """ 
        Crea la estructura de mensajes y dispara el cron.
        """
        self.ensure_one()
        prompt = self.name
        
        # 1. Crear el mensaje de la IA en estado 'pending'
        self.env['ai.assistant.message'].create({
            'session_id': self.id,
            'role': 'assistant',
            'state': 'pending',
            'content': _("<i>Generando respuesta...</i>"),
            'raw_prompt_stored': prompt,
            'output_style_stored': 'concise'
        })
        
        # 2. Intentar ejecutar el cron inmediatamente
        try:
            cron = self.env.ref('ai_production_assistant.ir_cron_process_ai_queue', raise_if_not_found=False)
            if cron:
                cron.with_context(active_test=True).trigger()
        except Exception as e:
            _logger.warning("No se pudo disparar el cron inmediatamente: %s", str(e))

    def _get_dynamic_context(self, model_name=False):
        """ 
        Extrae datos del modelo de forma inteligente.
        Si es mail.message, aplica filtros específicos para "bandeja de entrada".
        """
        model_to_read = model_name or (self.model_id.model if self.model_id else False)
        
        if model_to_read == 'qdrant':
             return self._query_vector_db(self.name) # Usa el título como query por defecto

        if not model_to_read:
            return "No hay contexto específico. Responde de forma general sobre Odoo."

        try:
            domain = []
            if model_to_read == 'mail.message':
                domain = [('message_type', 'in', ['email', 'comment']), ('model', '!=', False)]
            
            records = self.env[model_to_read].search(domain, limit=15, order='id desc')
            if not records:
                return f"El modelo {model_to_read} no tiene datos actuales."

            data_list = []
            for rec in records:
                # Extracción inteligente de campos
                info_parts = [rec.display_name or "ID: %s" % rec.id]
                
                # Campos prioritarios por tipo
                relevant_fields = []
                for fname, field in rec._fields.items():
                    if fname in ['display_name', 'id', 'create_date', 'write_date']: continue
                    if field.type in ['char', 'selection', 'float', 'monetary', 'date', 'datetime', 'text']:
                        val = rec[fname]
                        if val:
                            label = field.string or fname
                            # Truncar textos largos
                            if field.type == 'text' and len(str(val)) > 100:
                                val = str(val)[:100] + "..."
                            relevant_fields.append(f"{label}: {val}")
                
                # Limitar a los 5 campos más relevantes para no saturar el prompt
                info_parts.extend(relevant_fields[:6])
                data_list.append(" | ".join(info_parts))

            return f"Datos actuales de {model_to_read} (Últimos 15):\n- " + "\n- ".join(data_list)
            
        except Exception as e:
            _logger.error("Error leyendo contexto: %s", str(e))
            return f"Error leyendo datos del modelo {model_to_read}."

    def _query_vector_db(self, query):
        """ 
        Placeholder para búsqueda semántica en Qdrant.
        En una fase posterior se integrará qdrant-client.
        """
        config = self.env['ai.vector.config'].search([('active', '=', True)], limit=1)
        if not config:
            return "Qdrant no está configurado. No se puede realizar búsqueda vectorial."
        
        # Simulación de respuesta semántica
        return f"Buscando en Qdrant ({config.collection_name}) para: {query}...\n(Integración vectorial en progreso)"

class AIAssistantMessage(models.Model):
    _name = 'ai.assistant.message'
    _description = 'Mensaje del Asistente'
    _order = 'create_date asc'

    session_id = fields.Many2one('ai.assistant.session', required=True, ondelete='cascade')
    role = fields.Selection([('user', 'Usuario'), ('assistant', 'IA')], required=True)
    content = fields.Html(string='Contenido', sanitize=False)
    state = fields.Selection([
        ('done', 'Procesado'),
        ('pending', 'Pendiente'),
        ('error', 'Error')
    ], default='done', string='Estado')

    raw_prompt_stored = fields.Text(string="Prompt Original")
    output_style_stored = fields.Char(string="Estilo Solicitado", default='concise')

    @api.model
    def _cron_process_ai_queue(self):
        """ Procesa la cola de mensajes pendientes llamando a Ollama """
        pending_msgs = self.search([('state', '=', 'pending')], limit=5, order='create_date asc')
        
        for msg in pending_msgs:
            try:
                # 1. Obtener contexto de la sesión
                context_str = msg.session_id._get_dynamic_context()
                
                system_prompt = f"""Actúa como experto en Odoo.
                Contexto de datos:
                {context_str}
                
                Instrucción: Sé profesional y usa formato HTML simple para la respuesta.
                Si hay datos numéricos, relaciónalos."""

                # 2. Llamada HTTP a Ollama
                payload = {
                    "model": msg.session_id.model_ollama or "llama3.2",
                    "prompt": f"{system_prompt}\n\nPregunta: {msg.raw_prompt_stored}",
                    "stream": False,
                    "options": {"temperature": 0.3}
                }
                
                # Timeout largo para modelos lentos
                res = requests.post("http://localhost:11434/api/generate", json=payload, timeout=120)
                
                if res.status_code == 200:
                    raw_response = res.json().get('response', '')
                    # Formateo básico para Odoo
                    formatted_response = raw_response.replace('\n', '<br/>')
                    
                    msg.write({
                        'content': formatted_response,
                        'state': 'done'
                    })
                else:
                    msg.write({
                        'state': 'error', 
                        'content': f"Error en conexión con Ollama (Status: {res.status_code})"
                    })

            except Exception as e:
                _logger.error(f"Error IA: {str(e)}")
                msg.write({'state': 'error', 'content': f"Error técnico: {str(e)}"})
            
            # Commit por cada mensaje procesado para evitar pérdida de datos
            self.env.cr.commit()