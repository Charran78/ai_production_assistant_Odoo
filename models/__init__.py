# -*- coding: utf-8 -*-
import logging

from . import ai_assistant
from . import ai_ollama_model
from . import ai_pending_action
from . import ai_ollama_config
from . import ai_notification
from . import ai_watchdog

_logger = logging.getLogger(__name__)

try:
    from . import ai_vector_config
except ImportError as exc:
    _logger.warning("ai_vector_config no disponible: %s", exc)
