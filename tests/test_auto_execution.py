#!/usr/bin/env python3
"""
Test para verificar que las herramientas de búsqueda se ejecuten automáticamente
"""

import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.agent_core import AgentCore, parse_create_product_prompt, parse_inventory_prompt
from services.sales_purchase_tools import (
    parse_purchase_orders_prompt,
    parse_sale_orders_prompt,
)
from services.rag_service import parse_docs_prompt, parse_mail_prompt
import logging

# Configurar logging para ver lo que está pasando
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)


def test_auto_execution():
    """Test que simula la ejecución automática de herramientas de búsqueda"""

    print("🧪 Test de Auto-ejecución de Herramientas de Búsqueda")
    print("=" * 60)

    # Crear un mock del entorno de Odoo
    class MockEnv:
        def __init__(self):
            self.user = MockUser()

        def __getitem__(self, model_name):
            if model_name == "product.product":
                return MockProductModel()
            elif model_name == "mrp.production":
                return MockMrpModel()
            return MockModel()

    class MockUser:
        def __init__(self):
            self.name = "Test User"

    class MockModel:
        def search_read(self, domain, fields, limit=None):
            return []

    class MockProductModel(MockModel):
        def search_read(self, domain, fields, limit=None):
            # Simular algunos productos
            return [
                {
                    "id": 1,
                    "name": "Producto Test 1",
                    "qty_available": 10,
                    "list_price": 25.0,
                    "standard_price": 15.0,
                },
                {
                    "id": 2,
                    "name": "Producto Test 2",
                    "qty_available": 5,
                    "list_price": 50.0,
                    "standard_price": 30.0,
                },
            ]

        def create(self, vals):
            class MockProduct:
                def __init__(self, data):
                    self.id = 99
                    self.name = data.get("name")
                    self.list_price = data.get("list_price")
                    self.standard_price = data.get("standard_price")

            return MockProduct(vals)

    class MockMrpModel(MockModel):
        def search_read(self, domain, fields, limit=None):
            # Simular algunas órdenes de fabricación
            return [
                {
                    "id": 1,
                    "name": "MO/001",
                    "product_id": [1, "Producto Test 1"],
                    "state": "confirmed",
                    "date_deadline": "2024-01-15",
                    "product_qty": 10.0,
                },
                {
                    "id": 2,
                    "name": "MO/002",
                    "product_id": [2, "Producto Test 2"],
                    "state": "delayed",
                    "date_deadline": "2024-01-10",
                    "product_qty": 5.0,
                },
            ]

    # Crear el agente con el mock environment
    env = MockEnv()
    agent = AgentCore(env)

    # Test 1: Búsqueda de productos
    print("\n📦 Test 1: Búsqueda automática de productos")
    print("Query: 'que productos tenemos'")

    # Simular el parseo de una respuesta que debería ejecutar automáticamente
    test_action = {"tool": "search_products", "params": {"name": ""}}

    result = agent._handle_action(test_action, "", {})
    print(f"Resultado: {result}")

    # Test 2: Búsqueda de órdenes de fabricación
    print("\n🏭 Test 2: Búsqueda automática de órdenes MRP")
    print("Query: 'que ordenes están en retraso'")

    test_action2 = {"tool": "search_mrp_orders", "params": {"state": "delayed"}}

    result2 = agent._handle_action(test_action2, "", {})
    print(f"Resultado: {result2}")

    print("\n🛒 Test 3: Creación de producto con tipo en español")
    test_action3 = {
        "tool": "create_product",
        "params": {
            "name": "Barra de pan",
            "price": 1.2,
            "cost": 0.6,
            "type": "alimento",
        },
    }
    result3 = agent._execute_tool(test_action3["tool"], test_action3["params"])
    print(f"Resultado: {result3}")

    print("\n💬 Test 4: Mensaje normal (no auto-ejecución)")
    print("Query: 'hola, como estás'")

    test_action4 = {
        "tool": "message",
        "params": {"content": "Hola! Estoy bien, gracias. ¿En qué puedo ayudarte?"},
    }

    result4 = agent._handle_action(test_action4, "", {})
    print(f"Resultado: {result4}")

    print("\n🧩 Test 5: Parseo JSON message con text")
    raw = '```json{"tool": "message", "params": {"text": "Hola humano"}}```'
    parsed = agent._parse_response(raw)
    print(f"Resultado: {parsed}")

    print("\n🧩 Test 6: Parseo prompt crear producto")
    prompt = "crear barra de pan, venta 1.20€, coste 0.60€, alimento"
    parsed_action = parse_create_product_prompt(prompt)
    print(f"Resultado: {parsed_action}")

    print("\n🧩 Test 7: Parseo prompt con nombre entre comillas")
    prompt = 'crea producto: nombre ? "bollo", precio 2.5, costo 1, tipo alimento'
    parsed_action = parse_create_product_prompt(prompt)
    print(f"Resultado: {parsed_action}")

    print("\n🧩 Test 8: Parseo prompt inventario")
    prompt = "haz inventario"
    parsed_action = parse_inventory_prompt(prompt)
    print(f"Resultado: {parsed_action}")

    print("\n🧩 Test 9: Parseo prompt ventas con fechas")
    prompt = "ventas este mes"
    parsed_action = parse_sale_orders_prompt(prompt)
    print(f"Resultado: {parsed_action}")

    print("\n🧩 Test 10: Parseo prompt compras últimos 7 días")
    prompt = "compras últimos 7 días"
    parsed_action = parse_purchase_orders_prompt(prompt)
    print(f"Resultado: {parsed_action}")

    print("\n🧩 Test 11: Parseo prompt ventas por cliente")
    prompt = "ventas cliente Acme este mes"
    parsed_action = parse_sale_orders_prompt(prompt)
    print(f"Resultado: {parsed_action}")

    print("\n🧩 Test 12: Parseo prompt compras por proveedor")
    prompt = "compras proveedor Global Supplies"
    parsed_action = parse_purchase_orders_prompt(prompt)
    print(f"Resultado: {parsed_action}")

    print("\n🧩 Test 13: Parseo prompt ventas pendientes")
    prompt = "ventas pendientes"
    parsed_action = parse_sale_orders_prompt(prompt)
    print(f"Resultado: {parsed_action}")

    print("\n🧩 Test 14: Parseo prompt compras aprobadas")
    prompt = "compras aprobadas"
    parsed_action = parse_purchase_orders_prompt(prompt)
    print(f"Resultado: {parsed_action}")

    print("\n🧩 Test 15: Parseo prompt docs")
    prompt = "buscar en documentación el procedimiento de calibración"
    parsed_action = parse_docs_prompt(prompt)
    print(f"Resultado: {parsed_action}")

    print("\n🧩 Test 16: Parseo prompt correo")
    prompt = "revisar el correo urgente"
    parsed_action = parse_mail_prompt(prompt)
    print(f"Resultado: {parsed_action}")

    print("\n✅ Test completado")


if __name__ == "__main__":
    test_auto_execution()
