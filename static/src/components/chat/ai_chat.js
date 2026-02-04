/** @odoo-module **/

import { Component, useState, useRef, onMounted, onPatched, onWillStart, onWillUnmount } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { deserializeDateTime, formatDateTime } from "@web/core/l10n/dates";
import { user } from "@web/core/user";
import { session } from "@web/session";

export class AiChat extends Component {
    static template = "ai_production_assistant.AiChat";

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.bus = useService("bus_service");

        this.state = useState({
            messages: [],
            input: "",
            isThinking: false,
            selectedModel: "gemma3:4b",
            availableModels: [],
            sessionId: null,
            sessionName: "",
            showSettings: false,
            darkMode: false,
            userHasSelectedModel: false,
            currentAvatar: localStorage.getItem('ai_assistant_avatar') || 'avatar.png'
        });

        this.messagesEndRef = useRef("messagesEnd");

        onWillStart(async () => {
            console.log("[AI Chat] Iniciando...");
            this.state.darkMode = localStorage.getItem("ai_chat_dark_mode") === "true";
            await this._loadModels();
            await this._loadOrCreateSession();
        });

        onMounted(() => {
            this.scrollToBottom();
            const uid = session.user_id || user.userId;
            const channel = `ai.assistant.message.${uid}`;
            this.bus.addChannel(channel);
            this.bus.addEventListener("notification", this._onBusNotification.bind(this));
            window.addEventListener('ai-avatar-changed', this._onAvatarChanged.bind(this));
        });

        onPatched(() => this.scrollToBottom());

