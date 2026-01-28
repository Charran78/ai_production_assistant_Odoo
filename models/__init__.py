# -*- coding: utf-8 -*-
from . import ai_assistant
from . import ai_prompt_wizard
from . import ai_ollama_model
from . import ai_pending_action
from . import ai_ollama_config

# Importar modelos adicionales si existen
try:
    from . import ai_vector_config
except ImportError:
    pass  # El modelo no existe, continuar sin error