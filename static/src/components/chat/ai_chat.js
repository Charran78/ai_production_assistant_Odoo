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
            ]
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
                    // Auto scroll as we type
                    this.scrollToBottom();
                } else {
                    this.state.isThinking = false;
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

    _onKeydown(ev) {
        if (ev.key === "Enter" && !ev.shiftKey) {
            ev.preventDefault();
            this.sendMessage();
        }
    }
}

registry.category("actions").add("ai_production_assistant.chat", AiChat);
