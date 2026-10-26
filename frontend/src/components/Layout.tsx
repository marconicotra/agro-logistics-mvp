import { NavLink, Outlet } from "react-router-dom";
import { supabaseClient } from "../auth/supabase";
import { Icon } from "./Icon";

const navItems = [
  { to: "/dashboard", label: "Inicio", icon: "dashboard" },
  { to: "/conversations", label: "Conversaciones", icon: "chat" },
  { to: "/notifications", label: "Avisos", icon: "bell" },
  { to: "/shipments", label: "Cargas", icon: "box" },
  { to: "/trips", label: "Viajes", icon: "truck" },
  { to: "/route-availabilities", label: "Recorridos disponibles", icon: "map" },
  { to: "/producers", label: "Productores", icon: "people" },
  { to: "/carriers", label: "Transportistas", icon: "users" },
  { to: "/whatsapp-allowlist", label: "Acceso a WhatsApp", icon: "shield" },
  { to: "/catalogs", label: "Catálogos", icon: "settings" }
];

export function Layout() {
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">AG</div>
          <div>
            <strong>AGRO Logistics</strong>
            <span>Panel de gestión</span>
          </div>
        </div>
        <nav>
          {navItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) => (isActive ? "nav-link active" : "nav-link")}
            >
              <Icon name={item.icon} />
              <span>{item.label}</span>
            </NavLink>
          ))}
        </nav>
        {supabaseClient ? <button type="button" className="secondary-button auth-signout" onClick={() => { void supabaseClient?.auth.signOut(); }}>Cerrar sesión</button> : null}
      </aside>
      <main className="main-content">
        <Outlet />
      </main>
    </div>
  );
}
