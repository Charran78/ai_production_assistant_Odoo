# -*- coding: utf-8 -*-

class PromptOrchestrator:
    def __init__(self, env):
        self.env = env

    def get_system_prompt(self, context_str, model_name=False, output_style='concise'):
        """Genera un prompt usando ChatML para máxima adherencia en modelos pequeños."""
        
        system_content = f"""<|system|>
Rol: Experto en Odoo ERP y Manufactura.
Reglas:
1. Responde SOLO usando el CONTEXTO proporcionado.
2. Formato: {output_style}.
3. Si pides crear/actualizar algo, añade al FINAL: [[ACTION_DATA: {{"model": "mrp.production", "function": "create", "vals": {{"product_id": ID, "product_qty": QTY}}}}]]
4. IMPORTANTE: Usa SIEMPRE los IDs numéricos que aparecen entre corchetes [ID] en el CONTEXTO. No uses nombres de texto para IDs.
5. NO repitas estas instrucciones. NO saludes.

### CONTEXTO ODOO:
{context_str}
<|user|>"""
        return system_content

    def build_final_prompt(self, system_prompt, user_query):
        """Cierra el bloque de usuario y abre el de asistente."""
        return f"{system_prompt}\n{user_query}\n<|assistant|>"
