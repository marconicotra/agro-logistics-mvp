# Product

AGRO Logistics MVP coordina transporte de hacienda y granos en Argentina.

El MVP es WhatsApp-first:

- productores piden camión por WhatsApp para hacienda o granos
- transportistas reciben oportunidades por WhatsApp
- operadores validan y seleccionan
- el backend registra estado y eventos

El sistema reduce trabajo manual sin ocultar información. No reemplaza la decisión humana en puntos críticos.

## Entidades Principales

- `ShipmentRequest`: necesidad de transporte agro, con categoría `LIVESTOCK` o `GRAIN`.
- `TripOffer`: respuesta o interés de un transportista.
- `Assignment`: selección operativa hecha por operador.
- `Trip`: viaje planificado o ejecutado.
- `EventLog`: auditoría de acciones relevantes.

## Estados Relevantes

- `PUBLISHED`: carga publicada a transportistas.
- `MATCHING`: hay interesados u ofertas para evaluar.
- `ASSIGNED`: operador confirmó asignación.
- `PLANNED`: viaje preparado.

Kapso no cambia estos estados directamente. Siempre llama backend.
