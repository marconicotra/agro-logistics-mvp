import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { api } from "../api/client";
import { PageState } from "../components/PageState";
import { formatDate } from "../format";
import { entityLabel } from "../labels";
import type { ConversationMessage } from "../types";

function messageLabel(message: ConversationMessage): string {
  if (message.direction.toLowerCase() === "system") return "Sistema";
  if (message.direction.toLowerCase() === "outbound") return "Asistente";
  return message.qa_role ? entityLabel(message.qa_role) : entityLabel(message.sender_type);
}

function messageIcon(message: ConversationMessage): string {
  if (message.direction.toLowerCase() === "system") return "⚙️";
  return message.direction.toLowerCase() === "outbound" ? "🤖" : "👤";
}

function messageBody(message: ConversationMessage): string {
  if (message.content) return message.content;
  if (message.message_type.toLowerCase() !== "text") {
    return `Mensaje de ${entityLabel(message.message_type).toLocaleLowerCase("es-AR")}; el archivo no está disponible en esta vista.`;
  }
  return "Mensaje sin texto.";
}

export function ConversationDetail() {
  const { conversationId } = useParams();
  const [messages, setMessages] = useState<ConversationMessage[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadingOlder, setLoadingOlder] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [olderCursor, setOlderCursor] = useState<string | null>(null);
  const [latestCursor, setLatestCursor] = useState<string | null>(null);
  const [hasOlder, setHasOlder] = useState(false);
  const [newMessageCount, setNewMessageCount] = useState(0);
  const scrollRef = useRef<HTMLDivElement>(null);
  const pollingRef = useRef(false);
  const latestCursorRef = useRef<string | null>(null);
  const messagesRef = useRef<ConversationMessage[]>([]);
  messagesRef.current = messages;

  const loadInitial = useCallback(async () => {
    if (!conversationId) return;
    setLoading(true);
    setError(null);
    setMessages([]);
    setOlderCursor(null);
    setLatestCursor(null);
    latestCursorRef.current = null;
    setHasOlder(false);
    setNewMessageCount(0);
    try {
      const page = await api.conversationMessagePage(conversationId);
      setMessages(page.items);
      setOlderCursor(page.next_cursor);
      setLatestCursor(page.latest_cursor);
      latestCursorRef.current = page.latest_cursor;
      setHasOlder(page.has_more);
      requestAnimationFrame(() => {
        const panel = scrollRef.current;
        if (panel) panel.scrollTop = panel.scrollHeight;
      });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "No se pudo cargar la conversación.");
    } finally {
      setLoading(false);
    }
  }, [conversationId]);

  useEffect(() => { void loadInitial(); }, [loadInitial]);

  const loadOlder = async () => {
    if (!conversationId || !olderCursor || loadingOlder) return;
    const panel = scrollRef.current;
    const previousHeight = panel?.scrollHeight ?? 0;
    const previousTop = panel?.scrollTop ?? 0;
    setLoadingOlder(true);
    setError(null);
    try {
      const page = await api.conversationMessagePage(conversationId, { cursor: olderCursor, direction: "older" });
      setMessages((current) => {
        const known = new Set(current.map((item) => item.id));
        return [...page.items.filter((item) => !known.has(item.id)), ...current];
      });
      setOlderCursor(page.next_cursor);
      setHasOlder(page.has_more);
      requestAnimationFrame(() => {
        if (panel) panel.scrollTop = previousTop + panel.scrollHeight - previousHeight;
      });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "No se pudieron cargar los mensajes anteriores.");
    } finally {
      setLoadingOlder(false);
    }
  };

  useEffect(() => {
    if (!conversationId || !latestCursor) return;
    const timer = window.setInterval(async () => {
      if (document.visibilityState !== "visible" || pollingRef.current || !latestCursorRef.current) return;
      pollingRef.current = true;
      const panel = scrollRef.current;
      const wasAtBottom = !panel || panel.scrollHeight - panel.scrollTop - panel.clientHeight < 60;
      try {
        const page = await api.conversationMessagePage(conversationId, { cursor: latestCursorRef.current, direction: "newer" });
        if (page.items.length) {
          const known = new Set(messagesRef.current.map((item) => item.id));
          const additions = page.items.filter((item) => !known.has(item.id));
          if (additions.length) {
            setMessages((current) => {
              const currentIds = new Set(current.map((item) => item.id));
              return [...current, ...additions.filter((item) => !currentIds.has(item.id))].sort(
                (left, right) => left.occurred_at.localeCompare(right.occurred_at) || left.id.localeCompare(right.id)
              );
            });
            if (wasAtBottom) requestAnimationFrame(() => { if (panel) panel.scrollTop = panel.scrollHeight; });
            else setNewMessageCount((count) => count + additions.length);
          }
          const cursor = page.latest_cursor;
          if (cursor) {
            latestCursorRef.current = cursor;
            setLatestCursor(cursor);
          }
        }
      } catch {
        // A transient polling error should not replace the conversation or hide its history.
      } finally {
        pollingRef.current = false;
      }
    }, 10_000);
    return () => window.clearInterval(timer);
  }, [conversationId, latestCursor]);

  const jumpToLatest = () => {
    const panel = scrollRef.current;
    if (panel) panel.scrollTo({ top: panel.scrollHeight, behavior: "smooth" });
    setNewMessageCount(0);
  };

  return (
    <section className="page">
      <header className="page-header">
        <div>
          <Link className="inline-link" to="/conversations">← Conversaciones</Link>
          <h1>Conversación</h1>
          <p>Mensajes de la persona y del asistente, del más antiguo al más reciente.</p>
        </div>
        <button type="button" className="secondary-button" onClick={() => void loadInitial()} disabled={loading}>↻ Actualizar</button>
      </header>
      <PageState loading={loading} error={error} empty={messages.length === 0} emptyTitle="Esta conversación todavía no tiene mensajes" onRefresh={() => void loadInitial()}>
        {hasOlder ? <div className="conversation-history-actions"><button type="button" className="secondary-button" onClick={() => void loadOlder()} disabled={loadingOlder}>{loadingOlder ? "Cargando…" : "↑ Cargar mensajes anteriores"}</button></div> : null}
        {newMessageCount > 0 ? <div className="conversation-new-messages"><button type="button" className="primary-button" onClick={jumpToLatest}>↓ Hay {newMessageCount} mensaje{newMessageCount === 1 ? "" : "s"} nuevo{newMessageCount === 1 ? "" : "s"}</button></div> : null}
        <div className="conversation-scroll" ref={scrollRef} onScroll={() => {
          const panel = scrollRef.current;
          if (panel && panel.scrollHeight - panel.scrollTop - panel.clientHeight < 40) setNewMessageCount(0);
        }}>
          <div className="conversation-thread" aria-label="Historial cronológico de mensajes">
            {messages.map((message) => {
              const direction = message.direction.toLowerCase();
              const outbound = direction === "outbound";
              return (
                <article key={message.id} className={`conversation-message ${direction === "system" ? "system" : outbound ? "outbound" : "inbound"}`}>
                  <div className="conversation-message-meta"><strong>{messageIcon(message)} {messageLabel(message)}</strong><time dateTime={message.occurred_at}>{formatDate(message.occurred_at)}</time></div>
                  <p>{messageBody(message)}</p>
                  {message.delivery_status === "accepted_by_provider" ? <small className="conversation-status">El proveedor aceptó el envío; la entrega final no está verificada.</small> : null}
                  {message.delivery_status === "failed" ? <small className="conversation-status failed">No se pudo enviar la respuesta.</small> : null}
                  {message.test_run_id ? <small className="conversation-scenario">Escenario de prueba: {message.test_run_id}</small> : null}
                </article>
              );
            })}
          </div>
        </div>
      </PageState>
    </section>
  );
}
