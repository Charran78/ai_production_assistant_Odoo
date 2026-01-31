# -*- coding: utf-8 -*-
"""
AgentCore - Núcleo del Asistente IA para Odoo
Arquitectura limpia y optimizada para modelos locales (gemma3:4b)
"""
import json
import re
import logging
from datetime import datetime

_logger = logging.getLogger(__name__)


# ============================================================================
# CONFIGURACIÓN DE HERRAMIENTAS
# ============================================================================

TOOLS = {
    "search_products": {
        "description": "Buscar productos por nombre (vacío = listar todos)",
        "params": ["name"]
    },
    "create_product": {
        "description": "Crear un nuevo producto",
        "params": ["name", "price", "cost", "type"]  # type: consu, product, service
    },
    "search_mrp_orders": {
        "description": "Buscar órdenes de fabricación",
        "params": ["state"]  # draft, confirmed, progress, done, cancel
    },
    "create_mrp_order": {
        "description": "Crear orden de fabricación",
        "params": ["product_id", "quantity"]
    },
    "create_bom": {
        "description": "Crear lista de materiales (BoM) para un producto",
        "params": ["product_id", "components"]  # components: [{"product_id": X, "qty": Y}, ...]
    },
    "adjust_stock": {
        "description": "Ajustar inventario de un producto",
        "params": ["product_id", "quantity"]
    },
    "message": {
        "description": "Responder al usuario con texto",
        "params": ["content"]
    }
}


# ============================================================================
# SYSTEM PROMPT (CORTO Y EFECTIVO)
# ============================================================================

SYSTEM_PROMPT = """Eres el asistente de operaciones de Odoo.
Fecha y Hora Actual: {date}

HERRAMIENTAS DISPONIBLES:
- search_products: buscar productos (params: name). Ej: {{"tool": "search_products", "params": {{"name": "mesa"}}}}
- create_product: crear producto (params: name, price, cost). Ej: {{"tool": "create_product", "params": {{"name": "X", "price": 10, "cost": 5}}}}
- create_bom: crear lista de materiales (params: product_id, components). Components es lista de dicts {{"product_id": ID, "qty": N}}.
- search_mrp_orders: buscar órdenes de fabricación (params: state).
- message: responder texto normal.

REGLAS:
1. Si te preguntan la hora, responde con la fecha y hora indicadas arriba.
2. Para realizar acciones, responde SOLO con el JSON de la herramienta. NO añadas texto fuera del JSON.
3. Si faltan datos para una herramienta (ej: precio), PREGUNTA al usuario antes de generar el JSON. NO inventes datos.
4. Si el usuario pide crear algo complejo (BoM), primero busca si existen los componentes.
5. Usa el ID numérico de los productos (ej: [12]) para referirte a ellos en las herramientas.

{context}"""


