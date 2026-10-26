import { Navigate, Route, Routes } from "react-router-dom";
import { AuthGate } from "./auth/AuthGate";
import { Layout } from "./components/Layout";
import { CarrierStatus } from "./pages/CarrierStatus";
import { CarrierCreate } from "./pages/CarrierCreate";
import { CarrierDetail } from "./pages/CarrierDetail";
import { Carriers } from "./pages/Carriers";
import { Conversations } from "./pages/Conversations";
import { ConversationDetail } from "./pages/ConversationDetail";
import { Dashboard } from "./pages/Dashboard";
import { NotificationOutbox } from "./pages/NotificationOutbox";
import { ProducerDetail } from "./pages/ProducerDetail";
import { Producers } from "./pages/Producers";
import { ProducerStatus } from "./pages/ProducerStatus";
import { ShipmentDetail } from "./pages/ShipmentDetail";
import { Shipments } from "./pages/Shipments";
import { TripTracking } from "./pages/TripTracking";
import { Trips } from "./pages/Trips";
import { RouteAvailabilities } from "./pages/RouteAvailabilities";
import { WhatsappAllowlist } from "./pages/WhatsappAllowlist";
import { Catalogs } from "./pages/Catalogs";

export function App() {
  return (
    <Routes>
      <Route path="/producer-status" element={<ProducerStatus />} />
      <Route path="/carrier-status" element={<CarrierStatus />} />
      <Route path="/carrier-status/:carrierId" element={<CarrierStatus />} />
      <Route element={<AuthGate />}>
        <Route element={<Layout />}>
          <Route index element={<Navigate to="/dashboard" replace />} />
          <Route path="/dashboard" element={<Dashboard />} />
          <Route path="/conversations" element={<Conversations />} />
          <Route path="/conversations/:conversationId" element={<ConversationDetail />} />
          <Route path="/notifications" element={<NotificationOutbox />} />
          <Route path="/producers" element={<Producers />} />
          <Route path="/producers/:producerId" element={<ProducerDetail />} />
          <Route path="/shipments" element={<Shipments />} />
          <Route path="/shipments/:shipmentId" element={<ShipmentDetail />} />
          <Route path="/trips" element={<Trips />} />
          <Route path="/trips/:tripId/tracking" element={<TripTracking />} />
          <Route path="/route-availabilities" element={<RouteAvailabilities />} />
          <Route path="/carriers" element={<Carriers />} />
          <Route path="/carriers/new" element={<CarrierCreate />} />
          <Route path="/carriers/:carrierId" element={<CarrierDetail />} />
          <Route path="/whatsapp-allowlist" element={<WhatsappAllowlist />} />
          <Route path="/catalogs" element={<Catalogs />} />
        </Route>
      </Route>
    </Routes>
  );
}
