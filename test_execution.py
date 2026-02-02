#!/usr/bin/env python3
"""
Script de prueba para verificar la ejecución automática de herramientas
"""

import logging

from .services.agent_core import AgentCore

_logger = logging.getLogger(__name__)


def test_auto_execution():
    """Prueba la ejecución automática de herramientas"""

    # Simular un entorno de Odoo
    class MockEnv:
        def __init__(self):
            self.user = MockUser()

        def __getitem__(self, key):
            if key == "product.product":
                return MockProductModel()
            if key == "mrp.production":
                return MockMrpModel()
            if key == "mrp.bom":
                return MockBomModel()
            if key == "stock.location":
                return MockLocationModel()
            if key == "stock.quant":
                return MockQuantModel()
            return MockModel()

    class MockUser:
        def __init__(self):
            self.id = 1

    class MockModel:
        def search_read(self, *_args, **_kwargs):
            return []

        def search(self, *_args, **_kwargs):
            return MockRecordSet()

        def browse(self, *_args, **_kwargs):
            return MockRecordSet()

    class MockProductModel(MockModel):
        def search_read(self, *_args, **_kwargs):
            domain = _args[0] if _args else []
            if not domain:  # Listar todos
                return [
                    {
                        "id": 1,
                        "name": "Producto A",
                        "qty_available": 10,
                        "list_price": 100,
                        "standard_price": 50,
                    },
                    {
                        "id": 2,
                        "name": "Producto B",
                        "qty_available": 5,
                        "list_price": 200,
                        "standard_price": 100,
                    },
                ]
            return []

    class MockMrpModel(MockModel):
        def search_read(self, *_args, **_kwargs):
            domain = _args[0] if _args else []
            # Simular órdenes retrasadas
            if domain and any(d[0] == "state" and "delayed" in str(d) for d in domain):
                return [
                    {
                        "id": 1,
                        "name": "MO/001",
                        "product_id": [1, "Producto A"],
                        "product_qty": 10,
                        "state": "confirmed",
                        "date_deadline": "2024-01-01",
                    },
                    {
                        "id": 2,
                        "name": "MO/002",
                        "product_id": [2, "Producto B"],
                        "product_qty": 5,
                        "state": "progress",
                        "date_deadline": "2024-01-02",
                    },
                ]
            return []

    class MockBomModel(MockModel):
        pass

    class MockLocationModel(MockModel):
        pass

    class MockQuantModel(MockModel):
        pass

    class MockRecordSet:
        def __init__(self):
            self.exists = lambda: True

        def __iter__(self):
            return iter([])

    # Crear entorno mock
    env = MockEnv()
    agent = AgentCore(env)

    _logger.info("=== PRUEBA DE AUTO-EJECUCIÓN DE HERRAMIENTAS ===")

    # Test 1: search_products
    _logger.info("1. Probando search_products...")
    test_response = '{"tool": "search_products", "params": {"name": ""}}'
    result = agent.parse_response(test_response)
    _logger.info("   JSON parseado: %s", result)

    action_result = agent.handle_action(result, test_response)
    _logger.info("   Resultado del handle_action: %s", action_result)

    # Test 2: search_mrp_orders con estado "delayed"
    _logger.info("2. Probando search_mrp_orders con estado delayed...")
    test_response2 = '{"tool": "search_mrp_orders", "params": {"state": "delayed"}}'
    result2 = agent.parse_response(test_response2)
    _logger.info("   JSON parseado: %s", result2)

    action_result2 = agent.handle_action(result2, test_response2)
    _logger.info("   Resultado del handle_action: %s", action_result2)

    # Test 3: Probar con "parameters" en lugar de "params"
    _logger.info("3. Probando con 'parameters' en lugar de 'params'...")
    test_response3 = '{"tool": "search_products", "parameters": {"name": "test"}}'
    result3 = agent.parse_response(test_response3)
    _logger.info("   JSON parseado: %s", result3)

    action_result3 = agent.handle_action(result3, test_response3)
    _logger.info("   Resultado del handle_action: %s", action_result3)


if __name__ == "__main__":
    test_auto_execution()
