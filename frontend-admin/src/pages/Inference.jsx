import { useState } from "react";
import { runInference } from "../api";

export default function InferencePage() {
  const [prompt, setPrompt] = useState("手机质保多久？");
  const [answer, setAnswer] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function onSubmit(e) {
    e.preventDefault();
    setLoading(true);
    setError("");
    setAnswer("");
    try {
      const data = await runInference(
        [{ role: "user", content: prompt }],
        256
      );
      setAnswer(data.answer);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div>
      <header className="page-header">
        <h2>Kimi 推理测试</h2>
      </header>
      <p className="muted">
        调用 POST /inference，使用云端 Kimi（Moonshot）模型直接回答你的问题。
      </p>
      <form className="inference-form" onSubmit={onSubmit}>
        <label>
          用户问题
          <textarea
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            rows={4}
          />
        </label>
        <button type="submit" disabled={loading}>
          {loading ? "推理中…" : "运行推理"}
        </button>
      </form>
      {error && <p className="error">{error}</p>}
      {answer && (
        <section className="inference-result">
          <h3>回答</h3>
          <pre>{answer}</pre>
        </section>
      )}
    </div>
  );
}
