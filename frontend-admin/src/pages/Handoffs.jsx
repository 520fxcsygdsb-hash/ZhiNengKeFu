import { useCallback, useEffect, useState } from "react";
import {
  claimHandoff,
  getHandoffDetail,
  listHandoffs,
  replyHandoff,
  resolveHandoff,
} from "../api";

const STATUS_LABELS = {
  waiting: "排队中",
  active: "接待中",
  resolved: "已结束",
  cancelled: "已取消",
};

export default function HandoffsPage() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [filter, setFilter] = useState("waiting");
  const [selectedId, setSelectedId] = useState("");
  const [detail, setDetail] = useState(null);
  const [replyText, setReplyText] = useState("");
  const [busyId, setBusyId] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const data = await listHandoffs(filter || undefined);
      setItems(data.items || []);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [filter]);

  const loadDetail = useCallback(async (id) => {
    if (!id) {
      setDetail(null);
      return;
    }
    try {
      const data = await getHandoffDetail(id);
      setDetail(data);
    } catch (e) {
      setError(e.message);
    }
  }, []);

  useEffect(() => {
    load();
    const timer = setInterval(load, 8000);
    return () => clearInterval(timer);
  }, [load]);

  useEffect(() => {
    if (!selectedId) return undefined;
    loadDetail(selectedId);
    const timer = setInterval(() => loadDetail(selectedId), 5000);
    return () => clearInterval(timer);
  }, [selectedId, loadDetail]);

  async function onClaim(id) {
    setBusyId(id);
    try {
      await claimHandoff(id);
      setSelectedId(id);
      await load();
      await loadDetail(id);
    } catch (e) {
      alert(e.message);
    } finally {
      setBusyId("");
    }
  }

  async function onReply(id) {
    const text = replyText.trim();
    if (!text) return;
    setBusyId(id);
    try {
      await replyHandoff(id, text);
      setReplyText("");
      await load();
      await loadDetail(id);
    } catch (e) {
      alert(e.message);
    } finally {
      setBusyId("");
    }
  }

  async function onResolve(id) {
    setBusyId(id);
    try {
      await resolveHandoff(id);
      await load();
      await loadDetail(id);
    } catch (e) {
      alert(e.message);
    } finally {
      setBusyId("");
    }
  }

  return (
    <div>
      <header className="page-header">
        <h2>人工客服队列</h2>
        <p className="muted">接手会话后查看完整对话并回复，结束后恢复智能机器人。</p>
      </header>

      <div className="toolbar">
        <label>
          状态筛选
          <select value={filter} onChange={(e) => setFilter(e.target.value)}>
            <option value="waiting">排队中</option>
            <option value="active">接待中</option>
            <option value="resolved">已结束</option>
            <option value="">全部</option>
          </select>
        </label>
        <button type="button" onClick={load} disabled={loading}>
          刷新
        </button>
      </div>

      {error && <p className="error">{error}</p>}

      <div className="handoff-layout">
        <table className="data-table">
          <thead>
            <tr>
              <th>工单号</th>
              <th>状态</th>
              <th>原因</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {items.map((h) => (
              <tr
                key={h.id}
                className={selectedId === h.id ? "row-active" : ""}
                onClick={() => setSelectedId(h.id)}
              >
                <td>{h.ticket_id}</td>
                <td>{STATUS_LABELS[h.status] || h.status}</td>
                <td className="reason-cell">{h.reason || "—"}</td>
                <td className="handoff-actions" onClick={(e) => e.stopPropagation()}>
                  {h.status === "waiting" && (
                    <button
                      type="button"
                      onClick={() => onClaim(h.id)}
                      disabled={busyId === h.id}
                    >
                      接手
                    </button>
                  )}
                  {(h.status === "waiting" || h.status === "active") && (
                    <button
                      type="button"
                      className="btn-muted"
                      onClick={() => onResolve(h.id)}
                      disabled={busyId === h.id}
                    >
                      结束
                    </button>
                  )}
                </td>
              </tr>
            ))}
            {!loading && items.length === 0 && (
              <tr>
                <td colSpan={4}>暂无转人工请求</td>
              </tr>
            )}
          </tbody>
        </table>

        <section className="handoff-detail">
          {!detail && <p className="muted">选择左侧工单查看对话</p>}
          {detail && (
            <>
              <h3>
                {detail.ticket_id} · {STATUS_LABELS[detail.status] || detail.status}
              </h3>
              <p className="muted">会话 {detail.session_id}</p>
              <div className="handoff-thread">
                {(detail.messages || []).map((m) => (
                  <div key={m.id} className={`thread-msg role-${m.role}`}>
                    <strong>
                      {m.role === "agent"
                        ? "坐席"
                        : m.role === "user"
                          ? "用户"
                          : "机器人"}
                    </strong>
                    <p>{m.content}</p>
                  </div>
                ))}
              </div>
              {(detail.status === "waiting" || detail.status === "active") && (
                <div className="handoff-reply-box">
                  <textarea
                    rows={3}
                    placeholder="回复用户…"
                    value={replyText}
                    onChange={(e) => setReplyText(e.target.value)}
                  />
                  <button
                    type="button"
                    onClick={() => onReply(detail.id)}
                    disabled={busyId === detail.id}
                  >
                    发送回复
                  </button>
                </div>
              )}
            </>
          )}
        </section>
      </div>
    </div>
  );
}