        onWillUnmount(() => {
            window.removeEventListener('ai-avatar-changed', this._onAvatarChanged.bind(this));
            this.state.isThinking = false;
        });
    }

    _onAvatarChanged(ev) {
        if (ev.detail && ev.detail.avatar) {
            this.state.currentAvatar = ev.detail.avatar;
        }
    }

    get avatarUrl() {
        if (this.props.avatarUrl) return this.props.avatarUrl;
        return `/ai_production_assistant/static/src/img/${this.state.currentAvatar}`;
    }

    async _onBusNotification({ detail: notifications }) {
        for (const { payload, type } of notifications) {
            if (type === "ai_message" && payload.session_id === this.state.sessionId) {
                console.log("[AI Chat] Notificación recibida:", payload);
                await this._loadMessages(true);
            }
        }
    }

    toggleDarkMode() {
        this.state.darkMode = !this.state.darkMode;
        localStorage.setItem("ai_chat_dark_mode", this.state.darkMode);
    }

    async _loadModels() {
        try {
            const models = await this.orm.searchRead(
                "ai.ollama.model",
                [['active', '=', true]],
                ['id', 'name', 'size_mb']
            );
            this.state.availableModels = models;

            if (models.length > 0) {
                // Si ya teníamos uno seleccionado y válido, mantenerlo
                if (this.state.selectedModel && models.find(m => m.name === this.state.selectedModel)) {
                    // keep current
                } else {
                    // Default logic
                    const gemma = models.find(m => m.name.toLowerCase().includes("gemma"));
                    this.state.selectedModel = gemma ? gemma.name : models[0].name;
                }
            }
        } catch (e) {
            console.error("[AI Chat] Error cargando modelos:", e);
            this.state.availableModels = [{ id: 0, name: "gemma3:4b" }];
        }
    }

    async _loadOrCreateSession() {
        try {
            let sessions = await this.orm.searchRead(
                "ai.assistant.session",
                [['active', '=', true]], // Simplificado para debug (ver todas activas)
                ['id', 'name', 'model_ollama', 'user_id'],
                { limit: 1, order: 'write_date desc' }
            );

            if (sessions.length > 0) {
                const session = sessions[0];
                this.state.sessionId = session.id;
                this.state.sessionName = session.name;
                // IMPORTANTE: Si el usuario cambió el modelo localmente en el dropdown,
                // ese tiene prioridad sobre la sesión guardada (hasta que envíe mensaje).
                // Pero si es carga inicial, usamos el de la sesión.
                if (session.model_ollama && !this.state.userHasSelectedModel) {
                    this.state.selectedModel = session.model_ollama;
                }
                await this._loadMessages();
            } else {
                console.log("[AI Chat] No hay sesión activa.");
                this.state.messages = [
                    { role: "assistant", text: "¡Hola! Soy tu asistente de operaciones. ¿En qué puedo ayudarte?" }
                ];
            }
        } catch (e) {
            console.error("[AI Chat] Error sesión:", e);
        }
    }

    async _loadMessages(silent = false) {
        if (!this.state.sessionId) return;

        try {
            const serverMessages = await this.orm.searchRead(
                "ai.assistant.message",
                [['session_id', '=', this.state.sessionId]],
                ['id', 'role', 'content', 'pending_action', 'create_date', 'expert_name'],
                { order: 'create_date asc', limit: 100 }
            );

            // Mapear a formato interno y LIMPIAR JSON RESIDUAL
            const mappedMessages = serverMessages.map(m => {
                let cleanText = this._stripHtml(m.content || "");

                cleanText = cleanText.replace(/```(?:json)?[\s\S]*?```/g, '').trim();
                let candidate = cleanText.trim();
                if (candidate.includes('```')) {
                    candidate = candidate.replace(/```(?:json)?/g, '').replace(/```/g, '').trim();
                }
                if (candidate.startsWith('{') && candidate.includes('"tool"')) {
                    try {
                        const jsonContent = JSON.parse(candidate);
                        if (jsonContent.tool === 'message' && jsonContent.params) {
                            if (jsonContent.params.content) cleanText = jsonContent.params.content;
                            else if (jsonContent.params.text) cleanText = jsonContent.params.text;
                        } else if (jsonContent.tool) {
                            cleanText = `Acción preparada: ${jsonContent.tool}`;
                        }
                    } catch (e) {
                        const match = candidate.match(/"content"\s*:\s*"([^"]+)"/);
                        if (match) cleanText = match[1];
                    }
                }

                return {
                    id: m.id,
                    role: m.role,
                    text: cleanText,
                    pendingAction: m.pending_action ? this._safeParseJson(m.pending_action) : null,
                    time: formatDateTime(deserializeDateTime(m.create_date), { format: "HH:mm" }),
                    expert: m.expert_name || "IA"
                };
            });

            if (mappedMessages.length === 0 && this.state.messages.length === 0) {
                this.state.messages = [
                    { role: "assistant", text: "¡Hola! Soy tu asistente de operaciones." }
                ];
                return;
            }

            const lastServerMsg = mappedMessages[mappedMessages.length - 1];
            if (lastServerMsg) {
                if (lastServerMsg.role === "assistant") this.state.isThinking = false;
                if (lastServerMsg.role === "user") this.state.isThinking = true;
            }

            // SMART MERGE: 
            // 1. Mantener mensajes locales optimistas (IDs grandes)
            // Usamos un umbral alto para distinguir IDs temporales de IDs de base de datos
            const OPTIMISTIC_ID_THRESHOLD = 1000000000000;
            const localOptimistic = this.state.messages.filter(m => typeof m.id === 'number' && m.id > OPTIMISTIC_ID_THRESHOLD);

            // 2. Descartar optimistas si ya llegaron del servidor (evitar duplicados)
            const finalOptimistic = localOptimistic.filter(optMsg => {
                // Comparamos por contenido y rol, ya que el ID será diferente
                const existsInServer = mappedMessages.some(srvMsg =>
                    srvMsg.role === optMsg.role &&
                    srvMsg.text === optMsg.text
                );
                return !existsInServer;
            });

            // 3. Detectar cambios para actualizar
            const currentIds = new Set(this.state.messages.map(m => m.id));
            const newIds = new Set(mappedMessages.map(m => m.id));

            let hasChanges = false;
            for (let m of mappedMessages) {
                if (!currentIds.has(m.id)) hasChanges = true;
            }
            // Detectar borrados (excepto optimistas)
            for (let m of this.state.messages) {
                if (m.id < OPTIMISTIC_ID_THRESHOLD && !newIds.has(m.id)) hasChanges = true;
            }
            if (localOptimistic.length !== finalOptimistic.length) hasChanges = true;

            // SIEMPRE fusionar mensajes del servidor con los optimistas pendientes
            if (hasChanges || !silent || finalOptimistic.length > 0) {
                this.state.messages = [...mappedMessages, ...finalOptimistic];
                if (!silent || hasChanges) this.scrollToBottom();
            }

            // Apagar 'Thinking' si llegó respuesta assistant
            const lastMsg = mappedMessages[mappedMessages.length - 1];
            if (lastMsg && lastMsg.role === 'assistant' && this.state.isThinking) {
                if (hasChanges) this.state.isThinking = false;
            }

        } catch (e) {
            console.error("[AI Chat] Error mensajes:", e);
        }
    }

    _stripHtml(html) {
        const tmp = document.createElement("div");
        tmp.innerHTML = html;
        return tmp.textContent || tmp.innerText || "";
    }

    _safeParseJson(str) {
        try { return JSON.parse(str); } catch { return null; }
    }

    _formatActionSummary(action) {
        if (!action) return "";
        const tool = action.tool || action.type;
        const params = action.params || action;
        if (tool === "create_product") {
            const name = params.name || "(sin nombre)";
            const price = params.price ?? "?";
            const cost = params.cost ?? "?";
            const type = params.type || "consu";
            return `Crear producto: ${name} · Precio: ${price} · Coste: ${cost} · Tipo: ${type}`;
        }
        if (tool === "adjust_stock") {
            const productId = params.product_id ?? "?";
            const quantity = params.quantity ?? "?";
            return `Ajustar stock: producto ${productId} · Cantidad: ${quantity}`;
        }
        if (tool === "create_mrp_order") {
            const productId = params.product_id ?? "?";
            const quantity = params.quantity ?? "?";
            return `Crear orden MRP: producto ${productId} · Cantidad: ${quantity}`;
        }
        if (tool === "create_bom") {
            const productId = params.product_id ?? "?";
            const components = Array.isArray(params.components)
                ? params.components.length
                : 0;
            return `Crear BoM: producto ${productId} · Componentes: ${components}`;
        }
        return tool ? `Acción: ${tool}` : "Acción";
    }

    scrollToBottom() {
        if (this.messagesEndRef.el) {
            this.messagesEndRef.el.scrollIntoView({ behavior: "smooth" });
        }
    }

    toggleSettings() {
        this.state.showSettings = !this.state.showSettings;
    }

    async newChat() {
        if (this.state.sessionId) {
            await this.orm.write("ai.assistant.session", [this.state.sessionId], { active: false });
        }
        this.state.sessionId = null;
        this.state.messages = [];
        this.state.sessionName = "Nueva Conversación";
        this.notification.add("Nueva conversación iniciada", { type: "success" });
    }

    async clearHistory() {
        if (!this.state.sessionId) return;
        if (!confirm("¿Borrar historial?")) return;

        try {
            const OPTIMISTIC_ID_THRESHOLD = 1000000000000;
            const msgIds = this.state.messages
                .filter(m => typeof m.id === "number" && m.id < OPTIMISTIC_ID_THRESHOLD)
                .map(m => m.id);
            if (msgIds.length > 0) {
                await this.orm.unlink("ai.assistant.message", msgIds);
            }
            this.state.messages = [];
            this.notification.add("Historial borrado", { type: "success" });
        } catch (e) {
            this.notification.add("Error al borrar", { type: "danger" });
        }
    }

    async sendMessage() {
        const input = this.state.input.trim();
        if (!input || this.state.isThinking) return;

        this.state.input = "";
        this.state.isThinking = true;

        // Optimistic UI: Mostrar mensaje del usuario inmediatamente
        const tempId = Date.now();
        this.state.messages.push({
            id: tempId,
            role: "user",
            text: input,
            time: new Date().toLocaleTimeString().slice(0, 5)
        });

        try {
            const response = await fetch("/ai_assistant/ask_stream", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    prompt: input,
                    model: this.state.selectedModel,
                }),
            });

            if (!response.ok) throw new Error(`HTTP ${response.status}`);

            const data = await response.json();
            if (data.error) throw new Error(data.error);

            // Recargar mensajes desde BD para sincronizar IDs y respuestas
            // (El backend ya guardó todo)
            await this._loadOrCreateSession();

            // Si por alguna razón la recarga no trae el mensaje nuevo (race condition),
            // lo añadimos manualmente (pero preferimos recargar para tener IDs reales)

        } catch (err) {
            console.error("[AI Chat] Error:", err);
            this.state.messages.push({
                role: "assistant",
                text: `⚠️ Error de conexión: ${err.message}. (Pero el servidor podría estar procesando)`
            });
        } finally {
            this.state.isThinking = false;
        }
    }

    async confirmAction(msgIndex) {
        const msg = this.state.messages[msgIndex];
        if (!msg.pendingAction) return;

        this.state.isThinking = true;

        try {
            const result = await fetch("/ai_assistant/execute_action", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    jsonrpc: "2.0",
                    method: "call",
                    params: { action_data: msg.pendingAction, message_id: msg.id }
                }),
            });

            const data = await result.json();
            const res = data.result || data;

            if (res.error) throw new Error(res.error);

            msg.pendingAction = null;
            await this._loadOrCreateSession();

        } catch (err) {
            this.notification.add(`Error: ${err.message}`, { type: "danger" });
        } finally {
            this.state.isThinking = false;
        }
    }

    cancelAction(msgIndex) {
        this.state.messages[msgIndex].pendingAction = null;
    }

    _onKeydown(ev) {
        if (ev.key === "Enter" && !ev.shiftKey) {
            ev.preventDefault();
            this.sendMessage();
        }
    }

    async onModelChange(ev) {
        this.state.selectedModel = ev.target.value;
        this.state.userHasSelectedModel = true; // Marcar selección manual
        if (this.state.sessionId) {
            await this.orm.write("ai.assistant.session", [this.state.sessionId], {
                model_ollama: this.state.selectedModel
            });
        }
        try {
            await this.orm.call("ir.config_parameter", "set_param", [
                "ai_production_assistant.selected_model",
                this.state.selectedModel,
            ]);
            this.notification.add("Modelo actualizado", { type: "success" });
        } catch (e) {
            this.notification.add("No se pudo guardar el modelo", { type: "warning" });
        }
    }
}

registry.category("actions").add("ai_production_assistant.chat", AiChat);
