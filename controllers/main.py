# -*- coding: utf-8 -*-
import json
import requests
from odoo import http, _
from odoo.http import request, Response

class AiController(http.Controller):

    @http.route('/ai_assistant/ask_stream', type='http', auth='user', cors='*', csrf=False)
    def ask_stream(self, **kwargs):
        """ Endpoint para streaming de respuestas desde Ollama. """
        
        # Leer body JSON (porque fetch envía JSON, no form data)
        try:
            data = json.loads(request.httprequest.data)
            prompt = data.get('prompt', '')
            output_style = data.get('output_style', 'concise')
            model_name = data.get('model', 'llama3.2')
        except:
            prompt = kwargs.get('prompt', '')
            output_style = kwargs.get('output_style', 'concise')
            model_name = kwargs.get('model', 'llama3.2')

        if not prompt:
            return Response("Prompt requerido", status=400)

        # 1. Recuperar contexto de Odoo dinámicamente
        session_obj = request.env['ai.assistant.session']
        # Si no viene un modelo específico, intentamos con mrp.production como default "industrial"
        target_model = data.get('target_model', 'mrp.production')
        context_str = session_obj._get_dynamic_context(model_name=target_model)

        # Estilos
        style_instruction = ""
        if output_style == 'table':
            style_instruction = "FORMATO: Genera ÚNICAMENTE una tabla Markdown. No uses texto introductorio."
        elif output_style == 'report':
            style_instruction = "FORMATO: Genera un informe ejecutivo formal con encabezados."
        elif output_style == 'plan':
            style_instruction = "FORMATO: Genera un Plan de Acción (Checklist) paso a paso."
        else:
            style_instruction = "FORMATO: Sé conciso y directo."

        system_prompt = f"""Eres un asistente experto en producción dentro de Odoo ERP.
        DATOS DE ODOO (Contexto Real):
        {context_str}
        
        INSTRUCCIONES CLAVE:
        1. Responde basándote en los datos proporcionados.
        2. {style_instruction}
        3. Usa formato Markdown.
        """

        # 2. Llamada síncrona a Ollama (Sin Streaming real para evitar problemas TLS/Chunked)
        try:
            payload = {
                "model": model_name,
                "prompt": f"{system_prompt}\n\nPregunta del Usuario: {prompt}\nRespuesta Asistente:",
                "stream": False, 
                "options": {
                    "temperature": 0.3
                }
            }
            
            response = requests.post("http://localhost:11434/api/generate", json=payload, timeout=120)
            if response.status_code == 200:
                result = response.json()
                final_text = result.get('response', '')
                return Response(json.dumps({'response': final_text}), content_type='application/json')
            else:
                return Response(json.dumps({'error': f"Ollama Error: {response.status_code}"}), status=500, content_type='application/json')

        except Exception as e:
            return Response(json.dumps({'error': str(e)}), status=500, content_type='application/json')
