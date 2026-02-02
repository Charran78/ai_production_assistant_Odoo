# -*- coding: utf-8 -*-
import json
import re


class ResponseParser:
    ACTION_PATTERN = r"\[\[ACTION_DATA:\s*(.*?)\s*\]\]"

    def parse_actions(self, raw_text):
        """
        Extrae bloques [[ACTION_DATA: {...}]] del texto.
        Retorna: (clean_text, action_list)
        """
        actions = []
        clean_text = raw_text

        if not raw_text:
            return "", []

        # Buscar todos los bloques de acción
        matches = re.findall(self.ACTION_PATTERN, raw_text, re.DOTALL)
        for match in matches:
            try:
                action_data = json.loads(match)
                if isinstance(action_data, dict):
                    actions.append(action_data)
            except json.JSONDecodeError:
                continue

        # Eliminar los bloques del texto mostrado al usuario
        clean_text = re.sub(
            self.ACTION_PATTERN, "", clean_text, flags=re.DOTALL
        ).strip()
        return clean_text, actions

    def format_html(self, text):
        """Convierte texto plano a HTML simple para Odoo."""
        if not text:
            return ""
        # Saltos de línea a <br/>
        html = text.replace("\n", "<br/>")
        # Resaltar bloques de código
        html = re.sub(
            r"```(.*?)```", r"<pre><code>\1</code></pre>", html, flags=re.DOTALL
        )
        return html
