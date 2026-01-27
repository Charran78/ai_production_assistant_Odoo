/** @odoo-module **/

import { Component, useState, useRef, onMounted, onPatched, onWillStart } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

export class AiChat extends Component {
    static template = "ai_production_assistant.AiChat";

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.action = useService("action");

        this.state = useState({
            messages: [
                { role: "assistant", text: "Hola, soy tu asistente de producción 4.0. ¿En qué puedo ayudarte hoy?" }
            ],
            input: "",
            isThinking: false,
            selectedModel: "", // Se llenará dinámicamente
            outputStyle: "concise",
            darkMode: false,
            availableModels: [],
            selectedContextModel: "mrp.production",
            availableContextModels: [
                { id: "mrp.production", name: "Órdenes de Fabricación" },
                { id: "stock.picking", name: "Albaranes / Entregas" },
                { id: "stock.lot", name: "Lotes / Números de Serie" },
                { id: "product.template", name: "Catálogo de Productos" },
                { id: "mail.message", name: "Bandeja de Entrada / Emails" },
                { id: "qdrant", name: "🔍 Base de Conocimiento (Qdrant)" }
            ],
            pendingAction: null // { model, function, vals, msgIndex }
        });

        this.messagesEndRef = useRef("messagesEnd");

        onWillStart(async () => {
            try {
                // Cargar modelos desde DB
                const models = await this.orm.searchRead("ai.ollama.model", [['active', '=', true]], ['name', 'size_mb']);
                this.state.availableModels = models;

                if (models.length > 0) {
                    // Preferir TinyLlama o Phil si existe (por velocidad)
                    const fastModel = models.find(m => {
                        const n = m.name.toLowerCase();
                        return n.includes("tiny") || n.includes("phi");
                    });
                    this.state.selectedModel = fastModel ? fastModel.name : models[0].name;
                } else {
                    this.state.selectedModel = "llama3.2"; // Fallback visual
                    this.state.availableModels = [{ id: 0, name: "llama3.2 (Default)" }];
                }
            } catch (e) {
                console.error("Error loading models", e);
                this.state.availableModels = [{ id: 0, name: "Error cargando modelos" }];
            }
        });

        onMounted(() => this.scrollToBottom());
        onPatched(() => this.scrollToBottom());
    }

    toggleDarkMode() {
        this.state.darkMode = !this.state.darkMode;
    }

    scrollToBottom() {
        if (this.messagesEndRef.el) {
            this.messagesEndRef.el.scrollIntoView({ behavior: "smooth" });
        }
    }

    async sendMessage() {
        if (!this.state.input.trim() || this.state.isThinking) return;

        const currentInput = this.state.input;
        const currentStyle = this.state.outputStyle;
        const currentModel = this.state.selectedModel;

        // Add user message
        this.state.messages.push({ role: "user", text: currentInput });
        this.state.input = "";
        this.state.isThinking = true;

        try {
            // Initiate Fetch Request to our Controller
            const response = await fetch("/ai_assistant/ask_stream", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    prompt: currentInput,
                    output_style: currentStyle,
                    model: currentModel,
                    target_model: this.state.selectedContextModel
                }),
            });

            if (!response.ok) {
                const errorText = await response.text();
                throw new Error(`Server Error ${response.status}: ${errorText || response.statusText}`);
            }

            // Prepare assistant message bubble before writing
            const assistantMsgIndex = this.state.messages.push({ role: "assistant", text: "" }) - 1;
            const assistantMsg = this.state.messages[assistantMsgIndex];

            const data = await response.json();

            if (data.error) throw new Error(data.error);

            const fullText = data.response || "";

            // Typewriter Effect Logic
            let i = 0;
            const speed = 10; // ms per char (ajustable)

            const typeWriter = () => {
                if (i < fullText.length) {
                    assistantMsg.text += fullText.charAt(i);
                    i++;
                    setTimeout(typeWriter, speed);
                    this.scrollToBottom();
                } else {
                    this.state.isThinking = false;
                    this._checkForActions(assistantMsg.text, assistantMsgIndex);
                }
            };

            // Iniciar efecto
            typeWriter();

            // No reseteamos isThinking aquí, lo hace el callback al terminar
            return;

        } catch (err) {
            this.state.messages.push({
                role: "assistant",
                text: `⚠️ ${err.message}`
            });
            console.error("AI Chat Error:", err);
            this.state.isThinking = false;
        }
    }

    _checkForActions(text, msgIndex) {
        // Regex super-robusta: detecta ACTION_DATA con o sin dos puntos, y limpia ruidos logicamente
        const regex = /\[\[ACTION_DATA[:\s]+({[\s\S]*?})\s*\]\]/;
        const match = text.match(regex);
        if (match) {
            try {
                // Sanitizamos el contenido por si el modelo metio bloques de codigo dentro del tag
                let jsonStr = match[1].replace(/```json|```/g, "").trim();
                const actionData = JSON.parse(jsonStr);
                this.state.messages[msgIndex].pendingAction = actionData;
                // Limpiamos el texto visual: quitamos el bloque entero de la respuesta
                this.state.messages[msgIndex].text = text.replace(match[0], "").trim();
                this.scrollToBottom();
            } catch (e) {
                console.error("Error parsing AI action JSON", e, match[1]);
            }
        }
    }

    async confirmAction(msgIndex) {
        const msg = this.state.messages[msgIndex];
        const actionData = msg.pendingAction;
        if (!actionData) return;

        this.state.isThinking = true;
        try {
            const result = await fetch("/ai_assistant/execute_action", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ params: { action_data: actionData } }),
            });
            const data = await result.json();
            const res = data.result;

            if (res.error) throw new Error(res.error);

            msg.pendingAction = null;
            this.state.messages.push({
                role: "assistant",
                text: `✅ Éxito: Registro **${res.display_name}** creado correctamente (ID: ${res.res_id}).`
            });
        } catch (err) {
            this.notification.add(`Error: ${err.message}`, { type: "danger" });
        } finally {
            this.state.isThinking = false;
        }
    }

    cancelAction(msgIndex) {
        this.state.messages[msgIndex].pendingAction = null;
        this.state.messages.push({
            role: "assistant",
            text: "Acción cancelada por el usuario."
        });
    }

    _onKeydown(ev) {
        if (ev.key === "Enter" && !ev.shiftKey) {
            ev.preventDefault();
            this.sendMessage();
        }
    }
}

registry.category("actions").add("ai_production_assistant.chat", AiChat);
