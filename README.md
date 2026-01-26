# AI Production Assistant (Odoo 19 + Ollama)

Este módulo integra inteligencia artificial generativa local (Ollama) dentro del flujo de trabajo de Odoo Manufacturing (MRP), proporcionando un asistente conversacional capaz de analizar el estado de la producción en tiempo real.

---

## 🚀 Estado Actual (Fase 1 - Completada)

Hemos logrado implementar una arquitectura **Full-Stack** moderna dentro de Odoo:

### **Backend (Python)**

* **Conexión con Ollama**: Integración vía `requests` con la API local de Ollama (`localhost:11434`).
* **Gestión de Modelos**: Sistema para sincronizar y seleccionar modelos disponibles (ej: `phi3:mini`, `llama3.2`).
* **Prompt Engineering**: Lógica condicional para formatear respuestas como Tabla, Informe o Plan de Acción.
* **Simulación de Streaming**: Controlador optimizado para evitar bloqueos de red en Windows, devolviendo JSON completo pero permitiendo efectos visuales en cliente.

### **Frontend (Odoo Web Library - OWL)**

* **Single Page Application (SPA)**: Chat moderno implementado como `Client Action`, reemplazando las vistas estándar aburridas.
* **UX Avanzada**:
  * Efecto "Typewriter" (escritura letra a letra) simulando streaming.
  * **Modo Oscuro** nativo con toggle en tiempo real.
  * Selector dinámico de modelos.
  * Burbujas de chat estilo mensajería moderna.
  * Renderizado de Markdown (negritas, tablas básicas).

### **Integración**

* Menú dedicado en **Fabricación > Asistente IA**.
* Acceso a datos reales de Odoo (Órdenes de Producción confirmadas/en progreso).

---

## 🛠️ Tecnologías Usadas

* **Odoo 19.0** (Enterprise/Community)
* **Python 3.12+**
* **OWL (Odoo Web Library)**: Componentes reactivos JS.
* **Ollama**: Servidor de inferencia local.
* **SCSS**: Estilos industriales "Clean UI".

---

## 🔮 Roadmap (Lo que queda / Fase 2)

### **1. RAG Avanzado (Retrieval-Augmented Generation)**

* **PostgreSQL + Qdrant / ChromaDB**: Implementar una base de datos vectorial para "recordar" manuales técnicos PDF y hojas de Excel.
* **Búsqueda Semántica**: Que el asistente pueda responder dudas sobre manuales de maquinaria, pedidos, clientes, proyectos, plazos, etc. no solo sobre datos de Odoo.

### **2. Optimización y Estabilidad**

* **Control de Alucinaciones**: Refinar los prompts para que el modelo no invente datos ("Juan Pérez") cuando la base de datos está vacía.
* **Gestión de Recursos**: Implementar colas de tareas (Odoo CRON o Queue Job) para consultas pesadas que bloquean el servidor (evitar `ERR_CONNECTION_REFUSED`).
* **Markdown Real**: Integrar librería `marked.js` para renderizado perfecto de tablas complejas y código.

### **3. Agente Autónomo (Agentic Goals)**

* **Planificación Automática**: Que la IA no solo sugiera, sino que pueda *crear* una Orden de Fabricación (borrador) si el usuario lo confirma.
* **Análisis Predictivo**: Usar modelos más potentes para predecir roturas de stock basándose en históricos.

---

## 📝 Notas de Desarrollo

* **Modelo Recomendado**: `phi3:mini` (equilibrio perfecto velocidad/calidad para este caso de uso).
* **Advertencia**: En entornos de desarrollo Windows (`workers=0`), el streaming HTTP real es inestable. Se mantiene la simulación frontend por estabilidad.

---
