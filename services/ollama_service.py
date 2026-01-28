# -*- coding: utf-8 -*-
import requests
import logging
import time

_logger = logging.getLogger(__name__)

class OllamaService:
    """Servicio responsable de TODA la comunicación con Ollama."""
    
    def __init__(self, env):
        self.env = env
        self._base_url = self.env['ir.config_parameter'].sudo().get_param(
            'ai.ollama_url', 'http://localhost:11434'
        )

    def generate(self, model, prompt, system_prompt=None, options=None, retries=3):
        """Llamada a la API de generación de Ollama con política de reintentos."""
        payload = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": options or {"temperature": 0.3}
        }
        
        if system_prompt:
            payload["system"] = system_prompt
        
        url = f"{self._base_url.rstrip('/')}/api/generate"
        
        for attempt in range(retries):
            try:
                _logger.debug("Enviando a Ollama (Intento %s/%s | Modelo: %s): %s", 
                              attempt + 1, retries, model, prompt[:100])
                # Timeout de 600s para modelos pesados (4B+)
                res = requests.post(url, json=payload, timeout=600)
                
                if res.status_code == 200:
                    _logger.debug("Respuesta de Ollama recibida exitosamente")
                    return res.json().get('response', '')
                else:
                    _logger.error("Error en Ollama API. Status: %s, Respuesta: %s", 
                                 res.status_code, res.text[:500])
                    if attempt < retries - 1:
                        time.sleep(1)
                        continue
                    return f"Error en conexión con Ollama (Status: {res.status_code}). Detalles: {res.text[:200]}"
                    
            except requests.exceptions.Timeout:
                _logger.warning("Timeout excedido (600s) en Ollama para modelo %s (Intento %s/%s)", 
                                model, attempt + 1, retries)
                if attempt < retries - 1:
                    time.sleep(1)
                    continue
                return "Error: Tiempo de espera agotado con la IA (modelo cargado o sin memoria)."
            except Exception as e:
                _logger.error("Error técnico llamando a Ollama: %s", str(e), exc_info=True)
                if attempt < retries - 1:
                    time.sleep(1)
                    continue
                return f"Error técnico: {str(e)}"
        
        return "Error: Máximo de reintentos alcanzado."

    def create_custom_model(self, base_model, custom_name, modelfile_content):
        """Crea un modelo personalizado en Ollama usando un Modelfile."""
        if not self._model_exists(base_model):
            return {'success': False, 'error': f'El modelo base {base_model} no existe en Ollama'}
        
        url = f"{self._base_url.rstrip('/')}/api/create"
        payload = {
            "name": custom_name,
            "modelfile": modelfile_content,
            "stream": False
        }
        
        try:
            response = requests.post(url, json=payload, timeout=300)
            if response.status_code == 200:
                # Sincronizar catálogo tras creación
                self.env['ai.ollama.model'].action_sync_models()
                return {'success': True, 'message': f'Modelo {custom_name} creado exitosamente'}
            else:
                return {'success': False, 'error': f'Ollama respondió con error: {response.status_code}'}
        except Exception as e:
            _logger.exception("Error creando modelo personalizado")
            return {'success': False, 'error': str(e)}
    
    def _model_exists(self, model_name):
        """Verifica si un modelo existe en el servidor Ollama."""
        url = f"{self._base_url.rstrip('/')}/api/tags"
        try:
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                models = response.json().get('models', [])
                return any(m.get('name') == model_name or m.get('name') == f"{model_name}:latest" for m in models)
        except:
            return False
        return False
