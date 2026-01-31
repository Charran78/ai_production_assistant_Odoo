# -*- coding: utf-8 -*-
"""
Modelos del Asistente IA - Arquitectura limpia
"""
import json
import logging
from odoo import models, fields, api, _

_logger = logging.getLogger(__name__)


class AIAssistantSession(models.Model):
    _name = 'ai.assistant.session'
    _description = 'Sesión de Asistente IA'
    _order = 'create_date desc'

    name = fields.Char(string='Título', default='Nueva Conversación', required=True)
    active = fields.Boolean(default=True)
    user_id = fields.Many2one('res.users', string='Usuario', default=lambda self: self.env.user)
    model_ollama = fields.Char(string='Modelo Ollama', default='gemma3:4b')
    message_ids = fields.One2many('ai.assistant.message', 'session_id', string='Mensajes')

    def action_process_pending(self):
        """Procesa mensajes pendientes de esta sesión."""
        self.ensure_one()
        pending = self.message_ids.filtered(lambda m: m.state == 'pending')
        for msg in pending:
            msg._process_message()


class AIAssistantMessage(models.Model):
    _name = 'ai.assistant.message'
    _description = 'Mensaje del Asistente'
    _order = 'create_date asc'

    session_id = fields.Many2one('ai.assistant.session', required=True, ondelete='cascade')
    role = fields.Selection([
        ('user', 'Usuario'), 
        ('assistant', 'IA')
    ], required=True)
    content = fields.Html(string='Contenido', sanitize=False)
    state = fields.Selection([
        ('done', 'Procesado'),
        ('pending', 'Pendiente'),
        ('error', 'Error')
    ], default='done')
    
    # Para mensajes pendientes
    raw_prompt = fields.Text(string="Prompt Original")
    pending_action = fields.Text(string='Acción Pendiente (JSON)')

    def _process_message(self):
        """Procesa un mensaje pendiente con AgentCore."""
        self.ensure_one()
        
        if self.state != 'pending' or not self.raw_prompt:
            return
        
        try:
            from odoo.addons.ai_production_assistant.services import AgentCore, get_minimal_context
            
            agent = AgentCore(self.env)
            context = get_minimal_context(self.env, self.raw_prompt)
            result = agent.process(self.raw_prompt, context)
            
            response_text = result.get('response', str(result))
            
            # Si hay acción pendiente, guardarla
            if result.get('action'):
                self.pending_action = json.dumps(result['action'])
            
            self.write({
                'content': self._format_html(response_text),
                'state': 'done'
            })
            
        except Exception as e:
            _logger.error("Error procesando mensaje %s: %s", self.id, str(e))
            self.write({
                'content': f"<p>Error: {str(e)}</p>",
                'state': 'error'
            })
    
    def _format_html(self, text):
        """Convierte texto a HTML básico."""
        if not text:
            return "<p>Sin respuesta</p>"
        
        # Convertir saltos de línea a <br>
        html = text.replace('\n', '<br>')
        return f"<p>{html}</p>"

    @api.model
    def _cron_process_ai_queue(self):
        """Cron job para procesar mensajes pendientes."""
        pending = self.search([('state', '=', 'pending')], limit=5)
        for msg in pending:
            try:
                msg._process_message()
            except Exception as e:
                _logger.error("Error en cron para mensaje %s: %s", msg.id, str(e))
                msg.write({'state': 'error', 'content': f"<p>Error: {str(e)}</p>"})
