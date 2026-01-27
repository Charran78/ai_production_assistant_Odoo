# -*- coding: utf-8 -*-
import logging

_logger = logging.getLogger(__name__)

class ContextService:
    def __init__(self, env):
        self.env = env

    def get_context(self, session):
        """Orquesta la obtención de contexto."""
        model_to_read = session.model_id.model if session.model_id else False
        
        if model_to_read == 'qdrant':
            return self._get_vector_context(session)

        if not model_to_read:
            return "No hay contexto específico. Responde de forma general sobre Odoo."

        return self._get_odoo_context(model_to_read, session.name)

    def _get_odoo_context(self, model_name, query_text):
        """
        Extrae datos de Odoo refinados por el query_text (título de sesión).
        """
        try:
            # MEJORA: Búsqueda más inteligente si el query_text es descriptivo
            domain = []
            if query_text and len(query_text) > 3:
                # Intentar buscar por nombre si el modelo lo tiene
                Model = self.env[model_name]
                if 'name' in Model._fields:
                    domain = ['|', ('name', 'ilike', query_text), ('display_name', 'ilike', query_text)]
            
            if model_name == 'mail.message':
                domain = [('message_type', 'in', ['email', 'comment']), ('model', '!=', False)]
            
            # Buscar registros con el dominio inteligente o caer en los últimos 15
            records = self.env[model_name].search(domain, limit=15, order='id desc')
            
            # Si no hay resultados con el filtro, traer los últimos registros generales
            if not records and domain:
                records = self.env[model_name].search([], limit=15, order='id desc')

            if not records:
                return f"El modelo {model_name} no tiene datos actuales."

            data_list = []
            for rec in records:
                # MEJORA: Siempre incluir el ID técnico de forma explícita para el LLM
                info_parts = [f"[{rec.id}] {rec.display_name or 'Sin Nombre'}"]
                relevant_fields = []
                # Priorizar campos importantes según el tipo
                for fname, field in rec._fields.items():
                    if fname in ['display_name', 'id', 'create_date', 'write_date']: continue
                    if field.type in ['char', 'selection', 'float', 'monetary', 'date', 'datetime', 'text', 'many2one']:
                        val = rec[fname]
                        if val:
                            label = field.string or fname
                            if field.type == 'many2one':
                                val = val.display_name
                            if field.type == 'text' and len(str(val)) > 100:
                                val = str(val)[:100] + "..."
                            relevant_fields.append(f"{label}: {val}")
                
                # Limitar campos por registro para no saturar el prompt
                info_parts.extend(relevant_fields[:6])
                data_list.append(" | ".join(info_parts))

            return f"Contexto de {model_name}:\n- " + "\n- ".join(data_list)
        except Exception as e:
            _logger.error("Error leyendo contexto de Odoo: %s", str(e))
            return f"Error leyendo datos del modelo {model_name}."

    def _get_vector_context(self, session):
        """Placeholder para búsqueda vectorial."""
        config = self.env['ai.vector.config'].search([('active', '=', True)], limit=1)
        if not config:
            return "Qdrant no está configurado."
        return f"Buscando en Qdrant ({config.collection_name}) para: {session.name}...\n(Integración vectorial en progreso)"
