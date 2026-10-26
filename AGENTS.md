# Reglas Globales Para Agentes AI

Este documento define reglas obligatorias para cualquier agente AI que trabaje sobre AGRO Logistics MVP.

## Principios Generales

- Leer la documentacion del repositorio antes de generar codigo, proponer cambios o modificar flujos.
- Leer `docs/plan-y-bitacora.md` antes de trabajar. Es el registro principal de prioridades, tareas, decisiones y avances; actualizarlo al cerrar cada sesion con decisiones, archivos cambiados y verificaciones ejecutadas.
- Consultar `docs/22-data-standardization.md` al extraer, validar o cambiar datos de dominio. No agregar listas de valores o alias aisladas en prompts/agentes sin definir su fuente canonica en backend y documentarla.
- Registrar en la bitacora solo informacion operativa no sensible: nunca secretos, valores de `.env`, telefonos ni mensajes personales.
- `todo.md` es un backlog legado y queda fuera del plan operativo. No consultarlo ni actualizarlo como fuente de tareas salvo pedido explicito del usuario.
- `prompts/` contiene prompts historicos, no el roadmap vigente; usar la bitacora y el alcance actual para elegir tareas.
- No inventar reglas de negocio.
- Priorizar simplicidad MVP sobre completitud teorica.
- Priorizar operacion real sobre elegancia tecnica.
- Mantener el foco en transporte de hacienda y granos en Argentina.
- No implementar features fuera del alcance documentado en `docs/04-mvp-scope.md`. Si el usuario propone ampliar el producto, registrar primero la propuesta y sus dependencias en `docs/plan-y-bitacora.md`; antes de implementarla, actualizar el alcance y los documentos de dominio afectados.

## Separacion De Responsabilidades

Los agentes deben mantener separadas estas capas conceptuales:

| Capa | Responsabilidad | Regla |
| --- | --- | --- |
| Canal | WhatsApp u otro medio de entrada/salida | No debe contener reglas de negocio centrales |
| Logica | Flujo de carga, matching sugerido, estados y validaciones | Debe ser independiente del canal |
| Datos | Cargas, transportistas, respuestas, viajes y eventos | Debe preservar historial y trazabilidad |

WhatsApp es el canal del MVP, no el dominio del producto.

## Reglas Operativas

- Registrar eventos siempre que ocurra una accion relevante.
- Mantener consistencia de estados entre carga, interesados y viaje.
- No automatizar decisiones criticas sin validacion humana.
- Escalar al operador cuando falten datos importantes.
- Escalar al operador cuando haya conflictos, cancelaciones o respuestas ambiguas.
- No confirmar por el interes unilateral del transportista. La aceptacion explicita del productor confirma el match y habilita `Assignment.CONFIRMED` + `Trip.PLANNED`, segun `docs/04-mvp-scope.md`; soporte interviene en excepciones.
- No asignar transportistas automaticamente.
- No asumir precio, disponibilidad, cantidad de animales ni condiciones sanitarias si no fueron informadas.

## Documentacion

Actualizar la documentacion cuando cambie:

- El alcance del MVP.
- El modelo operativo.
- Los estados de carga o viaje.
- Los datos minimos requeridos.
- Las reglas de intervencion humana.
- Las skills disponibles.

Si una decision no esta documentada, el agente debe marcarla como pendiente y no tratarla como regla establecida.

## Criterio De Calidad

Un agente AI trabaja correctamente cuando:

- Reduce trabajo manual sin ocultar informacion.
- Hace explicitas las dudas.
- Mantiene trazabilidad.
- Ayuda al operador a decidir mejor.
- Evita automatizaciones prematuras.
- Respeta el alcance semi-automatico del MVP.

## Pruebas QA con WhatsApp

- El cambio de rol solo funciona con `ENABLE_TEST_ROLE_SWITCHING=true`, fuera de produccion y para un telefono permitido por la allowlist.
- En ese modo, iniciar cada recorrido con `/test iniciar`, cambiar el rol con `/soy productor` o `/soy transportista`, y cerrar con `/test cerrar`.
- No mezclar escenarios ni consultar datos de pruebas cerradas como datos normales. Preservar los registros etiquetados; no borrar datos generales entre escenarios.
- El mismo telefono puede representar ambos roles solo dentro del escenario de prueba. No conectar un telefono personal como numero de produccion.
- Antes de exponer un webhook, exigir secreto HMAC no predeterminado, allowlist cerrada, `INTERNAL_API_KEY` fuerte y proteccion de endpoints administrativos.
- `INTERNAL_API_KEY` es solo backend-a-backend; nunca exponerla con `VITE_*` ni enviarla desde el navegador. Los headers de usuario/rol son solo para desarrollo local. No habilitar el backoffice humano en entornos compartidos hasta integrar Supabase Auth con roles verificados en servidor y auditoria de lecturas sensibles.
