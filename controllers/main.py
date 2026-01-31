# -*- coding: utf-8 -*-
"""
Controller simplificado para el Asistente IA
"""
import json
import logging
from odoo import http, fields
from odoo.http import request, Response

_logger = logging.getLogger(__name__)


class AiController(http.Controller):

    @http.route('/ai_assistant/ask', type='http', auth='user', cors='*', csrf=False)
    def ask(self, **kwargs):
        """Endpoint principal para consultas al asistente."""
        try:
            # Soporte para JSON body o parámetros URL
            if request.httprequest.data:
                data = json.loads(request.httprequest.data)
            else:
                data = kwargs

            prompt = data.get('prompt', '').strip()
            model = data.get('model', '').strip()  # Modelo del frontend
            
            if not prompt:
                return Response(
                    json.dumps({'error': 'Prompt vacío'}), 
                    status=400, 
                    content_type='application/json'
                )

            _logger.info("AI Request: prompt='%s', model='%s'", prompt[:50], model)

        except Exception as e:
            _logger.error("Error parseando request: %s", str(e))
            return Response(
                json.dumps({'error': 'Request inválido'}), 
                status=400, 
                content_type='application/json'
            )

        # Procesar con AgentCore
        try:
            from ..services import AgentCore, get_minimal_context
            from ..services import OllamaService
            
            env = request.env
            
            # 1. Buscar o crear sesión (server-side safety)
            session = env['ai.assistant.session'].search([
                ('user_id', '=', env.user.id), 
                ('active', '=', True)
            ], limit=1, order='write_date desc')
            
            if not session:
                session = env['ai.assistant.session'].create({ # type: ignore
                    'name': f'Chat {fields.Date.today()}',
                    'user_id': env.user.id,
                    'model_ollama': model or 'gemma3:4b'
                })
            
            # 2. Guardar mensaje del usuario (PERSISTENCIA IMMEDIATA)
            env['ai.assistant.message'].create({ # type: ignore
                'session_id': session.id,
                'role': 'user',
                'content': prompt.replace('\n', '<br>'),
                'state': 'done'
            })
            
            # 3. Llamar al Agente con HISTORIAL
            agent = AgentCore(request.env)
            if model:
                ollama = OllamaService(request.env)
                ollama.model = model
            
            # Recuperar contexto RAG
            context = get_minimal_context(request.env, prompt)
            
            # Recuperar historial de conversación reciente (memoria a corto plazo)
            last_msgs = env['ai.assistant.message'].search([
                ('session_id', '=', session.id),
                ('role', 'in', ['user', 'assistant'])
            ], order='create_date desc', limit=10) # 5 turnos de diálogo
            
            history = []
            for msg in reversed(last_msgs): # Reordenar cronológicamente
                role_label = "Usuario" if msg.role == 'user' else "Asistente"
                # Limpiar contenido de posibles JSONs antiguos
                content = msg.content or ""
                if content.strip().startswith('{') and '"tool":' in content:
                    continue # Omitir mensajes técnicos/tools del historial para no confundir
                history.append(f"{role_label}: {content}")
            
            # Procesar
            result = agent.process(prompt, context, model=model, history=history)
            
            # 5. Guardar respuesta del asistente (PERSISTENCIA CHECKPOINT)
            response_content = result.get('response', '')
            action_json = json.dumps(result['action']) if result.get('action') else False
            
            env['ai.assistant.message'].create({ # type: ignore
                'session_id': session.id,
                'role': 'assistant',
                'content': response_content.replace('\n', '<br>'),
                'state': 'done',
                'pending_action': action_json
            })
            
            # Añadir info del modelo usado para el frontend
            result['model_used'] = model or 'default'
            
            return Response(
                json.dumps(result), 
                content_type='application/json'
            )

        except Exception as e:
            _logger.error("Error en AgentCore: %s", str(e))
            return Response(
                json.dumps({'error': str(e)}), 
                status=500, 
                content_type='application/json'
            )

    @http.route('/ai_assistant/ask_stream', type='http', auth='user', cors='*', csrf=False)
    def ask_stream(self, **kwargs):
        """Alias para compatibilidad con frontend existente."""
        return self.ask(**kwargs)

    @http.route('/ai_assistant/execute_action', type='jsonrpc', auth='user', cors='*', csrf=False)
    def execute_action(self, **kwargs):
        """Ejecuta una acción aprobada por el usuario."""
        action_data = kwargs.get('action_data')
        
        if not action_data:
            return {'error': 'No hay datos de acción'}
        
        try:
            from ..services import AgentCore
            
            agent = AgentCore(request.env)
            result = agent.execute_approved_action(action_data)
            return result
            
        except Exception as e:
            _logger.error("Error ejecutando acción: %s", str(e))
            return {'error': str(e)}

    @http.route('/ai_assistant/test', type='http', auth='user', cors='*', csrf=False)
    def test(self, **kwargs):
        """Endpoint de prueba para verificar que el servicio funciona."""
        from ..services import OllamaService
        
        ollama = OllamaService(request.env)
        result = ollama.test_connection()
        
        return Response(
            json.dumps(result), 
            content_type='application/json'
        )