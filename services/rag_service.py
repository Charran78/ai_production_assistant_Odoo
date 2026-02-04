# -*- coding: utf-8 -*-

import base64
import logging
import re

import requests

try:
    from odoo.tools import html2plaintext
except Exception:
    def html2plaintext(value):
        return re.sub(r"<[^>]+>", " ", value or "")

from .ollama_service import OllamaService


_logger = logging.getLogger(__name__)


def parse_docs_prompt(prompt):
    if not prompt:
        return None
    lower = prompt.lower()
    keywords = ["documentación", "documentacion", "documento", "manual", "procedimiento", "docs"]
    if not any(k in lower for k in keywords):
        return None
    return {"tool": "search_docs", "params": {"query": prompt.strip()}}


def parse_mail_prompt(prompt):
    if not prompt:
        return None
    lower = prompt.lower()
    keywords = ["correo", "mail", "email", "bandeja", "inbox"]
    if not any(k in lower for k in keywords):
        return None
    return {"tool": "search_mail", "params": {"query": prompt.strip()}}


class VectorRagService:
    def __init__(self, env):
        self.env = env
        self.config = env["ai.vector.config"].search([("active", "=", True)], limit=1)
        self.ollama = OllamaService(env)

    def _headers(self):
        if self.config and self.config.api_key:
            return {"api-key": self.config.api_key}
        return {}

    def _collection_url(self):
        return f"{self.config.url.rstrip('/')}/collections/{self.config.collection_name}"

    def _ensure_collection(self, vector_size):
        url = self._collection_url()
        try:
            res = requests.get(url, headers=self._headers(), timeout=5)
            if res.status_code == 200:
                return True
            if res.status_code != 404:
                return False
            payload = {
                "vectors": {"size": vector_size, "distance": "Cosine"},
            }
            create = requests.put(url, json=payload, headers=self._headers(), timeout=10)
            return create.status_code in [200, 201]
        except Exception:
            return False

    def _embed(self, text):
        return self.ollama.embed(text)

    def _sanitize(self, text):
        if not text:
            return ""
        return text.strip()[:4000]

    def _upsert_points(self, points):
        if not points:
            return False
        url = f"{self._collection_url()}/points?wait=true"
        payload = {"points": points}
        res = requests.post(url, json=payload, headers=self._headers(), timeout=20)
        return res.status_code in [200, 201]

    def index_documents(self, since=None):
        if not self.config:
            return 0
        domain = [("type", "=", "binary"), ("mimetype", "in", ["text/plain", "text/html"])]
        if since:
            domain.append(("write_date", ">", since))
        attachments = self.env["ir.attachment"].search_read(
            domain, ["id", "name", "mimetype", "datas", "write_date"]
        )
        count = 0
        for att in attachments:
            raw = base64.b64decode(att.get("datas") or b"")
            text = raw.decode("utf-8", errors="ignore")
            if att.get("mimetype") == "text/html":
                text = html2plaintext(text)
            content = self._sanitize(text)
            if len(content) < 30:
                continue
            vector = self._embed(content)
            if not vector:
                continue
            if not self._ensure_collection(len(vector)):
                return count
            point = {
                "id": f"doc_{att['id']}",
                "vector": vector,
                "payload": {
                    "source": "docs",
                    "record_id": att["id"],
                    "title": att.get("name"),
                    "content": content,
                    "updated": att.get("write_date"),
                },
            }
            if self._upsert_points([point]):
                count += 1
        return count

    def index_mail(self, since=None):
        if not self.config:
            return 0
        domain = [("body", "!=", False), ("message_type", "in", ["email", "comment"])]
        if since:
            domain.append(("write_date", ">", since))
        messages = self.env["mail.message"].search_read(
            domain, ["id", "subject", "body", "author_id", "write_date"]
        )
        count = 0
        for msg in messages:
            body = html2plaintext(msg.get("body") or "")
            subject = msg.get("subject") or ""
            content = self._sanitize(f"{subject}\n{body}")
            if len(content) < 30:
                continue
            vector = self._embed(content)
            if not vector:
                continue
            if not self._ensure_collection(len(vector)):
                return count
            author = msg.get("author_id")
            point = {
                "id": f"mail_{msg['id']}",
                "vector": vector,
                "payload": {
                    "source": "mail",
                    "record_id": msg["id"],
                    "title": subject,
                    "author": author[1] if author else "",
                    "content": content,
                    "updated": msg.get("write_date"),
                },
            }
            if self._upsert_points([point]):
                count += 1
        return count

    def search(self, query, source, limit=5):
        if not self.config:
            return "⚠️ No hay configuración de Qdrant activa."
        vector = self._embed(query)
        if not vector:
            return "⚠️ No se pudo generar embedding."
        if not self._ensure_collection(len(vector)):
            return "⚠️ Qdrant no está disponible."
        payload = {
            "vector": vector,
            "limit": limit,
            "with_payload": True,
            "filter": {"must": [{"key": "source", "match": {"value": source}}]},
        }
        url = f"{self._collection_url()}/points/search"
        try:
            res = requests.post(url, json=payload, headers=self._headers(), timeout=20)
            if res.status_code != 200:
                _logger.warning("Qdrant search error: %s", res.text[:200])
                return "⚠️ Error consultando Qdrant."
            hits = res.json().get("result", [])
            if not hits:
                return "No encontré resultados relevantes."
            lines = []
            for h in hits:
                payload = h.get("payload", {})
                title = payload.get("title") or "(sin título)"
                content = payload.get("content") or ""
                snippet = content[:200].replace("\n", " ")
                lines.append(f"• {title} — {snippet}...")
            return "\n".join(lines)
        except Exception:
            return "⚠️ Qdrant no está disponible."
