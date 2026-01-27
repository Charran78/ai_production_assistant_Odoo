# -*- coding: utf-8 -*-
import json
import requests
from odoo import http, _
from odoo.http import request, Response
from ..services import ContextService, PromptOrchestrator, OllamaService

import logging
_logger = logging.getLogger(__name__)

class AiController(http.Controller):

    @http.route('/ai_assistant/ask_stream', type='http', auth='user', cors='*', csrf=False)
    def ask_stream(self, **kwargs):
        """ Endpoint para streaming de respuestas desde Ollama usando la nueva arquitectura de servicios. """
        
        # Leer body JSON
        try:
            data = json.loads(request.httprequest.data)
            prompt = data.get('prompt', '')
            output_style = data.get('output_style', 'concise')
            model_ollama = data.get('model', 'llama3.2')
            target_model = data.get('target_model', 'mrp.production')
        except:
            prompt = kwargs.get('prompt', '')
            output_style = kwargs.get('output_style', 'concise')
            model_ollama = kwargs.get('model', 'llama3.2')
            target_model = kwargs.get('target_model', 'mrp.production')

        if not prompt:
            return Response("Prompt requerido", status=400)

        # 1. Instanciar Servicios
        ctx_service = ContextService(request.env)
        orchestrator = PromptOrchestrator(request.env)
        ollama = OllamaService(request.env)

        # 2. Obtener Contexto
        context_str = ctx_service._get_odoo_context(target_model, prompt)

        # 3. Construir System Prompt
        system_prompt = orchestrator.get_system_prompt(
            context_str, 
            model_name=target_model, 
            output_style=output_style
        )
        final_prompt = orchestrator.build_final_prompt(system_prompt, prompt)

        # 4. Llamar a Ollama (No-Streaming por ahora en este endpoint, pero usando el servicio)
        try:
            _logger.info("AI PROMPT SENT: %s", final_prompt)
            final_text = ollama.generate(model=model_ollama, prompt=final_prompt)
            _logger.info("AI RESPONSE RECEIVED: %s", final_text)
            return Response(json.dumps({'response': final_text}), content_type='application/json')
        except Exception as e:
            return Response(json.dumps({'error': str(e)}), status=500, content_type='application/json')

    @http.route('/ai_assistant/execute_action', type='json', auth='user', cors='*', csrf=False)
    def execute_action(self, **kwargs):
        """ Ejecuta una acción sugerida por la IA tras confirmación del usuario. """
        action_data = kwargs.get('action_data')
        if not action_data:
            return {'error': 'No action data provided'}
        
        # Centralizamos la ejecución en perform_ai_action de la sesión (o creamos una sesión temporal si no existe)
        # Por simplicidad, usamos perform_ai_action de una búsqueda o del entorno
        return request.env['ai.assistant.session'].perform_ai_action(action_data)
