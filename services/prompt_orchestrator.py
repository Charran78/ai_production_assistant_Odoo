# -*- coding: utf-8 -*-

class PromptOrchestrator:
    def __init__(self, env):
        self.env = env
        
        # 1. Diccionario de estilos CON REGLAS EXPLÍCITAS
        self.style_guides = {
            'concise': "Responde en un único párrafo conciso, sin introducciones ni despedidas.",
            'table': "Organiza los datos principales en una tabla Markdown. Añade una explicación breve si es necesario.",
            'report': """Estructura tu respuesta con estos apartados:
1. RESUMEN EJECUTIVO: La conclusión principal (1-2 líneas máx).
2. DATOS CLAVE: Los 3-5 datos más relevantes en viñetas.
3. ANÁLISIS: Interpretación de lo que significan esos datos.
4. RECOMENDACIONES: Acciones concretas a considerar (si aplica).""",
            'plan': """Genera un plan de acción con esta estructura:
- PASO 1: [Acción específica] → (Responsable: [Rol]) → (Plazo: [Fecha/Días])
- PASO 2: [Siguiente acción] → ..."""
        }
        
        # 2. Diccionario de especialización con ROLES ESPECÍFICOS
        self.model_expertise = {
            'mrp.production': "Eres un planificador de producción senior con 15 años de experiencia en Odoo. Especialista en capacidad, cuellos de botella, plazos y gestión de BoMs.",
            'sale.order': "Eres un director comercial especializado en Odoo. Experto en márgenes, plazos de entrega, priorización de clientes y negociación.",
            'stock.quant': "Eres un gestor de inventario certificado. Tu expertise es rotación de stock, puntos de pedido y optimización del espacio de almacén.",
            'product.product': "Eres un gestor de catálogo de productos. Conoces a fondo las categorías, atributos, variantes y costes.",
            'project.task': "Eres un director de proyectos PMP. Dominas metodologías ágiles, diagramas de Gantt y asignación de recursos.",
        }
        
        # 3. Diccionario de REQUISITOS MÍNIMOS por modelo (para validación)
        self.model_requirements = {
            'product.product': ['name'],
            'mrp.production': ['product_id'],
            'sale.order': ['partner_id'],
            'purchase.order': ['partner_id'],
            'stock.quant': ['quantity', 'location_id'],
        }

    def _build_action_templates(self, primary_model=None):
        """
        Devuelve PLANTILLAS GENÉRICAS con marcadores, NO ejemplos literales.
        Esto evita que el modelo copie IDs ficticios.
        """
        templates = "\n# EJEMPLOS DE ESTRUCTURA (NO COPIES LOS VALORES):\n"
        
        if primary_model == 'mrp.production':
            templates += """
<|user|>
¿Cómo vamos con la producción del producto [ID_DEL_CONTEXTO]?
<|assistant|>
Analizaré los datos de producción disponibles. Si detecto faltantes, sugeriré una acción específica.
[[ACTION_DATA: {"model": "purchase.order", "function": "create", "vals": {"partner_id": ID_PROVEEDOR_DEL_CONTEXTO, "order_line": [(0, 0, {"product_id": ID_COMPONENTE_DEL_CONTEXTO, "product_qty": CANTIDAD_DEL_CONTEXTO})]}}]]

<|user|>
Crea una orden de fabricación para X unidades del producto Y.
<|assistant|>
Para crear una orden de fabricación necesito: product_id, product_qty, y opcionalmente bom_id si está disponible.
[[ACTION_DATA: {"model": "mrp.production", "function": "create", "vals": {"product_id": ID_DEL_CONTEXTO, "product_qty": CANTIDAD_DEL_CONTEXTO, "bom_id": ID_BOM_DEL_CONTEXTO_SI_EXISTE}}]]
"""
        elif primary_model == 'sale.order':
            templates += """
<|user|>
Necesito una cotización para el cliente [ID_CLIENTE] con N unidades del producto [ID_PRODUCTO].
<|assistant|>
Para crear una cotización necesito: partner_id, order_line con product_id y product_uom_qty.
[[ACTION_DATA: {"model": "sale.order", "function": "create", "vals": {"partner_id": ID_DEL_CONTEXTO, "order_line": [(0, 0, {"product_id": ID_DEL_CONTEXTO, "product_uom_qty": CANTIDAD_DEL_CONTEXTO})]}}]]
"""
        elif primary_model == 'product.product':
            templates += """
<|user|>
Crea un nuevo producto llamado 'Nombre del Producto'.
<|assistant|>
Para crear un producto necesito al menos: name, y opcionalmente default_code, list_price, standard_price.
[[ACTION_DATA: {"model": "product.product", "function": "create", "vals": {"name": "NOMBRE_DEL_PRODUCTO", "default_code": "REFERENCIA_OPCIONAL"}}]]
"""
        
        templates += "\n# IMPORTANTE: Reemplaza los marcadores en MAYÚSCULAS con valores REALES del contexto.\n"
        return templates

    def get_system_prompt(self, context_str, model_name=False, output_style='concise', user_role='CEO'):
        """
        Genera un prompt con protecciones ANTI-ALUCINACIÓN.
        """
        # 1. Determinar especialidad principal
        primary_model = model_name if model_name in self.model_expertise else False
        expertise = self.model_expertise.get(primary_model, 
            "Eres un consultor ERP generalista con conocimiento transversal de Odoo 19.")
        
        # 2. Obtener plantillas genéricas (NO ejemplos literales)
        action_templates = self._build_action_templates(primary_model)
        
        # 3. Obtener requisitos mínimos para el modelo principal
        requirements = self.model_requirements.get(primary_model, [])
        req_text = f"Requisitos mínimos para {primary_model}: {', '.join(requirements)}" if requirements else ""
        
        # 4. Instrucciones de estilo
        style_guide = self.style_guides.get(output_style, self.style_guides['concise'])
        
        # 5. Reglas por rol de usuario
        role_rules = {
            'CEO': "Enfócate en el impacto estratégico y financiero. Evita detalles técnicos.",
            'CTO': "Profundiza en aspectos técnicos, integraciones y escalabilidad.",
            'Plant Manager': "Centrate en eficiencia operativa, plazos y recursos.",
            'Sales Manager': "Destaca oportunidades comerciales y relaciones con clientes.",
        }.get(user_role, "Adapta el nivel de detalle según el interlocutor.")
        
        # 6. Formatear contexto - LA ÚNICA FUENTE DE VERDAD
        if not context_str or "No hay contexto" in context_str:
            formatted_context = "🚨 CONTEXTO LIMITADO: Solo datos generales disponibles. NO inventes IDs ni valores específicos."
        else:
            formatted_context = f"""## 🗂️ DATOS REALES DISPONIBLES (ÚNICA FUENTE VÁLIDA):
{context_str}

## 📝 REGLAS DE USO DE DATOS:
1. SOLO usa IDs que aparezcan EXPLÍCITAMENTE arriba (ej: [45], [128]).
2. Si un dato NO está en la lista, NO lo inventes.
3. Para IDs no encontrados, di: 'Necesito el ID de [elemento] para proceder'."""
        
        # 7. Ensamblar el prompt FINAL con protecciones explícitas
        system_content = f"""<|system|>
# 🎯 ROL PRINCIPAL
{expertise}
Audiencia: {user_role}. {role_rules}
{req_text}

# 🛡️ REGLAS ABSOLUTAS (ANTI-ALUCINACIÓN)
1. **VERACIDAD TOTAL**: Solo usa datos del BLOQUE 'DATOS REALES DISPONIBLES'. Nunca inventes IDs, nombres, cantidades ni fechas.
2. **CONTEXTO O NADA**: Si no hay datos suficientes, di claramente: 'No tengo información suficiente sobre [aspecto]'.
3. **ACCIONES REALISTAS**: Solo sugiere acciones con datos COMPLETOS del contexto. Si faltan campos obligatorios, dilo.
4. **FORMATO ESTRICTO**: {style_guide}
5. **SEGURIDAD**: Para acciones críticas (>10.000€, despidos), añade '🚨 REQUIERE APROBACIÓN EXPLÍCITA'.

# 📋 FORMATO DE ACCIONES (Odoo 19)
- Productos nuevos → `product.product` (mínimo: name)
- Producción → `mrp.production` (mínimo: product_id, product_qty)
- Ventas → `sale.order` (mínimo: partner_id, order_line)
- Compras → `purchase.order` (mínimo: partner_id, order_line)
- Inventario → `stock.quant` (write con quantity y location_id)

{action_templates}

{formatted_context}

<|user|>"""
        
        return system_content

    def build_final_prompt(self, system_prompt, user_query, include_reminder=True):
        """
        Construye el prompt final con recordatorio anti-alucinación.
        """
        reminder = ""
        if include_reminder:
            reminder = "\n\n🔍 RECUERDA: Basa tu respuesta ÚNICAMENTE en los datos proporcionados. NO uses ejemplos anteriores como fuente de datos."
        
        return f"{system_prompt}\n{user_query}{reminder}\n<|assistant|>"
    
    def get_debug_prompt_summary(self, context_str, model_name, output_style):
        """
        Utilidad para depuración: muestra qué recibirá el LLM.
        """
        primary_model = model_name if model_name in self.model_expertise else False
        
        # Analizar contexto para IDs reales
        import re
        real_ids = re.findall(r'\[(\d+)\]', context_str)
        
        return {
            'primary_model': primary_model,
            'expertise': self.model_expertise.get(primary_model, 'Generalista'),
            'style': output_style,
            'context_length': len(context_str),
            'real_ids_in_context': list(set(real_ids))[:10],  # IDs únicos, máximo 10
            'context_preview': context_str[:150] + "..." if len(context_str) > 150 else context_str,
            'has_action_templates': primary_model in ['mrp.production', 'sale.order', 'product.product']
        }

    def validate_context_ids(self, context_str, proposed_action):
        """
        Validación simple: verifica que los IDs de la acción propuesta estén en el contexto.
        Para usar en ResponseParser o ActionValidator.
        """
        import re
        import json
        
        # Extraer IDs del contexto
        context_ids = set(re.findall(r'\[(\d+)\]', context_str))
        
        # Extraer IDs de la acción propuesta
        action_ids = []
        if isinstance(proposed_action, str):
            try:
                action_data = json.loads(proposed_action)
                # Buscar IDs en los valores del diccionario
                def extract_ids(obj):
                    ids = []
                    if isinstance(obj, dict):
                        for v in obj.values():
                            if isinstance(v, int):
                                ids.append(str(v))
                            elif isinstance(v, (dict, list)):
                                ids.extend(extract_ids(v))
                    elif isinstance(obj, list):
                        for item in obj:
                            ids.extend(extract_ids(item))
                    return ids
                action_ids = extract_ids(action_data.get('vals', {}))
            except:
                pass
        
        # Verificar coincidencias
        missing_ids = [id for id in action_ids if id not in context_ids]
        return {
            'is_valid': len(missing_ids) == 0,
            'missing_ids': missing_ids,
            'context_ids': list(context_ids)[:20]
        }