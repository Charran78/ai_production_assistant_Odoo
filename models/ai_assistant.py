# -*- coding: utf-8 -*-
import requests
import json
import logging
from odoo import models, fields, api, _
from odoo.exceptions import UserError

from ..services import ContextService, PromptOrchestrator, OllamaService, ResponseParser

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
    
    model_ollama = fields.Char(string='Modelo Ollama', default='llama3.2')
    message_ids = fields.One2many('ai.assistant.message', 'session_id', string='Mensajes')

    def action_ask_ai_async(self, prompt=False, output_style='concise', context_ref=False, model_id=False):
        """ 
        Crea la estructura de mensajes y dispara el cron.
        Acepta parámetros extendidos del wizard.
        """
        self.ensure_one()
        final_prompt = prompt or self.name
        
        # 1. Crear el mensaje de la IA en estado 'pending'
        self.env['ai.assistant.message'].create({
            'session_id': self.id,
            'role': 'assistant',
            'state': 'pending',
            'content': _("<i>Generando respuesta...</i>"),
            'raw_prompt_stored': final_prompt,
            'output_style_stored': output_style,
            'context_ref': context_ref,
            'model_ollama_id': model_id.id if model_id else False
        })
        
        # 2. Intentar ejecutar el cron inmediatamente
        try:
            cron = self.env.ref('ai_production_assistant.ir_cron_process_ai_queue', raise_if_not_found=False)
            if cron:
                cron.with_context(active_test=True).trigger()
        except Exception as e:
            _logger.warning("No se pudo disparar el cron inmediatamente: %s", str(e))

    @api.model
    def perform_ai_action(self, action_data):
        """ 
        Ejecuta una acción técnica sugerida por la IA tras aprobación del usuario.
        MEJORA SEGURIDAD: Verifica permisos y valida campos.
        """
        try:
            model_name = action_data.get('model')
            function = action_data.get('function')
            vals = action_data.get('vals', {})
            
            if not model_name or function not in ['create', 'write', 'update']:
                return {'error': 'Estructura de acción inválida'}

            # SEGURIDAD: Verificar existencia del modelo
            if model_name not in self.env:
                return {'error': f'Modelo {model_name} no existe'}

            # SEGURIDAD: Verificar permisos de creación
            Model = self.env[model_name]
            if not Model.check_access_rights('create', raise_exception=False):
                 return {'error': f'No tienes permisos para crear en {model_name}'}

            if function == 'create':
                # SEGURIDAD: Validar que los campos existan en el modelo
                valid_vals = {}
                for field_name, value in vals.items():
                    if field_name in Model._fields:
                        valid_vals[field_name] = value
                    else:
                        _logger.warning("Campo %s no existe en el modelo %s. Ignorado.", field_name, model_name)
                
                if not valid_vals:
                     return {'error': 'No hay campos válidos para crear el registro'}

                res = Model.create(valid_vals)
                return {'success': True, 'res_id': res.id, 'display_name': res.display_name}
            
            if function in ['write', 'update']:
                # MEJORA: Buscar el ID en vals o usar el último si no viene (simplificado)
                res_id = vals.get('res_id')
                if not res_id:
                    return {'error': 'Se requiere res_id para actualizar'}
                
                record = Model.browse(res_id)
                if not record.exists():
                    return {'error': f'Registro {res_id} no encontrado en {model_name}'}
                
                record.write(vals)
                return {'success': True, 'res_id': record.id, 'display_name': record.display_name}

            return {'error': 'Función no soportada'}
        except Exception as e:
            _logger.error("Error ejecutando acción IA: %s", str(e))
            return {'error': str(e)}


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
    
    # NUEVOS: Almacenar contexto extra y modelo específico
    context_ref = fields.Reference(
        selection='_selection_target_model',
        string="Referencia Contexto"
    )
    model_ollama_id = fields.Many2one('ai.ollama.model', string='Modelo específico')
    
    # NUEVO: Guardar acciones sugeridas para ejecución posterior
    extracted_actions = fields.Text(string="Acciones Extraídas (JSON)")

    def _selection_target_model(self):
        """Selección de modelos para contexto."""
        models = self.env['ir.model'].search([('transient', '=', False)], limit=100)
        return [(model.model, model.name) for model in models]

    @api.model
    def _cron_process_ai_queue(self):
        """ Procesa la cola de mensajes pendientes usando servicios refactorizados. """
        pending_msgs = self.search([('state', '=', 'pending')], limit=5, order='create_date asc')
        
        # Inicializar servicios
        ctx_service = ContextService(self.env)
        orchestrator = PromptOrchestrator(self.env)
        ollama = OllamaService(self.env)
        parser = ResponseParser()

        for msg in pending_msgs:
            try:
                session = msg.session_id
                model_name = session.model_id.model if session.model_id else False

                # 1. Obtener contexto (ahora inyectando el context_ref si existe)
                context_str = ctx_service.get_context(session)
                if msg.context_ref:
                     context_str += f"\n\nCONTEXTO ESPECÍFICO ADICIONAL:\n{msg.context_ref.display_name}"

                # 2. Orquestar prompt (inyectando output_style)
                system_prompt = orchestrator.get_system_prompt(
                    context_str, 
                    model_name=model_name,
                    output_style=msg.output_style_stored
                )
                final_prompt = orchestrator.build_final_prompt(system_prompt, msg.raw_prompt_stored)

                # 3. Llamar a Ollama (usando modelo específico si existe)
                target_model = msg.model_ollama_id.name or session.model_ollama or "llama3.2"
                raw_response = ollama.generate(
                    model=target_model,
                    prompt=final_prompt
                )
                
                # 4. Parsear respuesta (Acciones y HTML)
                clean_text, actions = parser.parse_actions(raw_response)
                formatted_response = parser.format_html(clean_text)
                
                msg.write({
                    'content': formatted_response,
                    'state': 'done' if "Error" not in raw_response else 'error',
                    'extracted_actions': json.dumps(actions) if actions else False
                })

                # NUEVO: Crear acciones pendientes para aprobación humana
                if actions:
                    for act_data in actions:
                        self.env['ai.pending.action'].create({
                            'message_id': msg.id,
                            'model_name': act_data.get('model'),
                            'function': act_data.get('function', 'create'),
                            'vals_json': json.dumps(act_data.get('vals', {}))
                        })

            except Exception as e:
                _logger.error("Error en cron IA: %s", str(e))
                msg.write({'state': 'error', 'content': f"Error crítico: {str(e)}"})
            
            # Commit por cada mensaje procesado
            self.env.cr.commit()