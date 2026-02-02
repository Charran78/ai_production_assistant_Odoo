# -*- coding: utf-8 -*-
import logging

from . import models
from . import controllers
from . import services
from . import wizards

_logger = logging.getLogger(__name__)


def _create_default_data(env):
    """
    Hook de post-inicialización llamado automáticamente por Odoo.
    Se ejecuta después de instalar o actualizar el módulo.
    """
    _logger.info("AI Production Assistant: Inicializando datos por defecto...")

    try:
        # 1. Crear configuración Ollama por defecto si no existe
        if not env["ai.ollama.config"].search_count([]):
            env["ai.ollama.config"].create(
                {
                    "name": "Servidor Local Ollama",
                    "url": "http://localhost:11434",
                    "timeout": 30,
                    "active": True,
                }
            )
            _logger.info("AI Production Assistant: Configuración Ollama creada")

        # 2. Crear modelos de Ollama por defecto
        # Verificar si el método get_default_models existe
        if hasattr(env["ai.ollama.model"], "get_default_models"):
            env["ai.ollama.model"].get_default_models()
            _logger.info("AI Production Assistant: Modelos por defecto creados")
        else:
            _logger.warning(
                "AI Production Assistant: Método get_default_models no encontrado"
            )

        # 3. Crear configuración vectorial por defecto si existe el modelo
        if "ai.vector.config" in env:
            if not env["ai.vector.config"].search_count([]):
                env["ai.vector.config"].create(
                    {
                        "name": "Configuración Qdrant Local",
                        "url": "http://localhost:6333",
                        "collection_name": "odoo_documents",
                        "active": True,
                    }
                )
                _logger.info("AI Production Assistant: Configuración Qdrant creada")

        # 4. Crear cron de procesamiento si no existe
        cron_model = env["ir.cron"]
        cron = cron_model.search(
            [
                (
                    "id",
                    "=",
                    env.ref(
                        "ai_production_assistant.ir_cron_process_ai_queue",
                        raise_if_not_found=False,
                    ),
                )
            ]
        )
        if not cron:
            cron_model.create(
                {
                    "name": "Procesar cola de IA",
                    "model_id": env.ref(
                        "ai_production_assistant.model_ai_assistant_message"
                    ).id,
                    "state": "code",
                    "code": "model._cron_process_ai_queue()",
                    "interval_number": 1,
                    "interval_type": "minutes",
                    "doall": False,
                    "active": True,
                }
            )
            _logger.info("AI Production Assistant: Cron de procesamiento creado")

        _logger.info("AI Production Assistant: Inicialización completada exitosamente")

    except Exception as e:
        _logger.error("AI Production Assistant: Error en inicialización: %s", str(e))
        raise
