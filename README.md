# AI Production Assistant (Odoo 19 + Ollama + Agentic RAG)

Asistente avanzado de producción inteligente que integra modelos locales (Ollama) con Odoo ERP, permitiendo análisis de datos en tiempo real y automatización de tareas. Optimizado para **Odoo 19.0** y modelos ligeros (<4B).

## 🚀 Características "Siguiente Nivel"

- **Chat OWL Moderno**: Interfaz fluida integrada en Odoo con soporte para Modo Oscuro y estilos de respuesta (Tablas, Informes, Planes).
- **Lógica de Agente HABA**: Arquitectura *Hybrid Agentic Behavior* que permite a la IA proponer acciones técnicas (ej: crear órdenes de fabricación) con validación humana.
- **Optimización para Modelos Pequeños**: Implementación de **ChatML** y **Few-Shot prompting** para máxima adherencia en modelos como `tinyLlama` y `phi3`.
- **RAG Multicontexto**: Extracción inteligente de datos (incluyendo campos relacionales) de cualquier modelo de Odoo.
- **Robustez y Rendimiento**: Configuración de timeouts extendidos (600s) y reintentos automáticos para manejar latencias de LLMs locales.
- **Privacidad Total**: Todo el procesamiento ocurre en tu infraestructura local a través de Ollama.

## 🛠️ Instalación y Configuración Odoo 19

1. **Requisitos**: Python 3.13 + Odoo 19.0.
2. **Ollama**: Asegúrate de tener Ollama corriendo en `localhost:11434`.
3. **Módulo**: Clona este repositorio en tu carpeta de `custom_addons`.
4. **Timeouts**: Se recomienda añadir estas líneas a tu `odoo.conf`:

   ```ini
   limit_time_real = 600
   limit_time_cpu = 600
   ```

5. **Configuración**: Instala el módulo, sincroniza los modelos desde **Configuración > Modelos IA** y ¡listo!

## 🤖 Uso del Agente

Puedes pedirle cosas como:

- *"Necesito fabricar 50 unidades de Pizza Pepperoni para hoy"*
- *"¿Qué órdenes de fabricación tenemos pendientes y qué productos contienen?"*
- *"Analiza mi inventario y genera un informe de materias primas"*

---
Desarrollado para Odoo 19 - Pedro Mencías.