class AgentCore:
    """Núcleo del agente IA - una llamada, una respuesta."""
    
    def __init__(self, env):
        self.env = env
    
    def process(self, query, context="", model=None):
        """
        Procesa una consulta del usuario.
        Args:
            query: Pregunta del usuario
            context: Contexto adicional
            model: Modelo Ollama a usar (opcional)
        Returns: dict con 'response' (texto) o 'action' (para aprobar)
        """
        from .ollama_service import OllamaService
        
        ollama = OllamaService(self.env)
        
        # Usar modelo especificado o el default
        target_model = model if model else ollama.model
        
        # Construir prompt
        # Incluir FECHA y HORA
        now = datetime.now()
        ctx_section = f"CONTEXTO RECUPERADO:\n{context}" if context else ""
        system = SYSTEM_PROMPT.format(
            date=now.strftime('%d/%m/%Y %H:%M'),
            context=ctx_section
        )
        
        full_prompt = f"{system}\n\nUsuario: {query}\nRespuesta (JSON o Texto):"
        
        # Llamar a Ollama con el modelo especificado
        raw_response = ollama.generate(prompt=full_prompt, model=target_model)
        
        if not raw_response or raw_response.startswith("Error") or raw_response.startswith("⚠️") or raw_response.startswith("❌") or raw_response.startswith("⏱️"):
            return {"response": raw_response or "Error de conexión con Ollama"}
        
        # Parsear respuesta
        action = self._parse_response(raw_response)
        
        # Ejecutar acción o devolver respuesta
        return self._handle_action(action, raw_response)
    
    def _parse_response(self, text):
        """Extrae JSON de la respuesta del modelo de forma robusta."""
        if not text:
            return {"tool": "message", "params": {"content": "Sin respuesta"}}
        
        text_clean = text.strip()
        
        # 1. Intento Directo (Lo más rápido y común si el modelo obedece bien)
        try:
            return json.loads(text_clean)
        except json.JSONDecodeError:
            pass
            
        # 2. Buscar bloque Markdown ```json ... ```
        code_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text_clean, re.DOTALL)
        if code_match:
            try:
                return json.loads(code_match.group(1))
            except json.JSONDecodeError:
                pass

        # 3. Buscar el primer objeto JSON válido { ... } usando pila de llaves (parser manual simple)
        # Esto es necesario porque regex no maneja bien anidamiento recursivo
        try:
            start = text_clean.find('{')
            if start != -1:
                brace_count = 0
                json_candidate = ""
                for char in text_clean[start:]:
                    json_candidate += char
                    if char == '{':
                        brace_count += 1
                    elif char == '}':
                        brace_count -= 1
                        if brace_count == 0:
                            # Fin del objeto
                            try:
                                return json.loads(json_candidate)
                            except json.JSONDecodeError:
                                # Si falla, podría ser que encontramos un {} interno pero no el principal, 
                                # o el JSON está malformado. Seguimos buscando? No, asumimos fallback.
                                break 
                            break
        except Exception:
            pass
        
        # 4. Fallback: Devolver como mensaje, pero intentando limpiar si parece un JSON roto
        _logger.warning("No se pudo parsear JSON. Raw: %s", text[:100])
        return {"tool": "message", "params": {"content": text_clean}}

    def process(self, query, context="", model=None, history=None):
        """
        Procesa una consulta del usuario con memoria a corto plazo.
        Args:
            query: Pregunta del usuario
            context: Contexto adicional (RAG)
            model: Modelo Ollama (opcional)
            history: Lista de strings con historial previo para contexto
        Returns: dict con 'response' (texto) o 'action' (para aprobar)
        """
        from .ollama_service import OllamaService
        
        ollama = OllamaService(self.env)
        target_model = model if model else ollama.model
        
        # Incluir FECHA y HORA
        now = datetime.now()
        ctx_section = f"CONTEXTO RECUPERADO:\n{context}" if context else ""
        system = SYSTEM_PROMPT.format(
            date=now.strftime('%d/%m/%Y %H:%M'),
            context=ctx_section
        )

        # Construir sección de historial
        history_section = ""
        if history:
            history_str = "\n".join(history)
            history_section = f"HISTORIAL CHAT:\n{history_str}\n"
        
        full_prompt = f"{system}\n\n{history_section}Usuario: {query}\nRespuesta (JSON o Texto):"
        
        raw_response = ollama.generate(prompt=full_prompt, model=target_model)
    
    def _handle_action(self, action, raw_response):
        """Ejecuta la acción o devuelve respuesta, con validación de parámetros."""
        tool = action.get("tool", "message")
        params = action.get("params", {})
        
        # Si es mensaje, devolver el contenido limpio SIN JSON
        if tool == "message":
            content = params.get("content", raw_response)
            # Limpieza defensiva de JSON residual en content
            if isinstance(content, str) and content.strip().startswith('{') and '"tool":' in content:
                 try:
                     inner = json.loads(content)
                     if inner.get('tool') == 'message':
                         content = inner['params'].get('content', content)
                 except:
                     pass
            return {"response": content}
            
        # VALIDACIÓN DE PARÁMETROS OBLIGATORIOS
        required_params = {
            "create_product": ["name", "price"],
            "create_bom": ["product_id", "components"],
            "create_mrp_order": ["product_id", "quantity"],
            "adjust_stock": ["product_id", "quantity"]
        }
        
        if tool in required_params:
            missing = [p for p in required_params[tool] if p not in params or not params[p]]
            if missing:
                # Si faltan parámetros, convertimos la acción en una pregunta al usuario
                msg = f"Para realizar '{tool}' necesito más información: {', '.join(missing)}. ¿Podrías proporcionarla?"
                return {"response": msg}

        # Si es una acción válida, preparar para aprobación
        return {
            "response": f"He preparado la acción: {tool}. ¿Deseas proceder?",
            "action": action
        }
    
    def _execute_tool(self, tool, params):
        """Ejecuta una herramienta y devuelve resultado."""
        
        if tool == "search_products":
            name = params.get("name", "")
            domain = [('name', 'ilike', name)] if name else []
            products = self.env['product.product'].search_read(
                domain,
                ['id', 'name', 'qty_available', 'list_price', 'standard_price'],
                limit=15
            )
            if products:
                lines = [f"📦 Encontré {len(products)} productos:"]
                for p in products:
                    stock_info = f"Stock: {p['qty_available']}" if p['qty_available'] else "Sin stock"
                    lines.append(f"• [{p['id']}] {p['name']} - {stock_info} - Precio: {p['list_price']}€")
                return {"response": "\n".join(lines)}
            if name:
                return {"response": f"No encontré productos con '{name}'"}
            return {"response": "No hay productos en el sistema. ¿Quieres crear uno?"}
        
        elif tool == "create_product":
            name = params.get("name")
            price = params.get("price", 0)
            cost = params.get("cost", 0)
            product_type = params.get("type", "consu")  # consu, product, service
            
            if not name:
                return {"response": "❌ Necesito el nombre del producto"}
            
            # Crear producto
            vals = {
                'name': name,
                'list_price': float(price) if price else 0,
                'standard_price': float(cost) if cost else 0,
                'type': product_type,
                'sale_ok': True,
                'purchase_ok': True,
            }
            
            try:
                product = self.env['product.product'].create(vals)
                return {
                    "response": f"✅ Producto creado:\n• ID: {product.id}\n• Nombre: {product.name}\n• Precio: {product.list_price}€\n• Coste: {product.standard_price}€",
                    "created_id": product.id
                }
            except Exception as e:
                return {"response": f"❌ Error creando producto: {str(e)}"}
        
        elif tool == "create_bom":
            product_id = params.get("product_id")
            components = params.get("components", [])
            
            if not product_id:
                return {"response": "❌ Necesito el ID del producto para crear la BoM"}
            
            if not components:
                return {"response": "❌ Necesito la lista de componentes"}
            
            try:
                product = self.env['product.product'].browse(int(product_id))
                if not product.exists():
                    return {"response": f"❌ Producto {product_id} no existe"}
                
                # Crear BoM
                bom_lines = []
                for comp in components:
                    comp_id = comp.get("product_id")
                    qty = comp.get("qty", 1)
                    if comp_id:
                        bom_lines.append((0, 0, {
                            'product_id': int(comp_id),
                            'product_qty': float(qty),
                        }))
                
                bom = self.env['mrp.bom'].create({
                    'product_id': product.id,
                    'product_tmpl_id': product.product_tmpl_id.id,
                    'product_qty': 1,
                    'bom_line_ids': bom_lines,
                })
                
                return {
                    "response": f"✅ Lista de materiales creada:\n• BoM ID: {bom.id}\n• Producto: {product.name}\n• Componentes: {len(bom_lines)}",
                    "created_id": bom.id
                }
            except Exception as e:
                return {"response": f"❌ Error creando BoM: {str(e)}"}
        
        elif tool == "search_mrp_orders":
            state = params.get("state", "")
            domain = [('state', '=', state)] if state else []
            orders = self.env['mrp.production'].search_read(
                domain,
                ['id', 'name', 'product_id', 'product_qty', 'state', 'date_deadline'],
                limit=10
            )
            if orders:
                lines = [f"🏭 Encontré {len(orders)} órdenes:"]
                for o in orders:
                    product_name = o['product_id'][1] if o['product_id'] else 'N/A'
                    lines.append(f"• [{o['id']}] {o['name']} - {product_name} x{o['product_qty']} ({o['state']})")
                return {"response": "\n".join(lines)}
            if state:
                return {"response": f"No hay órdenes de fabricación en estado '{state}'"}
            return {"response": "No hay órdenes de fabricación en el sistema"}
        
        elif tool == "create_mrp_order":
            product_id = params.get("product_id")
            quantity = params.get("quantity", 1)
            
            if not product_id:
                return {"response": "❌ Necesito el ID del producto para crear la orden"}
            
            try:
                product = self.env['product.product'].browse(int(product_id))
                if not product.exists():
                    return {"response": f"❌ Producto {product_id} no existe"}
                
                # Buscar BoM
                bom = self.env['mrp.bom'].search([
                    '|', 
                    ('product_id', '=', product.id),
                    ('product_tmpl_id', '=', product.product_tmpl_id.id)
                ], limit=1)
                
                vals = {
                    'product_id': product.id,
                    'product_qty': float(quantity),
                    'product_uom_id': product.uom_id.id,
                }
                if bom:
                    vals['bom_id'] = bom.id
                
                mo = self.env['mrp.production'].create(vals)
                return {
                    "response": f"✅ Orden de fabricación creada:\n• {mo.name}\n• Producto: {product.name}\n• Cantidad: {quantity}",
                    "created_id": mo.id
                }
            except Exception as e:
                return {"response": f"❌ Error creando orden: {str(e)}"}
        
        elif tool == "adjust_stock":
            product_id = params.get("product_id")
            quantity = params.get("quantity")
            
            if not product_id or quantity is None:
                return {"response": "❌ Necesito product_id y quantity para ajustar stock"}
            
            try:
                product = self.env['product.product'].browse(int(product_id))
                if not product.exists():
                    return {"response": f"❌ Producto {product_id} no existe"}
                
                # Buscar ubicación principal
                location = self.env['stock.location'].search([
                    ('usage', '=', 'internal')
                ], limit=1)
                
                if not location:
                    return {"response": "❌ No hay ubicaciones de almacén configuradas"}
                
                # Buscar o crear quant
                quant = self.env['stock.quant'].search([
                    ('product_id', '=', product.id),
                    ('location_id', '=', location.id)
                ], limit=1)
                
                if quant:
                    quant.write({'inventory_quantity': float(quantity)})
                    quant.action_apply_inventory()
                else:
                    self.env['stock.quant'].create({
                        'product_id': product.id,
                        'location_id': location.id,
                        'inventory_quantity': float(quantity),
                    }).action_apply_inventory()
                
                return {
                    "response": f"✅ Stock ajustado:\n• Producto: {product.name}\n• Nueva cantidad: {quantity}"
                }
            except Exception as e:
                return {"response": f"❌ Error ajustando stock: {str(e)}"}
        
        return {"response": f"Herramienta '{tool}' no implementada"}
    
    def execute_approved_action(self, action_data):
        """Ejecuta una acción previamente aprobada por el usuario."""
        action_type = action_data.get("type")
        
        try:
            if action_type == "create_mrp_order":
                return self._execute_tool("create_mrp_order", action_data)
            elif action_type == "adjust_stock":
                return self._execute_tool("adjust_stock", action_data)
            elif action_type == "create_product":
                return self._execute_tool("create_product", action_data)
            elif action_type == "create_bom":
                return self._execute_tool("create_bom", action_data)
            
            return {"error": f"Tipo de acción '{action_type}' no soportado"}
            
        except Exception as e:
            _logger.error("Error ejecutando acción aprobada: %s", str(e))
            return {"error": str(e)}


def get_minimal_context(env, query=""):
    """Obtiene contexto mínimo para el modelo."""
    lines = []
    
    query_lower = query.lower() if query else ""
    
    # Detectar intención y obtener datos relevantes
    if any(w in query_lower for w in ['producto', 'productos', 'stock', 'inventario', 'qué hay', 'listar']):
        products = env['product.product'].search_read(
            [], ['id', 'name', 'qty_available'], limit=5, order='write_date desc'
        )
        if products:
            lines.append("Productos recientes:")
            for p in products:
                lines.append(f"- [{p['id']}] {p['name']}: {p['qty_available']} uds")
    
    elif any(w in query_lower for w in ['fabricación', 'producción', 'orden', 'mrp', 'retras']):
        orders = env['mrp.production'].search_read(
            [('state', 'in', ['confirmed', 'progress'])],
            ['id', 'name', 'product_id', 'state'],
            limit=5
        )
        if orders:
            lines.append("Órdenes activas:")
            for o in orders:
                prod = o['product_id'][1] if o['product_id'] else 'N/A'
                lines.append(f"- [{o['id']}] {o['name']}: {prod} ({o['state']})")
    
    return "\n".join(lines) if lines else ""
