# -*- coding: utf-8 -*-
{
    'name': "Asistente de Producción IA (Ollama)",
    'version': '1.0',
    'author': 'Pedro Mencías',
    'website': 'https://pedromencias.netlify.app/',
    'category': 'Manufacturing',
    'summary': 'Asistente IA para CEO/CTO con conexión a Ollama',
    'description': """
        Integra un modelo local (Ollama) en el módulo de Fabricación para análisis de datos.
    """,
    
    'icon': 'static/description/icon.png',
    'images': [
        'static/description/images/portada_screenshot.png',
        'static/description/images/modal_wizard.png',
    ],
    
    'depends': ['base', 'mail', 'mrp', 'stock', 'sale', 'product'],
    
    'data': [
    # 1. Seguridad (siempre primero)
    'security/ir.model.access.csv',
    
    # 2. Acciones (deben cargarse antes que los menús)
    'views/ai_chat_action.xml',
    
    # 3. Vistas (cargar antes que los menús que las usen)
    'views/ai_assistant_views.xml',
    'views/ai_ollama_model_views.xml',
    'views/ai_ollama_config_views.xml',
    'views/ai_prompt_wizard_views.xml',
    'views/ai_vector_config_views.xml',
    'views/ai_pending_action_views.xml',
    
    # 4. Menús (deben cargarse después de las acciones y vistas)
    'views/menu.xml',
    
    # 5. Datos del sistema (cron, etc.)
    'data/ir_cron.xml',
],
    
    'demo': [
        'demo/demo_data.xml',
    ],
    
    'assets': {
        'web.assets_backend': [
            'ai_production_assistant/static/src/components/chat/ai_chat.js',
            'ai_production_assistant/static/src/components/chat/ai_chat.xml',
            'ai_production_assistant/static/src/components/chat/ai_chat.scss',
        ],
    },
    
    'post_init_hook': '_create_default_data',
    
    'application': True,
    'installable': True,
    'license': 'LGPL-3',
}