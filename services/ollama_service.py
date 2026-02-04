# -*- coding: utf-8 -*-
"""
OllamaService - Comunicación simplificada con Ollama
"""

import logging

import requests

_logger = logging.getLogger(__name__)


class OllamaService:
    """Servicio limpio para comunicación con Ollama."""

    def __init__(self, env):
        self.env = env
        self._load_config()

    def _load_config(self):
        """Carga configuración desde Odoo."""
        config = self.env["ai.ollama.config"].search([("active", "=", True)], limit=1)

        if config:
            self.base_url = config.url.rstrip("/")
            self.timeout = max(config.timeout, 30)  # Mínimo 30s
            self.num_ctx = config.num_ctx or 1024  # Por defecto bajo
            self.temperature = config.temperature or 0.7
            self.model = (
                self.env["ir.config_parameter"]
                .sudo()
                .get_param("ai_production_assistant.selected_model", "gemma3:4b")
            )
            self.embedding_model = (
                self.env["ir.config_parameter"]
                .sudo()
                .get_param("ai_production_assistant.embedding_model", "nomic-embed-text")
            )
        else:
            # Defaults si no hay config
            self.base_url = "http://localhost:11434"
            self.timeout = 60
            self.num_ctx = 1024
            self.temperature = 0.7
            self.model = "gemma3:4b"
            self.embedding_model = "nomic-embed-text"

    def generate(self, prompt, model=None, system=None):
        """
        Genera respuesta con Ollama.
        Args:
            prompt: Texto a enviar
            model: Modelo (opcional, usa config por defecto)
            system: System prompt (opcional)
        Returns:
            str: Respuesta del modelo o mensaje de error
        """
        target_model = model or self.model

        payload = {
            "model": target_model,
            "prompt": prompt,
            "stream": False,
            "options": {"num_ctx": self.num_ctx, "temperature": self.temperature},
        }

        if system:
            payload["system"] = system

        url = f"{self.base_url}/api/generate"

        try:
            _logger.debug("Ollama request to %s (model: %s)", url, target_model)

            response = requests.post(url, json=payload, timeout=self.timeout)

            if response.status_code == 200:
                result = response.json().get("response", "")
                _logger.debug("Ollama response: %s", result[:100])
                return result

            # Manejo de errores específicos
            error_text = response.text[:500]

            if "exit status 2" in error_text:
                return f"⚠️ Modelo '{target_model}' corrupto. Prueba: ollama pull {target_model}"

            if "out of memory" in error_text.lower():
                return "⚠️ Sin memoria GPU. Cierra otras apps o usa modelo más pequeño."

            return f"Error Ollama: {response.status_code}"

        except requests.exceptions.Timeout:
            return f"⏱️ Timeout ({self.timeout}s). Aumenta el timeout en configuración."

        except requests.exceptions.ConnectionError:
            return "❌ No puedo conectar con Ollama. ¿Está ejecutándose?"

        except Exception as e:
            _logger.error("Error Ollama: %s", str(e))
            return f"Error: {str(e)}"

    def test_connection(self):
        """Prueba conexión con Ollama."""
        try:
            response = requests.get(f"{self.base_url}/api/tags", timeout=10)
            if response.status_code == 200:
                models = response.json().get("models", [])
                return {"status": "ok", "models": [m.get("name") for m in models]}
            return {"status": "error", "message": f"Status: {response.status_code}"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def embed(self, text, model=None):
        if not text:
            return None
        primary = model or getattr(self, "embedding_model", None) or self.model
        url = f"{self.base_url}/api/embeddings"
        candidates = []
        if primary:
            candidates.append(primary)
        if primary != "all-minilm":
            candidates.append("all-minilm")
        if primary != "nomic-embed-text":
            candidates.append("nomic-embed-text")
        if self.model and self.model not in candidates:
            candidates.append(self.model)
        installed = None
        try:
            tags = requests.get(f"{self.base_url}/api/tags", timeout=10)
            if tags.status_code == 200:
                data = tags.json().get("models", [])
                names = {m.get("name") for m in data if m.get("name")}
                installed = names
        except Exception:
            installed = None
        try:
            for candidate in candidates:
                if installed is not None and candidate not in installed:
                    continue
                r = requests.post(url, json={"model": candidate, "prompt": text}, timeout=self.timeout)
                if r.status_code == 200:
                    return r.json().get("embedding")
            _logger.warning("Ollama embeddings no disponibles. Instale un modelo de embeddings como 'nomic-embed-text' o 'all-minilm'.")
            return None
        except Exception as e:
            _logger.error("Error embeddings: %s", str(e))
            return None
