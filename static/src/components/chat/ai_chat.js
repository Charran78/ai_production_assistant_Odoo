/** @odoo-module **/

import { Component, useState, useRef, onMounted, onPatched, onWillStart, onWillUnmount } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

export class AiChat extends Component {
    static template = "ai_production_assistant.AiChat";

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");

        this.state = useState({
            messages: [],
            input: "",
            isThinking: false,
            selectedModel: "gemma3:4b",
            availableModels: [],
            sessionId: null,
            sessionName: "",
            showSettings: false,
            darkMode: false, // ¡Vuelve el Dark Mode!
            userHasSelectedModel: false, // Nuevo estado para saber si el usuario ha cambiado el modelo
        });

        this.messagesEndRef = useRef("messagesEnd");
        this.pollingInterval = null;

        onWillStart(async () => {
            console.log("[AI Chat] Iniciando...");
            // Cargar estado de dark mode (simple localstorage)
            this.state.darkMode = localStorage.getItem("ai_chat_dark_mode") === "true";

            await this._loadModels();
            await this._loadOrCreateSession();
        });

        onMounted(() => {
            this.scrollToBottom();
            // Polling para actualizar mensajes (cada 3s)
            this.pollingInterval = setInterval(() => this._refreshMessages(), 3000);
        });

        onPatched(() => this.scrollToBottom());

        // Limpiar intervalo al destruir
        onWillUnmount(() => {
            if (this.pollingInterval) clearInterval(this.pollingInterval);
        });
    }

    async _refreshMessages() {
        if (!this.state.sessionId) return;
        // Solo recargar si no estamos escribiendo ni esperando respuesta inmediata
        // (aunque el backend sea async, evitamos parpadeos si el user está activo)
        // Pero para el caso "me fui y volví", esto es clave.
        await this._loadMessages(true); // true = silent (sin scroll forzado si no hay cambios)
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
                ['name', 'size_mb']
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
                ['id', 'role', 'content', 'pending_action', 'create_date'],
                { order: 'create_date asc', limit: 100 }
            );

            // Mapear a formato interno y LIMPIAR JSON RESIDUAL
            const mappedMessages = serverMessages.map(m => {
                let cleanText = this._stripHtml(m.content || "");

                // Si el texto parece un JSON de herramienta "message", extraerlo
                if (cleanText.trim().startsWith('{') && cleanText.includes('"tool"')) {
                    try {
                        const jsonContent = JSON.parse(cleanText);
                        if (jsonContent.tool === 'message' && jsonContent.params && jsonContent.params.content) {
                            cleanText = jsonContent.params.content;
                        }
                    } catch (e) {
                        // Ignorar error de parseo, dejar texto original o intentar regex
                        const match = cleanText.match(/"content"\s*:\s*"([^"]+)"/);
                        if (match) cleanText = match[1];
                    }
                }

                return {
                    id: m.id,
                    role: m.role,
                    text: cleanText,
                    pendingAction: m.pending_action ? this._safeParseJson(m.pending_action) : null,
                    time: new Date(m.create_date).toLocaleTimeString('es-ES').slice(0, 5),
                };
            });

            if (mappedMessages.length === 0 && this.state.messages.length === 0) {
                this.state.messages = [
                    { role: "assistant", text: "¡Hola! Soy tu asistente de operaciones." }
                ];
                return;
            }

            // SMART MERGE: 
            // 1. Mantener mensajes locales optimistas (IDs grandes)
            const localOptimistic = this.state.messages.filter(m => typeof m.id === 'number' && m.id > 1000000000000);

            // 2. Descartar optimistas si ya llegaron del servidor
            const finalOptimistic = localOptimistic.filter(optMsg => {
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
            // Detectar borrados
            for (let m of this.state.messages) {
                if (m.id < 1000000000000 && !newIds.has(m.id)) hasChanges = true;
            }
            if (localOptimistic.length !== finalOptimistic.length) hasChanges = true;

            if (hasChanges || !silent) {
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
            const msgIds = this.state.messages.filter(m => m.id).map(m => m.id);
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
                    params: { action_data: msg.pendingAction }
                }),
            });

            const data = await result.json();
            const res = data.result || data;

            if (res.error) throw new Error(res.error);

            msg.pendingAction = null;
            // Recargar para ver el mensaje de confirmación guardado por backend? 
            // Execute action NO guarda mensaje en backend automáticamente (es otro endpoint).
            // Deberíamos añadirlo manualmente al chat local
            const feedback = res.message || "✅ Acción ejecutada";
            this.state.messages.push({
                role: "assistant",
                text: feedback,
                time: new Date().toLocaleTimeString().slice(0, 5)
            });

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
    }
}

registry.category("actions").add("ai_production_assistant.chat", AiChat);
