/** @odoo-module **/

import { Component, useState, onWillStart, onMounted, useRef } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { registry } from "@web/core/registry";
import { session } from "@web/session";
import { user } from "@web/core/user";
import { AiChat } from "../chat/ai_chat";

export class AiAvatar extends Component {
      static template = "ai_production_assistant.AiAvatar";
      static components = { AiChat };
      static props = {};

      setup() {
            this.orm = useService("orm");
            this.action = useService("action");
            this.bus = useService("bus_service");

            this.state = useState({
                  isOpen: false,
                  activeTab: 'chat', // chat | notifications
                  mood: 'idle',
                  selectedAvatar: localStorage.getItem('ai_assistant_avatar') || 'avatar.png',
                  isAvatarSelectorOpen: false
            });

            this.avatars = [
                'avatar.png',
                'avatar1.png', 'avatar2.png', 'avatar3.png', 'avatar4.png',
                'avatar5.png', 'avatar6.png', 'avatar7.png', 'avatar8.png', 
                'avatar9.png', 'avatar10.png'
            ];

            this.notifications = useState([]);

            onWillStart(async () => {
                  await this.refreshNotifications();
            });

            setInterval(() => this.refreshNotifications(), 60000);

            onMounted(() => {
                  let uid = Array.isArray(session.user_id) ? session.user_id[0] : user.userId;
                  if (uid) {
                      const channel = `ai.notification.${uid}`;
                      this.bus.addChannel(channel);
                  }
                  this.bus.subscribe("ai.notification", (payload) => {
                        const item = {
                              id: payload.id || Date.now(),
                              title: payload.title,
                              body: payload.body,
                              type: payload.type || "info",
                              action_payload: payload.action_payload || null,
                              is_read: false,
                        };
                        this.notifications.unshift(item);
                        if (this.notifications.length > 50) {
                              this.notifications.pop();
                        }
                  });
            });
      }

      toggleWindow() {
            this.state.isOpen = !this.state.isOpen;
      }

      toggleAvatarSelector() {
          this.state.isAvatarSelectorOpen = !this.state.isAvatarSelectorOpen;
      }

      selectAvatar(avatar) {
          this.state.selectedAvatar = avatar;
          localStorage.setItem('ai_assistant_avatar', avatar);
          this.state.isAvatarSelectorOpen = false;
          
          // Emitir evento para que otros componentes se enteren
          window.dispatchEvent(new CustomEvent('ai-avatar-changed', { detail: { avatar } }));
      }

      get avatarUrl() {
          return `/ai_production_assistant/static/src/img/${this.state.selectedAvatar}`;
      }

      switchTab(tab) {
            this.state.activeTab = tab;
      }

      get unreadCount() {
            return this.notifications.filter(n => !n.is_read).length;
      }

      async refreshNotifications() {
            try {
                  const result = await this.orm.call("ai.notification", "search_read", [
                        [['is_dismissed', '=', false]],
                        ['name', 'body', 'notification_type', 'action_payload', 'is_read']
                  ], { limit: 20, order: 'create_date desc' });

                  // Mapear para facilitar uso en template
                  // Limpiar array actual y rellenar
                  this.notifications.splice(0, this.notifications.length);

                  result.forEach(r => {
                        this.notifications.push({
                              id: r.id,
                              title: r.name,
                              body: r.body,
                              type: r.notification_type,
                              action_payload: r.action_payload ? JSON.parse(r.action_payload) : null,
                              is_read: r.is_read
                        });
                  });

            } catch (e) {
                  console.error("Error fetching notifications", e);
            }
      }

      async dismissNotification(id) {
            await this.orm.call("ai.notification", "action_dismiss", [[id]]);
            await this.refreshNotifications();
      }

      async executeAction(notification) {
            if (!notification.action_payload) return;

            // Ejecutar acción a través del servidor
            // Dependiendo de cómo queramos manejarlo: abrir vista o ejecutar silent
            // Aquí asumimos ejecución backend y mostrar resultado
            try {
                  const result = await this.orm.call("ai.assistant.session", "execute_action_payload", [notification.action_payload]);
                  // Feedback visual o abrir chat para mostrar resultado?
                  // Por ahora simple alerta
                  alert("Acción ejecutada: " + JSON.stringify(result));
                  await this.dismissNotification(notification.id);
            } catch (e) {
                  alert("Error ejecutando acción: " + e);
            }
      }
}

// Registrar en el systray para que aparezca globalmente
export const systrayItem = {
      Component: AiAvatar,
};

registry.category("systray").add("ai_production_assistant.avatar", systrayItem, { sequence: 100 });
