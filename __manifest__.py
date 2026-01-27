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
    'depends': ['mrp', 'stock', 'mail'],
    'data': [
        'security/ir.model.access.csv',
        'views/ai_assistant_views.xml',
        'views/ai_ollama_model_views.xml',
        'views/ai_chat_action.xml',
        'views/ai_vector_views.xml',
        'views/menu.xml',
        'data/ir_cron.xml',
    ],
    'demo': [
        'demo/demo_data.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'ai_production_assistant/static/src/components/chat/ai_chat.xml',
            'ai_production_assistant/static/src/components/chat/ai_chat.scss',
            'ai_production_assistant/static/src/components/chat/ai_chat.js',
        ],
    },
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}
