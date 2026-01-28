# -*- coding: utf-8 -*-
import logging
from datetime import date, datetime
from odoo import fields

_logger = logging.getLogger(__name__)

class ContextService:
    def __init__(self, env):
        self.env = env

    def get_context(self, session, user_query=""):
        """Orquesta la obtención de contexto INTELIGENTE basado en sesión y consulta."""
        # 1. Prioridad: context_ref si existe
        if hasattr(session, 'message_ids') and session.message_ids:
            last_msg = session.message_ids.sorted('create_date', reverse=True)[0]
            if last_msg.context_ref:
                return self._get_context_from_ref(last_msg.context_ref)

        # 2. Determinar modelo a consultar
        model_to_read = session.model_id.model if session.model_id else False
        
        if model_to_read == 'qdrant':
            return self._get_vector_context(session, user_query)

        # 3. Inferir modelo de la consulta si no hay explícito
        if not model_to_read:
            model_to_read = self._infer_model_from_query(user_query)
            if not model_to_read:
                return "⚠️ No se pudo determinar el contexto. Por favor, especifica sobre qué datos necesitas información."

        # 4. Obtener datos RELEVANTES de Odoo
        return self._get_odoo_context(model_to_read, session, user_query)

    def _get_context_from_ref(self, context_ref):
        """Obtiene datos de un registro específico."""
        try:
            record = context_ref
            if not record.exists():
                return f"⚠️ Referencia {record._name}[{record.id}] no encontrada."
            
            context_lines = [f"📌 REGISTRO ESPECÍFICO: {record._name} [{record.id}]"]
            context_lines.append(f"   • Nombre/Referencia: {record.display_name or record.name or 'N/A'}")
            
            # Campos específicos por modelo
            if record._name == 'mrp.production':
                context_lines.append(f"   • Producto: {record.product_id.display_name} [{record.product_id.id}]")
                context_lines.append(f"   • Cantidad: {record.product_qty} {record.product_uom_id.name}")
                context_lines.append(f"   • Estado: {record.state}")
                context_lines.append(f"   • Fecha Inicio: {record.date_planned_start or 'No planificada'}")
                context_lines.append(f"   • Fecha Fin: {record.date_deadline or 'No planificada'}")
                
                # Componentes críticos
                critical_components = []
                for move in record.move_raw_ids.filtered(lambda m: m.state not in ['done', 'cancel']):
                    available = move.product_id.qty_available
                    needed = move.product_uom_qty
                    if available < needed:
                        critical_components.append(f"      - {move.product_id.display_name} [{move.product_id.id}]: {available}/{needed} unidades")
                
                if critical_components:
                    context_lines.append("   • ⚠️ COMPONENTES INSUFICIENTES:")
                    context_lines.extend(critical_components)
                    
            elif record._name == 'sale.order':
                context_lines.append(f"   • Cliente: {record.partner_id.display_name} [{record.partner_id.id}]")
                context_lines.append(f"   • Total: {record.amount_total:.2f} {record.currency_id.name}")
                context_lines.append(f"   • Estado: {record.state}")
                context_lines.append(f"   • Fecha: {record.date_order}")
                
                if record.order_line:
                    context_lines.append("   • Líneas del pedido:")
                    for line in record.order_line[:5]:
                        context_lines.append(f"      - {line.product_id.display_name}: {line.product_uom_qty} x {line.price_unit:.2f}")
            
            elif record._name == 'product.product':
                context_lines.append(f"   • Referencia: {record.default_code or 'N/A'}")
                context_lines.append(f"   • Precio Venta: {record.list_price:.2f}")
                context_lines.append(f"   • Coste Estándar: {record.standard_price:.2f}")
                context_lines.append(f"   • Stock Actual: {record.qty_available}")
            
            return "\n".join(context_lines)
            
        except Exception as e:
            _logger.error("Error obteniendo contexto de referencia: %s", str(e))
            return f"Error procesando la referencia."

    def _infer_model_from_query(self, query):
        """Infere el modelo de Odoo basado en palabras clave de la consulta."""
        if not query:
            return False
            
        query_lower = query.lower()
        
        # Mapeo de palabras clave a modelos
        keyword_to_model = {
            'mrp.production': ['orden de fabricación', 'orden fabricación', 'producción', 'mrp', 'manufactura', 'retrasada', 'retraso', 'fabricar'],
            'sale.order': ['venta', 'cotización', 'pedido cliente', 'cliente', 'comercial', 'presupuesto', 'oferta'],
            'product.product': ['producto', 'artículo', 'ítem', 'sku', 'crear producto', 'nuevo producto'],
            'stock.quant': ['stock', 'inventario', 'almacén', 'existencia', 'cantidad', 'disponible'],
            'purchase.order': ['compra', 'proveedor', 'pedido proveedor', 'orden compra'],
            'project.task': ['tarea', 'proyecto', 'actividad', 'sprint', 'asignar tarea'],
            'mail.message': ['correo', 'email', 'mensaje', 'comunicación', 'correspondencia'],
        }
        
        for model, keywords in keyword_to_model.items():
            if any(keyword in query_lower for keyword in keywords):
                _logger.info("Modelo inferido para '%s': %s", query[:50], model)
                return model
        
        return False

    def _get_odoo_context(self, model_name, session, user_query=""):
        """Extrae datos RELEVANTES de Odoo basados en consulta."""
        try:
            # Verificar que el modelo existe
            if model_name not in self.env:
                return f"❌ Modelo '{model_name}' no disponible."
            
            # Construir dominio dinámico
            domain = self._build_dynamic_domain(model_name, user_query)
            
            # Obtener campos relevantes
            fields_to_get = self._get_relevant_fields(model_name, user_query)
            
            # Determinar límite según consulta
            limit = self._determine_limit(model_name, user_query)
            
            # Buscar registros
            records = self.env[model_name].search(domain, limit=limit, order='create_date desc')
            
            if not records:
                return f"ℹ️ No se encontraron registros en {model_name} que coincidan con la búsqueda."
            
            # Formatear para LLM
            return self._format_records_for_llm(records, model_name, fields_to_get, user_query)
            
        except Exception as e:
            _logger.error("Error obteniendo contexto de %s: %s", model_name, str(e))
            return f"Error técnico obteniendo datos de {model_name}."

    def _build_dynamic_domain(self, model_name, user_query):
        """Construye filtros inteligentes basados en la consulta."""
        query_lower = user_query.lower() if user_query else ""
        domain = []
        today = date.today()
        
        if model_name == 'mrp.production':
            if any(word in query_lower for word in ['retrasada', 'retraso', 'atrasada', 'tarde']):
                # Órdenes con fecha pasada y no terminadas
                domain = [
                    ('date_deadline', '<', today),
                    ('state', 'not in', ['done', 'cancel'])
                ]
            elif any(word in query_lower for word in ['hoy', 'para hoy']):
                domain = [('date_planned_start', '=', today)]
            elif any(word in query_lower for word in ['esta semana', 'semana actual']):
                next_week = today.replace(day=today.day + 7)
                domain = [('date_planned_start', '>=', today), ('date_planned_start', '<=', next_week)]
            else:
                # Por defecto: órdenes activas recientes
                domain = [('state', 'in', ['confirmed', 'progress'])]
                
        elif model_name == 'sale.order':
            if any(word in query_lower for word in ['pendiente', 'por confirmar']):
                domain = [('state', 'in', ['draft', 'sent'])]
            elif any(word in query_lower for word in ['este mes', 'mes actual']):
                first_day = today.replace(day=1)
                domain = [('date_order', '>=', first_day)]
            elif any(word in query_lower for word in ['urgente', 'prioridad']):
                domain = [('priority', '=', '1')]
                
        elif model_name == 'product.product':
            if query_lower and len(query_lower) > 2:
                # Buscar productos por nombre o referencia
                domain = ['|', ('name', 'ilike', query_lower), ('default_code', 'ilike', query_lower)]
        
        return domain

    def _get_relevant_fields(self, model_name, user_query):
        """Devuelve campos relevantes según modelo y consulta."""
        base_fields = ['name', 'display_name']
        
        field_map = {
            'mrp.production': base_fields + ['product_id', 'product_qty', 'date_planned_start', 
                                           'date_deadline', 'state', 'qty_producing'],
            'sale.order': base_fields + ['partner_id', 'date_order', 'amount_total', 'state', 
                                       'amount_untaxed', 'user_id', 'priority'],
            'product.product': base_fields + ['default_code', 'list_price', 'standard_price', 
                                            'qty_available', 'categ_id', 'type'],
            'stock.quant': ['product_id', 'location_id', 'quantity', 'reserved_quantity', 
                          'inventory_quantity', 'lot_id'],
            'purchase.order': base_fields + ['partner_id', 'date_order', 'amount_total', 'state'],
            'project.task': base_fields + ['project_id', 'user_id', 'date_deadline', 'stage_id', 
                                         'priority', 'planned_hours'],
        }
        
        return field_map.get(model_name, base_fields + ['id'])

    def _determine_limit(self, model_name, user_query):
        """Determina límite de registros según tipo de consulta."""
        query_lower = user_query.lower() if user_query else ""
        
        if any(word in query_lower for word in ['todos', 'todas', 'listar todos', 'listar todas']):
            return 20
        elif any(word in query_lower for word in ['reciente', 'último', 'última']):
            return 3
        elif 'retrasada' in query_lower and model_name == 'mrp.production':
            return 10  # Para ver todas las retrasadas
        else:
            return 6  # Límite por defecto

    def _format_records_for_llm(self, records, model_name, fields, user_query):
        """Formatea registros de forma CLARA y ÚTIL para el LLM."""
        lines = []
        today = date.today()
        
        # Título contextual
        if any(word in (user_query or "").lower() for word in ['retrasada', 'retraso']):
            lines.append("🚨 ÓRDENES DE FABRICACIÓN RETRASADAS")
            lines.append("(Fecha de finalización planificada YA PASADA)")
        elif model_name == 'mrp.production':
            lines.append("🏭 ÓRDENES DE FABRICACIÓN")
        elif model_name == 'sale.order':
            lines.append("💰 PEDIDOS DE VENTA")
        else:
            lines.append(f"📦 DATOS DE {model_name.upper()}")
        
        lines.append(f"Registros encontrados: {len(records)}")
        lines.append("-" * 40)
        
        for rec in records:
            # Línea principal con ID entre corchetes
            main_info = f"[{rec.id}]"
            if hasattr(rec, 'display_name') and rec.display_name:
                main_info += f" {rec.display_name}"
            elif hasattr(rec, 'name') and rec.name:
                main_info += f" {rec.name}"
            
            lines.append(f"• {main_info}")
            
            # Campos específicos
            field_count = 0
            for field_name in fields:
                if field_name in ['name', 'display_name', 'id']:
                    continue
                    
                if field_name in rec._fields and rec[field_name]:
                    field = rec._fields[field_name]
                    value = rec[field_name]
                    
                    # Formatear según tipo de campo
                    if field.type == 'many2one':
                        if value and hasattr(value, 'display_name'):
                            field_display = f"{value.display_name} [{value.id}]"
                        else:
                            field_display = f"ID {value}" if value else "-"
                    elif field.type in ['date', 'datetime']:
                        # Resaltar fechas pasadas para órdenes de fabricación
                        if model_name == 'mrp.production' and field_name == 'date_deadline':
                            if value and value < today:
                                field_display = f"⚠️ {value} (RETRASADA)"
                            else:
                                field_display = str(value)
                        else:
                            field_display = str(value)
                    elif field.type in ['float', 'monetary']:
                        field_display = f"{value:,.2f}"
                    else:
                        field_display = str(value)
                    
                    lines.append(f"  ├ {field.string or field_name}: {field_display}")
                    field_count += 1
                    
                    if field_count >= 3:  # Máximo 3 campos adicionales
                        break
            
            lines.append("")  # Espacio entre registros
        
        # Añadir resumen si es relevante
        if model_name == 'mrp.production':
            retrasadas = len([r for r in records if r.date_deadline and r.date_deadline < today])
            if retrasadas > 0:
                lines.append(f"📊 RESUMEN: {retrasadas} de {len(records)} órdenes están retrasadas.")
        
        return "\n".join(lines)

    def _get_vector_context(self, session, user_query):
        """Contexto para búsqueda vectorial."""
        config = self.env['ai.vector.config'].search([('active', '=', True)], limit=1)
        if not config:
            return "ℹ️ Búsqueda vectorial (Qdrant) no configurada."
        
        return f"🔍 Búsqueda semántica activada para: '{user_query}'\nColección: {config.collection_name}\n(Integración en desarrollo)"