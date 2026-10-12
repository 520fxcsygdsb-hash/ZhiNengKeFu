import { useEffect, useState } from "react";
import { NavLink, Route, Routes } from "react-router-dom";
import KnowledgePage from "./pages/Knowledge";
import ComplaintsPage from "./pages/Complaints";
import HandoffsPage from "./pages/Handoffs";
import DashboardPage from "./pages/Dashboard";
import MetricsPage from "./pages/Metrics";
import InferencePage from "./pages/Inference";
import PersonalizePage from "./pages/Personalize";
import SettingsBar from "./components/SettingsBar";
import { applyAdminFonts, getAdminLang, t } from "./i18n";

export default function App() {
  const [lang, setLang] = useState(getAdminLang());

  useEffect(() => {
    applyAdminFonts();
    const handler = () => {
      setLang(getAdminLang());
      applyAdminFonts();
    };
    window.addEventListener("kefu-lang-changed", handler);
    window.addEventListener("kefu-font-changed", handler);
    return () => {
      window.removeEventListener("kefu-lang-changed", handler);
      window.removeEventListener("kefu-font-changed", handler);
    };
  }, []);

  return (
    <div className="admin-layout">
      <aside className="admin-sidebar">
        <h1>{t("adminTitle", lang)}</h1>
        <nav>
          <NavLink to="/" end>{t("dashboard", lang)}</NavLink>
          <NavLink to="/knowledge">{t("knowledge", lang)}</NavLink>
          <NavLink to="/complaints">{t("complaints", lang)}</NavLink>
          <NavLink to="/handoffs">{t("handoffs", lang)}</NavLink>
          <NavLink to="/metrics">{t("metrics", lang)}</NavLink>
          <NavLink to="/inference">{t("inference", lang)}</NavLink>
          <NavLink to="/personalize">{t("personalize", lang)}</NavLink>
          <a href="/" target="_blank" rel="noreferrer">{t("frontend", lang)}</a>
        </nav>
        <SettingsBar />
      </aside>
      <main className="admin-main">
        <Routes>
          <Route path="/" element={<DashboardPage />} />
          <Route path="/knowledge" element={<KnowledgePage />} />
          <Route path="/complaints" element={<ComplaintsPage />} />
          <Route path="/handoffs" element={<HandoffsPage />} />
          <Route path="/metrics" element={<MetricsPage />} />
          <Route path="/inference" element={<InferencePage />} />
          <Route path="/personalize" element={<PersonalizePage />} />
        </Routes>
      </main>
    </div>
  );
}