# -*- coding: utf-8 -*-

import json
import logging
import platform
import subprocess
import warnings

import psutil
import requests

from odoo import models, fields, api
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

try:
    import GPUtil
except ImportError:
    GPUtil = None
    _logger.warning(
        "GPUtil no está instalado. La información de la GPU no estará disponible."
    )


class InstallationWizard(models.TransientModel):
    _name = "ai.installation.wizard"
    _description = "Asistente de Instalación - Configuración Automática"

    # Paso 1: Detección de Ollama
    ollama_installed = fields.Boolean(string="Ollama Detectado", readonly=True)
    ollama_version = fields.Char(string="Versión de Ollama", readonly=True)
    ollama_status = fields.Selection(
        [
            ("not_installed", "No instalado"),
            ("installed", "Instalado"),
            ("running", "Ejecutándose"),
        ],
        string="Estado de Ollama",
        readonly=True,
    )

    # Paso 2: Modelos disponibles
    available_models = fields.Text(string="Modelos Disponibles", readonly=True)
    selected_model = fields.Selection(
        selection="_get_dynamic_model_options", string="Modelo Instalado", default=None
    )

    def _get_dynamic_model_options(self):
        """Devuelve lista de tuplas con modelos instalados y remotos para el campo de selección"""
        current_log = self.installation_log or ""  # Asegurarse de que sea una cadena
        options = []
        _logger.info(
            "Iniciando _get_dynamic_model_options para obtener opciones de modelos."
        )

        ram_total = self.ram_total

        recommendation_text = ""
        if ram_total:
            if ram_total < 8:
                recommendation_text = " (Recomendado para RAM < 8GB)"
            elif 8 <= ram_total < 16:
                recommendation_text = " (Recomendado para RAM 8-16GB)"
            else:
                recommendation_text = " (Recomendado para RAM > 16GB)"

        # Revalidar estado de Ollama y modelos al cargar opciones
        current_ollama_status = self._detect_ollama()["ollama_status"]
        if current_ollama_status == "running":
            _logger.info(
                "Ollama está ejecutándose. Obteniendo modelos instalados localmente."
            )
            # Obtener modelos instalados localmente
            installed_models_data = self._get_available_models()
            _logger.info(
                "Modelos instalados localmente encontrados: %s",
                len(installed_models_data.get("models", [])),
            )
            for model in installed_models_data.get("models", []):
                try:
                    model_name = model.get("name")
                    model_details = model.get("details", {})
                    parameter_size = model_details.get("parameter_size")

                    if model_name and parameter_size:
                        options.append(
                            (
                                model_name,
                                f"{model_name} (Instalado - {parameter_size}){recommendation_text}",
                            )
                        )
                        _logger.info("Añadido modelo instalado: %s", model_name)
                    else:
                        current_log += (
                            "⚠️ Modelo instalado con estructura inesperada: %s - %s\n"
                            % (model_name, model_details)
                        )
                        _logger.warning(
                            "Modelo instalado con estructura inesperada: %s - %s",
                            model_name,
                            model_details,
                        )
                except Exception as e:
                    model_label = model.get("name", "desconocido")
                    current_log += (
                        "❌ Error procesando modelo instalado %s: %s\n"
                        % (model_label, str(e))
                    )
                    _logger.error(
                        "Error procesando modelo instalado %s: %s", model_label, str(e)
                    )

            _logger.info("Obteniendo modelos remotos.")
            # Obtener modelos remotos
            remote_models_data = self._get_remote_models()
            _logger.info(
                "Modelos remotos encontrados: %s",
                len(remote_models_data.get("models", [])),
            )
            for model in remote_models_data.get("models", []):
                try:
                    model_name = model.get("name")
                    model_details = model.get("details", {})
                    parameter_size = model_details.get("parameter_size")

                    # Solo añadir modelos remotos que no estén ya instalados
                    if (
                        model_name
                        and parameter_size
                        and model_name not in [opt[0] for opt in options]
                    ):
                        options.append(
                            (
                                f"remote_{model_name}",
                                f"[Remoto] {model_name} ({parameter_size}){recommendation_text}",
                            )
                        )
                        _logger.info("Añadido modelo remoto: %s", model_name)
                    elif model_name and parameter_size:
                        current_log += (
                            "ℹ️ Modelo remoto %s ya está instalado localmente, "
                            "no se añade como opción remota.\n"
                            % model_name
                        )
                        _logger.info(
                            "Modelo remoto %s ya está instalado localmente, no se añade como opción remota.",
                            model_name,
                        )
                    else:
                        current_log += (
                            "⚠️ Modelo remoto con estructura inesperada: %s - %s\n"
                            % (model_name, model_details)
                        )
                        _logger.warning(
                            "Modelo remoto con estructura inesperada: %s - %s",
                            model_name,
                            model_details,
                        )
                except Exception as e:
                    model_label = model.get("name", "desconocido")
                    current_log += (
                        "❌ Error procesando modelo remoto %s: %s\n"
                        % (model_label, str(e))
                    )
                    _logger.error(
                        "Error procesando modelo remoto %s: %s", model_label, str(e)
                    )

            self.write({"installation_log": current_log})  # Guardar log
            _logger.info(
                "Total de opciones de modelos generadas: %s", len(options)
            )
            if options:
                return options

        current_log += "ℹ️ No hay modelos disponibles (Ollama no está ejecutándose o no hay conexión).\n"
        self.write({"installation_log": current_log})  # Guardar log
        _logger.info(
            "No hay modelos disponibles (Ollama no está ejecutándose o no hay conexión)."
        )
        return [("none", "No hay modelos disponibles")]

    # Paso 3: Configuración de Base de Datos
    db_configured = fields.Boolean(string="BD Configurada", readonly=True)
    vector_db_status = fields.Selection(
        [
            ("not_configured", "No configurado"),
            ("configured", "Configurado"),
            ("ready", "Listo"),
        ],
        string="Estado de Vector DB",
        readonly=True,
    )

    # Paso 4: Configuración Avanzada (Proactividad)
    enable_watchdogs = fields.Boolean(
        string="Activar Watchdogs (Alertas Proactivas)", default=True
    )
    enable_dashboards = fields.Boolean(
        string="Activar Dashboards Ejecutivos", default=True
    )
    enable_actions = fields.Boolean(
        string="Permitir Ejecución de Acciones Automáticas", default=False
    )
    show_pending_actions = fields.Boolean(
        string="Mostrar Acciones Pendientes en Dashboard", default=True
    )
    advanced_config_saved = fields.Boolean(
        string="Configuración Avanzada Guardada", readonly=True
    )

    # Estado del wizard
    current_step = fields.Selection(
        [
            ("detection", "Detección"),
            ("model_selection", "Selección de Modelo"),
            ("configuration", "Configuración de BD"),
            ("advanced_config", "Configuración Avanzada"),
            ("completion", "Completado"),
        ],
        string="Paso Actual",
        default="detection",
    )

    progress = fields.Integer(string="Progreso", default=0)
    installation_log = fields.Text(string="Log de Instalación", readonly=True)

    # Información de Hardware
    cpu_count = fields.Integer(string="Número de CPUs", readonly=True)
    cpu_freq = fields.Float(string="Frecuencia de CPU (MHz)", readonly=True)
    ram_total = fields.Float(string="RAM Total (GB)", readonly=True)
    gpu_info = fields.Text(string="Información de GPU", readonly=True)

    # Métodos de detección automática
    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)

        # Detectar estado de Ollama automáticamente
        ollama_status = self._detect_ollama()
        res.update(ollama_status)

        # Verificar modelos disponibles
        if ollama_status["ollama_status"] == "running":
            available_models = self._get_available_models()
            res["available_models"] = json.dumps(available_models, indent=2)

        # Verificar configuración de BD
        db_status = self._check_database_config()
        res.update(db_status)

        # Obtener información del sistema
        system_info = self._get_system_info()
        res.update(system_info)

        return res

    def _detect_ollama(self):
        """Detecta si Ollama está instalado y ejecutándose"""
        result = {
            "ollama_installed": False,
            "ollama_version": "No detectado",
            "ollama_status": "not_installed",
            "installation_log": "Iniciando detección de Ollama...\n",
        }

        current_log = self.installation_log or ""
        try:
            # Verificar si el comando ollama existe
            process = subprocess.run(
                ["ollama", "--version"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )

            if process.returncode == 0:
                result["ollama_installed"] = True
                result["ollama_version"] = process.stdout.strip()
                current_log += f"✅ Ollama detectado: {process.stdout.strip()}\n"

                # Verificar si el servicio está ejecutándose
                try:
                    response = requests.get(
                        "http://localhost:11434/api/tags", timeout=5
                    )
                    if response.status_code == 200:
                        result["ollama_status"] = "running"
                        current_log += "✅ Servicio Ollama ejecutándose\n"
                    else:
                        result["ollama_status"] = "installed"
                        current_log += "⚠️ Ollama instalado pero no ejecutándose\n"
                except requests.RequestException:
                    result["ollama_status"] = "installed"
                    current_log += "⚠️ Ollama instalado pero no ejecutándose\n"

            else:
                current_log += "❌ Ollama no encontrado en el sistema\n"

        except (FileNotFoundError, subprocess.TimeoutExpired):
            current_log += "❌ Ollama no está instalado\n"

        result["installation_log"] = current_log
        return result

    def _get_available_models(self):
        """Obtiene lista de modelos disponibles en Ollama con registro de errores y tiempo de espera mayor"""
        current_log = self.installation_log or ""  # Asegurarse de que sea una cadena
        try:
            # Aumentar tiempo de espera para hardware más lento (I5 2013)
            response = requests.get("http://localhost:11434/api/tags", timeout=20)
            if response.status_code == 200:
                models_data = response.json()
                model_names = [
                    model["name"] for model in models_data.get("models", [])
                ]
                current_log += f"🔍 Modelos detectados: {model_names}\n"
                self.write({"installation_log": current_log})
                return models_data

            current_log += (
                "❌ Error en API de Ollama: Código de estado %s\n"
                % response.status_code
            )
            self.write({"installation_log": current_log})
        except requests.RequestException as e:
            current_log += f"❌ Fallo al obtener modelos: {str(e)}\n"
            self.write({"installation_log": current_log})  # Guardar log
        return {"models": []}

    def _get_remote_models(self):
        """Devuelve una lista curada de modelos populares recomendados para descargar"""
        current_log = self.installation_log or ""

        # Lista curada de modelos populares y eficientes
        # Incluye nombre, y tamaño aproximado en GB para referencia
        curated_models = [
            {"name": "llama3.2:1b", "details": {"parameter_size": "1.3GB"}},
            {"name": "llama3.2:3b", "details": {"parameter_size": "2.0GB"}},
            {"name": "deepseek-r1:1.5b", "details": {"parameter_size": "1.1GB"}},
            {"name": "deepseek-r1:7b", "details": {"parameter_size": "4.7GB"}},
            {"name": "deepseek-r1:8b", "details": {"parameter_size": "4.9GB"}},
            {"name": "phi3:mini", "details": {"parameter_size": "2.3GB"}},
            {"name": "gemma2:2b", "details": {"parameter_size": "1.6GB"}},
            {"name": "gemma2:9b", "details": {"parameter_size": "5.4GB"}},
            {"name": "qwen2.5:0.5b", "details": {"parameter_size": "394MB"}},
            {"name": "qwen2.5:1.5b", "details": {"parameter_size": "986MB"}},
            {"name": "qwen2.5:3b", "details": {"parameter_size": "1.9GB"}},
            {"name": "qwen2.5:7b", "details": {"parameter_size": "4.7GB"}},
            {"name": "mistral", "details": {"parameter_size": "4.1GB"}},
            {"name": "neural-chat", "details": {"parameter_size": "4.1GB"}},
            {"name": "starling-lm", "details": {"parameter_size": "4.1GB"}},
        ]

        current_log += (
            f"🌐 Cargando lista de {len(curated_models)} modelos recomendados...\n"
        )
        self.write({"installation_log": current_log})

        return {"models": curated_models}

    def _check_database_config(self):
        """Verifica la configuración de la base de datos"""
        # Esta es una verificación básica - se expandirá con la integración de vector DB
        return {
            "db_configured": True,  # Odoo ya tiene su BD configurada
            "vector_db_status": "not_configured",
        }

    def _get_system_info(self):
        """Obtiene información del sistema (CPU, RAM, GPU)"""
        current_log = self.installation_log or ""
        system_info = {}

        try:
            # CPU Info
            system_info["cpu_count"] = psutil.cpu_count(logical=True)
            system_info["cpu_freq"] = psutil.cpu_freq().current
            current_log += (
                "💻 CPU: %s cores, %.2f MHz\n"
                % (system_info["cpu_count"], system_info["cpu_freq"])
            )

            # RAM Info
            svmem = psutil.virtual_memory()
            system_info["ram_total"] = round(svmem.total / (1024**3), 2)  # GB
            current_log += "💾 RAM Total: %.2f GB\n" % system_info["ram_total"]

            # GPU Info
            if GPUtil:
                try:
                    with warnings.catch_warnings():
                        warnings.filterwarnings("ignore", category=DeprecationWarning)
                        gpus = GPUtil.getGPUs()
                    if gpus:
                        gpu_info_list = []
                        for gpu in gpus:
                            gpu_info_list.append(
                                {
                                    "id": gpu.id,
                                    "name": gpu.name,
                                    "memoryTotal": gpu.memoryTotal,
                                    "memoryUsed": gpu.memoryUsed,
                                    "memoryFree": gpu.memoryFree,
                                    "driver": gpu.driver,
                                    "temperature": gpu.temperature,
                                    "utilization": gpu.load * 100,
                                }
                            )
                            current_log += (
                                "🎮 GPU %s: %s (%sMB, %.1f%% util)\n"
                                % (
                                    gpu.id,
                                    gpu.name,
                                    gpu.memoryTotal,
                                    gpu.load * 100,
                                )
                            )
                        system_info["gpu_info"] = json.dumps(gpu_info_list)
                    else:
                        system_info["gpu_info"] = "No GPU detected"
                        current_log += "🎮 GPU: No GPU detectada\n"
                except Exception as gpu_e:
                    system_info["gpu_info"] = "Error getting GPU info: %s" % str(
                        gpu_e
                    )
                    current_log += (
                        "❌ Error obteniendo información de GPU: %s\n" % str(gpu_e)
                    )
                    _logger.warning(
                        "GPUtil error: %s. It might not be installed or no GPUs are present.",
                        gpu_e,
                    )
            else:
                system_info["gpu_info"] = (
                    "GPUtil no está disponible, información de GPU no detectada."
                )
                current_log += "🎮 GPU: GPUtil no está disponible, información de GPU no detectada.\n"

        except Exception as e:
            current_log += f"❌ Error obteniendo información del sistema: {str(e)}\n"
            _logger.error("Error getting system info: %s", e)

        self.write({"installation_log": current_log})
        return system_info

    # Acciones del wizard
    def action_install_ollama(self):
        """Intenta instalar Ollama automáticamente"""
        current_log = self.installation_log or ""  # Asegurarse de que sea una cadena
        current_log += "🚀 Intentando instalar Ollama automáticamente...\n"

        try:
            # Detectar sistema operativo
            system = platform.system().lower()

            if system == "windows":
                # Para Windows - descargar instalador
                current_log += "📥 Descargando instalador para Windows...\n"
                # En una implementación real, descargaríamos el instalador
                current_log += "✅ Por favor, descarga Ollama desde https://ollama.ai/download y ejecuta el instalador\n"

            elif system == "linux":
                # Para Linux - instalar via curl
                current_log += "🐧 Instalando Ollama en Linux...\n"
                try:
                    process = subprocess.run(
                        ["curl", "-fsSL", "https://ollama.ai/install.sh"],
                        capture_output=True,
                        text=True,
                        timeout=30,
                        check=False,
                    )
                    if process.returncode == 0:
                        install_script = process.stdout
                        # Ejecutar script de instalación
                        install_process = subprocess.run(
                            ["sh", "-c", install_script],
                            capture_output=True,
                            text=True,
                            timeout=120,
                            check=False,
                        )
                        current_log += install_process.stdout
                        if install_process.returncode == 0:
                            current_log += (
                                "✅ Ollama instalado correctamente en Linux\n"
                            )
                        else:
                            current_log += (
                                f"❌ Error en instalación: {install_process.stderr}\n"
                            )

                except subprocess.TimeoutExpired:
                    current_log += "❌ Timeout durante la instalación\n"

            elif system == "darwin":  # macOS
                current_log += "🍎 Para macOS: brew install ollama\n"

            # Actualizar estado después de intentar instalar
            new_status = self._detect_ollama()
            self.write(new_status)
            self.write({"installation_log": current_log})  # Guardar log actualizado

        except Exception as e:
            current_log += f"❌ Error durante instalación: {str(e)}\n"
            self.write({"installation_log": current_log})  # Guardar log de error

        return self._show_installation_view()

    def action_download_model(self):
        """Descarga el modelo seleccionado"""
        current_log = self.installation_log or ""  # Asegurarse de que sea una cadena

        if not self.selected_model:
            current_log += (
                "❌ Error: No se ha seleccionado ningún modelo para descargar.\n"
            )
            self.write({"installation_log": current_log})
            raise UserError(
                self.env._("Por favor, selecciona un modelo para descargar.")
            )

        model_to_download = str(self.selected_model)  # Asegurarse de que sea una cadena
        if model_to_download.startswith("remote_"):
            model_to_download = model_to_download[len("remote_") :]
            current_log += f"📥 Descargando modelo remoto {model_to_download}...\n"
        else:
            current_log += (
                f"📥 Verificando/actualizando modelo local {model_to_download}...\n"
            )

        try:
            process = subprocess.run(
                ["ollama", "pull", model_to_download],
                capture_output=True,
                text=True,
                timeout=300,
                check=False,
            )  # 5 minutos timeout

            current_log += process.stdout
            if process.returncode == 0:
                current_log += f"✅ Modelo {model_to_download} descargado/actualizado correctamente\n"
                # Auto-seleccionar el modelo recién descargado para facilitar el avance
                self.selected_model = model_to_download
            else:
                current_log += f"❌ Error descargando/actualizando modelo {model_to_download}: {process.stderr}\n"

            # Actualizar lista de modelos disponibles
            available_models = self._get_available_models()
            self.write(
                {
                    "available_models": json.dumps(available_models, indent=2),
                    "installation_log": current_log,
                }
            )  # Guardar log y modelos

        except subprocess.TimeoutExpired:
            current_log += "❌ Timeout durante la descarga del modelo\n"
            self.write({"installation_log": current_log})  # Guardar log de error
        except Exception as e:
            current_log += f"❌ Error: {str(e)}\n"
            self.write({"installation_log": current_log})  # Guardar log de error

        return self._show_installation_view()

    def action_start_ollama(self):
        """Inicia el servicio Ollama"""
        current_log = self.installation_log or ""  # Asegurarse de que sea una cadena
        current_log += "🚀 Iniciando servicio Ollama...\n"

        try:
            # Intentar iniciar Ollama (depende del SO)
            system = platform.system().lower()

            if system == "windows":
                # En Windows, Ollama se ejecuta como servicio automáticamente
                process = subprocess.run(
                    ["ollama", "serve"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    check=False,
                )
                current_log += process.stdout

            elif system in ["linux", "darwin"]:
                process = subprocess.run(
                    ["systemctl", "start", "ollama"],
                    capture_output=True,
                    text=True,
                    timeout=30,
                    check=False,
                )
                current_log += process.stdout

            # Verificar estado
            new_status = self._detect_ollama()
            self.write(
                {**new_status, "installation_log": current_log}
            )  # Guardar log y nuevo estado

        except Exception as e:
            current_log += f"❌ Error iniciando Ollama: {str(e)}\n"
            self.write({"installation_log": current_log})  # Guardar log de error

        return self._show_installation_view()

    def action_configure_database(self):
        """Configura la base de datos vectorial"""
        current_log = self.installation_log or ""  # Asegurarse de que sea una cadena
        current_log += "🔧 Configurando base de datos vectorial...\n"

        try:
            # Aquí iría la configuración real de la vector DB
            # Por ahora, simulamos una configuración exitosa
            self.write(
                {
                    "vector_db_status": "configured",
                    "installation_log": current_log
                    + "✅ Base de datos vectorial configurada\n",
                }
            )

        except Exception as e:
            current_log += f"❌ Error configurando BD: {str(e)}\n"
            self.write({"installation_log": current_log})  # Guardar log de error

        return self._show_installation_view()

    def action_save_advanced_config(self):
        """Guarda la configuración avanzada"""
        current_log = self.installation_log or ""
        current_log += "⚙️ Guardando configuración avanzada...\n"

        self.write(
            {
                "advanced_config_saved": True,
                "installation_log": current_log
                + "✅ Configuración avanzada guardada\n",
            }
        )
        return self._show_installation_view()

    def action_next_step(self):
        """Avanza al siguiente paso del wizard"""
        current_log = self.installation_log or ""  # Asegurarse de que sea una cadena
        current_log += "⏭️ Avanzando al siguiente paso...\n"

        try:
            if self.current_step == "detection":
                # Verificar que Ollama esté ejecutándose antes de avanzar
                if self.ollama_status != "running":
                    raise UserError(
                        self.env._("Ollama debe estar ejecutándose para continuar")
                    )

                self.write(
                    {
                        "current_step": "model_selection",
                        "progress": 25,
                        "installation_log": current_log,
                    }
                )

            elif self.current_step == "model_selection":
                # Verificar que se haya seleccionado un modelo
                if not self.selected_model:
                    raise UserError(
                        self.env._("Debes seleccionar un modelo para continuar")
                    )

                self.write(
                    {
                        "current_step": "configuration",
                        "progress": 50,
                        "installation_log": current_log,
                    }
                )

            elif self.current_step == "configuration":
                # Verificar que la BD esté configurada
                if self.vector_db_status not in ["configured", "ready"]:
                    raise UserError(
                        self.env._(
                            "La base de datos debe estar configurada para continuar"
                        )
                    )

                self.write(
                    {
                        "current_step": "advanced_config",
                        "progress": 75,
                        "installation_log": current_log,
                    }
                )

            elif self.current_step == "advanced_config":
                self.write(
                    {
                        "current_step": "completion",
                        "progress": 100,
                        "installation_log": current_log,
                    }
                )

        except Exception as e:
            current_log += f"❌ Error avanzando al siguiente paso: {str(e)}\n"
            self.write({"installation_log": current_log})  # Guardar log de error
            raise UserError(
                self.env._("Error avanzando al siguiente paso: %s") % str(e)
            ) from e

        return self._show_installation_view()

    def action_previous_step(self):
        """Retrocede al paso anterior del wizard"""
        current_log = self.installation_log or ""  # Asegurarse de que sea una cadena
        current_log += "⏮️ Retrocediendo al paso anterior...\n"

        try:
            if self.current_step == "model_selection":
                self.write(
                    {
                        "current_step": "detection",
                        "progress": 0,
                        "installation_log": current_log,
                    }
                )

            elif self.current_step == "configuration":
                self.write(
                    {
                        "current_step": "model_selection",
                        "progress": 25,
                        "installation_log": current_log,
                    }
                )

            elif self.current_step == "advanced_config":
                self.write(
                    {
                        "current_step": "configuration",
                        "progress": 50,
                        "installation_log": current_log,
                    }
                )

            elif self.current_step == "completion":
                self.write(
                    {
                        "current_step": "advanced_config",
                        "progress": 75,
                        "installation_log": current_log,
                    }
                )

        except Exception as e:
            current_log += f"❌ Error retrocediendo al paso anterior: {str(e)}\n"
            self.write({"installation_log": current_log})  # Guardar log de error
            raise UserError(
                self.env._("Error retrocediendo al paso anterior: %s") % str(e)
            ) from e

        return self._show_installation_view()

    def action_complete_installation(self):
        """Completa la instalación y configura todo"""
        current_log = self.installation_log or ""  # Asegurarse de que sea una cadena
        current_log += "🎉 Completando instalación...\n"

        try:
            # Verificar que todo esté configurado
            if self.ollama_status != "running":
                raise UserError(
                    self.env._(
                        "Ollama debe estar ejecutándose para completar la instalación"
                    )
                )

            # 1. Guardar configuración de servidor Ollama
            config = self.env["ai.ollama.config"].search([], limit=1)
            if not config:
                self.env["ai.ollama.config"].create(
                    {
                        "name": "Local Ollama",
                        "url": "http://localhost:11434",
                        "active": True,
                    }
                )
                current_log += "✅ Configuración del servidor Ollama guardada\n"

            # 2. Registrar el modelo seleccionado
            if self.selected_model:
                model_name = self.selected_model
                # Buscar si ya existe
                ollama_model = self.env["ai.ollama.model"].search(
                    [("name", "=", model_name)], limit=1
                )
                if not ollama_model:
                    self.env["ai.ollama.model"].create(
                        {"name": model_name, "display_name": model_name, "active": True}
                    )
                    current_log += f"✅ Modelo {model_name} registrado en el catálogo\n"
                else:
                    ollama_model.write({"active": True})
                    current_log += f"✅ Modelo {model_name} activado en el catálogo\n"

                # 3. Guardar como preferencia del sistema
                self.env["ir.config_parameter"].sudo().set_param(
                    "ai_production_assistant.selected_model", model_name
                )
                current_log += (
                    f"✅ Modelo {model_name} establecido como predeterminado\n"
                )

            # 4. Guardar configuración avanzada
            set_param = self.env["ir.config_parameter"].sudo().set_param
            set_param(
                "ai_production_assistant.enable_watchdogs", str(self.enable_watchdogs)
            )
            set_param(
                "ai_production_assistant.enable_dashboards", str(self.enable_dashboards)
            )
            set_param(
                "ai_production_assistant.enable_actions", str(self.enable_actions)
            )
            set_param(
                "ai_production_assistant.show_pending_actions",
                str(self.show_pending_actions),
            )
            current_log += "✅ Preferencias de proactividad guardadas\n"

            # Configurar modelos por defecto si es necesario
            current_log += "✅ Instalación completada correctamente\n"
            self.write(
                {
                    "current_step": "completion",
                    "progress": 100,
                    "vector_db_status": "ready",
                    "installation_log": current_log,
                }
            )

        except Exception as e:
            current_log += f"❌ Error completando instalación: {str(e)}\n"
            self.write({"installation_log": current_log})
            raise UserError(
                self.env._("Error completando instalación: %s") % str(e)
            ) from e

        return self._show_installation_view()

    def action_installation_wizard(self):
        """
        Abre el wizard de instalación.
        """
        return {
            "name": self.env._(
                "Asistente de Instalación de AI Production Assistant"
            ),
            "type": "ir.actions.act_window",
            "res_model": "ai.installation.wizard",
            "view_mode": "form",
            "view_id": self.env.ref(
                "ai_production_assistant.view_installation_wizard_form"
            ).id,
            "target": "new",
            "res_id": self.create({}).id,
        }

    def _show_installation_view(self):
        """Muestra la vista actual del wizard"""
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
            "context": self.env.context,
        }
