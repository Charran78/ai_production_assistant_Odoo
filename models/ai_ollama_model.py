# -*- coding: utf-8 -*-
import json
import logging

import requests

from odoo import models, fields, api
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class AIOllamaModel(models.Model):
    _name = "ai.ollama.model"
    _description = "Modelo de Ollama (Catálogo)"
    _order = "name asc"

    # Nombre visible en la interfaz
    display_name = fields.Char(
        string="Nombre para mostrar", compute="_compute_display_name", store=True
    )

    # Nombre técnico en Ollama (el que se usa en la API)
    name = fields.Char(
        string="Nombre técnico",
        required=True,
        index=True,
        help="Nombre exacto en Ollama. Ej: 'llama3.2', 'mistral', 'phi3:mini'",
    )

    # Nombre personalizado opcional para variantes
    custom_suffix = fields.Char(
        string="Sufijo personalizado",
        help="Sufijo para crear variante. Ej: '-produccion' para 'llama3.2-produccion'",
    )

    # Propiedades del modelo
    is_custom = fields.Boolean(
        string="Es personalizado",
        compute="_compute_is_custom",
        store=True,
        help="True si fue creado con 'ollama create' o tiene sufijo personalizado",
    )

    size_mb = fields.Float(string="Tamaño (MB)", readonly=True, digits=(16, 2))
    details = fields.Text(string="Detalles técnicos", readonly=True)
    active = fields.Boolean(string="Activo", default=True)
    sequence = fields.Integer(string="Orden", default=10)

    # Modelfile para creación de variantes
    modelfile = fields.Text(
        string="Modelfile personalizado",
        help="Contenido del Modelfile para crear una variante especializada con 'ollama create'",
    )

    # Parámetros de generación
    max_tokens = fields.Integer(
        string="Tokens máximos",
        default=2048,
        help="Máximo número de tokens en la respuesta",
    )

    temperature = fields.Float(
        string="Temperatura",
        default=0.7,
        help="Controla la aleatoriedad (0.0 = determinístico, 1.0 = creativo)",
    )

    top_p = fields.Float(
        default=0.9,
        help="Controla la diversidad mediante nucleus sampling",
    )

    # Especializaciones (para filtros en wizard)
    is_production_optimized = fields.Boolean(
        string="Optimizado para producción", default=False
    )

    is_sales_optimized = fields.Boolean(string="Optimizado para ventas", default=False)

    is_general_purpose = fields.Boolean(string="Propósito general", default=True)

    # Estadísticas
    usage_count = fields.Integer(string="Veces usado", default=0, readonly=True)
    last_used = fields.Datetime(string="Último uso", readonly=True)

    # Relación con el modelo de configuración
    config_id = fields.Many2one("ai.ollama.config", string="Configuración Ollama")

    @api.depends("name", "custom_suffix")
    def _compute_display_name(self):
        """Genera un nombre amigable para mostrar en la interfaz."""
        for rec in self:
            base_name = rec.name.split(":")[0]  # Remover tag si existe
            if rec.custom_suffix:
                rec.display_name = f"{base_name}{rec.custom_suffix}"
            else:
                rec.display_name = base_name

    @api.depends("custom_suffix", "modelfile")
    def _compute_is_custom(self):
        """Determina si es un modelo personalizado."""
        for rec in self:
            rec.is_custom = bool(rec.custom_suffix) or bool(rec.modelfile)

    @api.constrains("name")
    def _check_name_format(self):
        """Valida que el nombre sea compatible con Ollama."""
        for rec in self:
            if not rec.name or len(rec.name.strip()) < 2:
                raise ValidationError(
                    self.env._("El nombre del modelo debe tener al menos 2 caracteres.")
                )

    def action_sync_with_ollama(self):
        """Sincroniza este modelo específico con Ollama para obtener detalles."""
        self.ensure_one()

        config = self.env["ir.config_parameter"].sudo()
        ollama_url = config.get_param("ai.ollama_url", "http://localhost:11434")
        url = f"{ollama_url.rstrip('/')}/api/show"

        payload = {"name": self.name}

        try:
            response = requests.post(url, json=payload, timeout=10)
            response.raise_for_status()
            data = response.json()

            # Actualizar detalles
            self.write(
                {
                    "size_mb": data.get("size", 0) / (1024 * 1024),  # Bytes a MB
                    "details": json.dumps(
                        {
                            "format": data.get("format"),
                            "family": data.get("family"),
                            "parameter_size": data.get("parameter_size"),
                            "quantization_level": data.get("quantization_level"),
                        },
                        indent=2,
                        ensure_ascii=False,
                    ),
                }
            )

            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": self.env._("Sincronización exitosa"),
                    "message": self.env._("Detalles del modelo actualizados"),
                    "type": "success",
                    "sticky": False,
                },
            }

        except requests.exceptions.ConnectionError as exc:
            raise UserError(
                self.env._("No se pudo conectar al servidor Ollama.")
            ) from exc
        except Exception as e:
            raise UserError(
                self.env._("Error sincronizando modelo: %s") % str(e)
            ) from e

    def action_create_custom_variant(self):
        """Crea una variante personalizada del modelo en Ollama."""
        self.ensure_one()

        if not self.modelfile:
            raise UserError(
                self.env._(
                    "Se requiere un Modelfile para crear una variante personalizada."
                )
            )

        if not self.custom_suffix:
            raise UserError(
                self.env._("Se requiere un sufijo personalizado para la variante.")
            )

        config = self.env["ir.config_parameter"].sudo()
        ollama_url = config.get_param("ai.ollama_url", "http://localhost:11434")
        url = f"{ollama_url.rstrip('/')}/api/create"

        # Nombre de la variante: modelo_base-sufijo
        variant_name = f"{self.name.split(':')[0]}{self.custom_suffix}"

        # Modelfile con FROM explícito
        full_modelfile = f"FROM {self.name}\n{self.modelfile}"

        payload = {"name": variant_name, "modelfile": full_modelfile, "stream": False}

        try:
            _logger.info("Creando variante personalizada: %s", variant_name)
            response = requests.post(
                url, json=payload, timeout=300
            )  # 5 minutos timeout

            if response.status_code != 200:
                raise UserError(
                    self.env._("Ollama respondió con error: %s") % response.text
                )

            self.name = variant_name

            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": self.env._("Variante creada"),
                    "message": self.env._(
                        'Modelo personalizado "%s" creado exitosamente.'
                    )
                    % variant_name,
                    "type": "success",
                    "sticky": False,
                },
            }

        except requests.exceptions.ConnectionError as exc:
            raise UserError(
                self.env._("No se pudo conectar al servidor Ollama.")
            ) from exc
        except Exception as e:
            raise UserError(self.env._("Error creando variante: %s") % str(e)) from e

    def action_pull_model(self):
        """Descarga el modelo desde Ollama Hub si no está disponible localmente."""
        self.ensure_one()

        config = self.env["ir.config_parameter"].sudo()
        ollama_url = config.get_param("ai.ollama_url", "http://localhost:11434")
        url = f"{ollama_url.rstrip('/')}/api/pull"

        payload = {"name": self.name, "stream": False}

        try:
            response = requests.post(
                url, json=payload, timeout=600
            )  # 10 minutos timeout

            if response.status_code != 200:
                raise UserError(
                    self.env._("Ollama respondió con error: %s") % response.text
                )

            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": self.env._("Descarga iniciada"),
                    "message": self.env._(
                        'La descarga del modelo "%s" ha comenzado. Revisa los logs de Ollama.'
                    )
                    % self.name,
                    "type": "warning",
                    "sticky": False,
                },
            }

        except requests.exceptions.ConnectionError as exc:
            raise UserError(
                self.env._("No se pudo conectar al servidor Ollama.")
            ) from exc
        except Exception as e:
            raise UserError(
                self.env._("Error iniciando descarga: %s") % str(e)
            ) from e

    @api.model
    def action_sync_all_models(self):
        """Sincroniza todos los modelos disponibles en Ollama (acción global)."""
        config = self.env["ir.config_parameter"].sudo()
        ollama_url = config.get_param("ai.ollama_url", "http://localhost:11434")
        url = f"{ollama_url.rstrip('/')}/api/tags"

        _logger.info("Sincronizando todos los modelos desde %s", url)

        try:
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            data = response.json()
            models_data = data.get("models", [])

            existing_models = {m.name: m for m in self.search([])}
            fetched_names = set()

            for model_info in models_data:
                name = model_info.get("name")
                if not name:
                    continue

                fetched_names.add(name)
                size = model_info.get("size", 0) / (1024 * 1024)  # Bytes a MB

                if name in existing_models:
                    existing_models[name].write({"size_mb": size, "active": True})
                else:
                    self.create(
                        {
                            "name": name,
                            "size_mb": size,
                            "details": json.dumps(
                                model_info, indent=2, ensure_ascii=False
                            ),
                        }
                    )

            # Desactivar modelos que ya no existen en Ollama
            missing = set(existing_models.keys()) - fetched_names
            for name in missing:
                existing_models[name].write({"active": False})

            model_count = len(models_data)
            _logger.info(
                "Sincronización completada. %s modelos encontrados.", model_count
            )

            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": self.env._("Sincronización completada"),
                    "message": self.env._("%s modelos sincronizados desde Ollama.")
                    % model_count,
                    "type": "success",
                    "sticky": False,
                },
            }

        except requests.exceptions.ConnectionError as exc:
            _logger.error("No se pudo conectar a Ollama en %s", url)
            raise UserError(
                self.env._(
                    "No se pudo conectar con Ollama. Verifica que el servidor esté ejecutándose en %s."
                )
                % ollama_url
            ) from exc
        except Exception as e:
            _logger.exception("Error inesperado sincronizando modelos")
            raise UserError(
                self.env._("Error sincronizando modelos: %s") % str(e)
            ) from e

    def increment_usage(self):
        """Incrementa el contador de uso y actualiza la última fecha de uso."""
        self.write(
            {"usage_count": self.usage_count + 1, "last_used": fields.Datetime.now()}
        )

    @api.model
    def get_default_models(self):
        """Crea modelos por defecto si no existen (para post_init_hook)."""
        default_models = [
            {
                "name": "llama3.2",
                "display_name": "Llama 3.2",
                "max_tokens": 4096,
                "temperature": 0.7,
                "is_general_purpose": True,
                "sequence": 10,
            },
            {
                "name": "mistral",
                "display_name": "Mistral 7B",
                "max_tokens": 8192,
                "temperature": 0.8,
                "is_general_purpose": True,
                "is_production_optimized": True,
                "sequence": 20,
            },
            {
                "name": "phi3:mini",
                "display_name": "Phi-3 Mini",
                "max_tokens": 2048,
                "temperature": 0.7,
                "is_general_purpose": True,
                "sequence": 30,
            },
            {
                "name": "codellama",
                "display_name": "Code Llama",
                "max_tokens": 4096,
                "temperature": 0.2,
                "is_general_purpose": True,
                "sequence": 40,
            },
        ]

        for model_data in default_models:
            existing = self.search([("name", "=", model_data["name"])], limit=1)
            if not existing:
                self.create(model_data)
                _logger.info("Modelo por defecto creado: %s", model_data["name"])
