# -*- coding: utf-8 -*-
import logging

_logger = logging.getLogger(__name__)


class MoERouter:
    """
    Mixture of Experts Router.
    Analiza la intención del usuario y selecciona el 'Experto' (System Prompt + Herramientas) más adecuado.
    """

    def __init__(self, env):
        self.env = env

    def route(self, user_query, _current_model=False):
        """
        Determina el experto basado en palabras clave y contexto.
        Retorna: (expert_name, system_prompt, tools_config)
        """
        query_lower = user_query.lower()

        # 1. Experto en Manufactura (MRP)
        if any(
            w in query_lower
            for w in [
                "fabricar",
                "producción",
                "orden",
                "mo",
                "lista de materiales",
                "bom",
                "componentes",
            ]
        ):
            return self._get_manufacturing_expert()

        # 2. Experto en Inventario (Stock)
        if any(
            w in query_lower
            for w in ["stock", "inventario", "cantidad", "almacén", "ubicación", "lote"]
        ):
            return self._get_inventory_expert()

        # 3. Experto Kaizen (Mejora Continua)
        if any(
            w in query_lower
            for w in [
                "mejorar",
                "analizar",
                "eficiencia",
                "retraso",
                "problema",
                "optimizar",
                "kaizen",
            ]
        ):
            return self._get_kaizen_expert()

        # 4. Experto General (Fallback)
        return self._get_generalist_expert()

    def _get_manufacturing_expert(self):
        tools = {
            "search_products": "Busca productos y materias primas. params: {'name': str}",
            "create_product": (
                "Crea un nuevo producto. params: {'name': str, 'price': float, "
                "'cost': float, 'type': str}"
            ),
            "create_bom": (
                "Crea lista de materiales. params: {'product_id': int, "
                "'components': list}"
            ),
            "search_mrp_orders": (
                "Busca órdenes de fabricación (usa state='delayed' para retrasos). "
                "params: {'state': str}"
            ),
            "create_mrp_order": (
                "Crea una Orden de Fabricación. params: {'product_id': int, "
                "'product_qty': float}"
            ),
            "message": "Responde al usuario.",
        }
        prompt = """Eres el EXPERTO EN MANUFACTURA (MRP) de Odoo.
Tu misión es asegurar que la producción fluya sin interrupciones.
Enfócate en listas de materiales, órdenes de producción y disponibilidad de centros de trabajo.
Si falta material, sugiere verificar stock o crear productos faltantes.
Si hay retrasos, busca las órdenes retrasadas y sugiere acciones.

REGLA IMPORTANTE: Usa SIEMPRE "params" y NUNCA "parameters" en el JSON de las herramientas."""
        return "Manufacturing Lead", prompt, tools

    def _get_inventory_expert(self):
        tools = {
            "search_products": "Busca productos y ver stock. params: {'name': str}",
            "create_product": (
                "Crea un nuevo producto. params: {'name': str, 'price': float, "
                "'cost': float, 'type': str}"
            ),
            "adjust_stock": (
                "Ajusta el inventario. params: {'product_id': int, 'quantity': "
                "float}"
            ),
            "message": "Responde al usuario.",
        }
        prompt = """Eres el EXPERTO EN INVENTARIO Y LOGÍSTICA de Odoo.
Tu misión es mantener la precisión del stock.
Cuando te pregunten por cantidades, sé preciso con las ubicaciones.
Puedes crear productos nuevos si no existen y ajustar sus niveles de stock.

REGLA IMPORTANTE: Usa SIEMPRE "params" y NUNCA "parameters" en el JSON de las herramientas."""
        return "Inventory Manager", prompt, tools

    def _get_kaizen_expert(self):
        tools = {
            "search_mrp_orders": (
                "Busca órdenes retrasadas (state='delayed') o en otros estados. "
                "params: {'state': str}"
            ),
            "search_products": "Busca información de productos y stock. params: {'name': str}",
            "create_mrp_order": (
                "Crea una Orden de Fabricación. params: {'product_id': int, "
                "'product_qty': float}"
            ),
            "message": "Responde al usuario.",
        }
        prompt = """Eres el CONSULTOR KAIZEN (Mejora Continua).
Tu filosofía es: "Hoy mejor que ayer, mañana mejor que hoy".
Analiza retrasos buscando órdenes con state='delayed'.
Propón soluciones proactivas. Si ves un retraso, pregunta "¿Por qué?" y sugiere acciones correctivas.

REGLA IMPORTANTE: Usa SIEMPRE "params" y NUNCA "parameters" en el JSON de las herramientas."""
        return "Kaizen Analyst", prompt, tools

    def _get_generalist_expert(self):
        # El generalista tiene acceso a herramientas básicas de todos
        tools = {
            "search_products": "Busca productos. params: {'name': str}",
            "create_product": (
                "Crea un nuevo producto. params: {'name': str, 'price': float, "
                "'cost': float, 'type': str}"
            ),
            "search_mrp_orders": "Busca órdenes de fabricación. params: {'state': str}",
            "search_docs": "Busca en documentación. params: {'query': str}",
            "search_mail": "Busca en correo. params: {'query': str}",
            "message": "Responde al usuario.",
        }
        prompt = """Eres el ASISTENTE GENERAL de Operaciones.
Ayuda al usuario con consultas generales.
Puedes buscar productos, crear productos simples y ver el estado de la producción.
Si la consulta se vuelve muy técnica sobre producción o stock, intenta responder con lo que sabes.

REGLA IMPORTANTE: Usa SIEMPRE "params" y NUNCA "parameters" en el JSON de las herramientas."""
        return "Assistant", prompt, tools
