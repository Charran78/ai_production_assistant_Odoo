# -*- coding: utf-8 -*-
{
    "name": "Asistente de Producción IA (Ollama)",
    "version": "19.0.1.0.0",
    "author": "Pedro Mencías",
    "website": "https://pedromencias.netlify.app/",
    "category": "Manufacturing",
    "summary": "Asistente IA para CEO/CTO con conexión a Ollama",
    # 'icon': '/ai_production_assistant/static/description/icon.png', # Odoo busca esto automáticamente
    "images": [
        "static/description/images/portada_screenshot.png",
        "static/description/images/modal_wizard.png",
    ],
    "depends": ["base", "mail", "product", "stock", "mrp"],
    "data": [
        # 1. Seguridad (siempre primero)
        "security/ir.model.access.csv",
        "security/ai_assistant_rules.xml",
        # 2. Acciones (deben cargarse antes que los menús)
        "views/ai_chat_action.xml",
        # 3. Vistas (cargar antes que los menús que las usen)
        "views/ai_assistant_views.xml",
        "views/ai_ollama_model_views.xml",
        "views/ai_ollama_config_views.xml",
        "views/ai_prompt_wizard_views.xml",
        "views/ai_vector_config_views.xml",
        "views/ai_watchdog_views.xml",
        "views/ai_notification_views.xml",
        "views/ai_pending_action_views.xml",
        "views/installation_wizard_views.xml",
        # 4. Menús (deben cargarse después de las acciones y vistas)
        "views/menu.xml",
        # 5. Datos del sistema (cron, etc.)
        "data/ir_cron.xml",
    ],
    "demo": [
        "demo/demo_data.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "ai_production_assistant/static/src/components/chat/ai_chat.js",
            "ai_production_assistant/static/src/components/chat/ai_chat.xml",
            "ai_production_assistant/static/src/components/chat/ai_chat.scss",
            "ai_production_assistant/static/src/components/assistant/ai_avatar.js",
            "ai_production_assistant/static/src/components/assistant/ai_avatar.xml",
            "ai_production_assistant/static/src/components/assistant/ai_avatar.scss",
        ],
    },
    "post_init_hook": "_create_default_data",
    "application": True,
    "license": "LGPL-3",
}
