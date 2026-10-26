# Estandarizacion de datos de dominio

Este documento indica que debe consultar un agente y que controles corresponden al backend para leer y guardar datos de AGRO Logistics. Categorías, tipos y alias de carga ahora pueden mantenerse desde el backoffice; en modo SQL, el parser y OpenAI consultan el catálogo activo. Provincias, partidos/departamentos y localidades se importan desde el snapshot local de Georef y también tienen ABM. La migración `0017_managed_catalogs` está creada y aún debe aplicarse explícitamente al ambiente SQL elegido.

## Fuente de verdad

- Conceptos y entidades: `docs/07-domain-model.md`.
- Estados y transiciones: `docs/08-state-machine.md`.
- Contrato para el runtime: este documento.
- Fuente canonica de categorias, tipos y alias editables: catalogo de base de datos administrado por backoffice; `backend/app/domain/cargo.py` provee el conjunto inicial y fallback local. En modo SQL, parser, adaptador OpenAI y backoffice consultan la misma version activa del catalogo.
- Alias de equipo declarados: `backend/app/domain/equipment.py`. El onboarding canoniza alias conocidos; conserva texto desconocido para revision humana.
- Snapshot de localidades: `data/catalogs/georef/localidades.csv`; fuente, recuperacion, filas y SHA en `data/catalogs/georef/README.md`. La migracion siembra provincias, partidos/departamentos y localidades en las tablas geograficas; el runtime SQL resuelve desde el catalogo mantenible por backoffice. El snapshot queda como fuente de importacion/fallback local.
- Complemento heredado revisado: `data/catalogs/jauregui_lorda/README.md`. Sus valores de `departamento` son provincias; localidades nuevas quedan inactivas para revisión, sin ID Georef ni activación del agente. El archivo no contiene partidos/departamentos administrativos.
- Implementacion de otras reglas: `backend/app/application/chat_shipment_parser.py`, `backend/app/infrastructure/adapters/openai_ai.py` y `backend/app/domain/models.py`.
- Registro de prioridades, decisiones y avances: `docs/plan-y-bitacora.md`.

El modelo de lenguaje no es la fuente canonica. Puede extraer candidatos del chat, pero el backend debe validar esos candidatos antes de mostrarlos como confirmados o persistirlos como valores canonicos. El agente no debe leer ni escribir la base directamente.

## Reglas recomendadas de lectura y escritura

1. Conservar la expresion original del usuario y su mensaje fuente.
2. Normalizar con una unica funcion/servicio de dominio compartido por WhatsApp, IA y backoffice.
3. Mantener por campo el valor canonico, la unidad, la confianza, la fuente y el estado de revision cuando aplique.
4. Si falta un dato obligatorio o hay mas de una interpretacion valida, preguntar o derivar a una persona. No completar por conocimiento general del modelo.
5. Los catalogos deben exponer valores canonicos y alias; los alias apuntan a un solo valor canonico. Un alias conflictivo no se resuelve automaticamente.
6. Cada actualizacion relevante debe quedar asociada a su mensaje/evento de origen y preservar la trazabilidad.

## Datos que conviene estandarizar

| Dato | Forma canonica inicial observada | Regla |
| --- | --- | --- |
| Categoria de carga | Código estable (`LIVESTOCK`, `GRAIN` y los que agregue un administrador) | Resolver por código, nombre o alias activo del catálogo; una categoría nueva requiere alta administrativa, no basta con que la proponga la IA. |
| Tipo de carga | Tipos activos del catálogo administrable, con conjunto inicial en `domain/cargo.py` | Resolver alias a valor estable; un producto fuera del catálogo queda declarado y pide revisión. El mensaje original se conserva como fuente. |
| Cantidad y unidad | `Decimal` + `HEAD`, `TON`, `KG` o `TRUCKLOAD` | El nombre contado de animales establece `HEAD`; en granos no inferir unidad si no se informó. Un peso indicado por animal se guarda aparte como `weight_per_head_kg`. |
| Pesaje de hacienda | `weight_per_head_kg` en kg por cabeza | Campo opcional y distinto del peso total de la carga; aceptar solo si se declara. No convertirlo en cantidad de cabezas ni inferir peso total. |
| Origen/destino | ID/nombre Georef, provincia y referencia rural opcional | Mantener texto original; canonizar solo coincidencia unica. Homonimos no se eligen automaticamente; fuera de catalogo queda `USER_DECLARED`. |
| Fecha/ventana | ISO 8601 en backend, con interpretacion en `America/Argentina/Buenos_Aires` | Una expresion relativa debe convertirse a fecha concreta antes de confirmar; no inventar extremos de una ventana. |
| Estado operativo | Valores documentados en `docs/08-state-machine.md` | Transiciones por servicios de dominio, con evento y actor; no asignar estados libres desde el prompt. |
| Vehiculo y documentacion | Aliases iniciales de equipo en `domain/equipment.py`, mas identificador/estado de documento y revision | Canonizar alias conocidos; conservar tipos nuevos como declarados y pendientes de soporte. La matriz documental sigue pendiente. |
| Disponibilidad de recorrido | Ruta/corredor, ventana, capacidad y unidad, tipos de carga/equipo, paradas y desvio aceptado | Separar capacidad declarada de capacidad comprometida; no inferir una ruta ni disponibilidad desde las zonas preferidas. |
| Preferencias del transportista | Zonas/corredores y criterios de difusion | Preferencia habilita busqueda/aviso, pero no afirma capacidad para una fecha. |
| Homologacion | Perfil de carrier persona/empresa, contacto principal, email, CUIT, conductores, vehiculos y referencias privadas a documentos | Carrier, persona de contacto, conductor y vehiculo son entidades distintas. Dato declarado no equivale a dato verificado; conservar estado, actor revisor y motivo. |
| Mensaje de conversacion | Emisor/actor, direccion, timestamp, contenido o referencia segura, estado de entrega | Distinguir humano, agente y sistema; aplicar permisos y retencion. |
| Identidad/contacto | Telefono normalizado E.164 asociado a un `User`, relacionado por separado con perfiles Producer, Carrier y Driver | El telefono identifica al contacto, no a la empresa ni necesariamente al conductor. Distinguir rol de prueba de identidad real; no duplicar personas porque alternen productor/transportista en QA. |
| Confianza/proveniencia | `unknown`, `estimated`, `provided`, `validated`, `corrected`, segun dominio | Registrar por campo; una extraccion de IA no pasa a `validated` por tener confianza alta. |

No completar precio, disponibilidad, cantidad, ubicacion exacta, condiciones sanitarias o datos de flota por inferencia. Mantenerlos ausentes y preguntar cuando sean necesarios.

## Estado actual respaldado por codigo

- `chat_shipment_parser.py` recibe el catálogo activo de SQL en runtime (y usa el catálogo de dominio como fallback local); extrae cantidad/unidad, ruta y fechas relativas.
- Las categorías, tipos y alias se mantienen en `cargo_categories` y `cargo_types`; `domain/cargo.py` define el catálogo inicial/fallback. En SQL, OpenAI recibe las categorías y tipos activos en su prompt y la extracción se valida contra el mismo catálogo del parser. La unidad solo se acepta cuando el mensaje la expresa.
- El backoffice ofrece ABM de categorías, tipos, alias y activación/desactivación. Las mutaciones requieren rol administrador y dejan eventos de auditoría; un tipo no activo no participa en nuevas interpretaciones. Una categoría activa con tipos activos no se puede desactivar.
- `geographic_catalog` contiene provincias, partidos/departamentos y localidades con jerarquía, alias, origen, estado e ID Georef cuando existe. El ABM evita duplicados por zona y protege entradas superiores con dependencias activas. Las nuevas interpretaciones consultan la instantánea activa suministrada por SQL; los cambios no reescriben ubicaciones históricas.
- La revisión de datos heredados agrega los alias provinciales `CABA` y `Tierra del Fuego`; 773 localidades no coincidentes se importan inactivas, con origen `JAUREGUI_LORDA`, para que soporte las revise desde el ABM. El archivo de origen no separa partidos y no se usan esas candidatas para canonicalizar hasta que un administrador las active.
- `cargo_type` fuera del catalogo se conserva como declarado y queda marcado con confianza desconocida para revision.
- El parser solo asigna unidades expresadas o implícitas en el tipo de carga (`HEAD` cuando se cuenta hacienda; `TON`, `KG` o `TRUCKLOAD` cuando están escritos). Para granos, si se informa cantidad sin unidad, el chat pide aclararla antes de confirmar. En hacienda, «25 terneros de 300 kilos» separa 25 `HEAD` de 300 kg por cabeza. La unidad propuesta por IA se descarta sin evidencia textual. Una respuesta breve como «cabezas» o «toneladas» se reconoce como dato complementario. Validar y publicar desde soporte tambien bloquea cantidades sin unidad.
- El flujo SQL intenta resolver localidades contra el catálogo administrado; el modo local usa el snapshot versionado de Georef. Una coincidencia única conserva nombre/provincia/ID; no se confunde canonicalización con aprobación humana (`is_validated` sigue falso). Homónimos impiden auto-publicación; parajes y estancias conservan el texto original.
- La migración `0017_managed_catalogs` siembra provincias, partidos/departamentos, localidades y el catálogo inicial de carga desde los datos versionados. La migración `0018_jauregui_geo_localities` añade alias provinciales y 773 candidatos heredados inactivos. Se ejecutaron ambas directamente en SQLite en memoria; no se aplicaron a una base persistente. La cadena histórica completa no se validó en SQLite porque una migración anterior (`0007`) requiere operaciones PostgreSQL.

## Donde debe consultar un agente en runtime

El agente de conversación integrado no consulta directamente el CSV ni escribe SQL. El backend carga una instantánea de los catálogos activos y la comparte con el parser y el adaptador OpenAI. El ABM del backoffice usa endpoints autenticados del backend; un agente remoto independiente necesitaría consultar esos recursos por API, no acceder al CSV o a SQL.

Direccion propuesta para completar la implementacion:

- Mantener las unidades y validaciones en el dominio; categorías, tipos y alias editables se administran en base SQL y se comparten en runtime. No duplicar listas editables en instrucciones de agente.
- Si se incorpora un agente remoto independiente, hacer que use recursos autenticados de la API de catálogos, en lugar de copiar listas a prompts/workflows.
- Antes de crear o actualizar una carga, pasar cada campo por el mismo validador del backend. El backoffice debe usarlo tambien.
- Refrescar de forma revisada el snapshot Georef y sus referencias; no llamar servicios de geocoding desde cada conversacion.
- Versionar cambios de catalogo y registrar que version produjo cada canonicalizacion si el valor afecta matching o auditoria.

Hasta implementar ese servicio, los agentes deben basarse en los documentos de dominio y pedir aclaracion ante alias, unidades o lugares que el parser actual no reconozca. No deben prometer que un valor libre ya quedo normalizado.

## Decisiones de producto pendientes

- Tipos de hacienda y granos incluidos en el MVP y sus alias aceptados.
- Unidades admitidas por tipo de carga y comportamiento cuando el usuario omite unidad.
- Fuente geografica para localidades/provincias argentinas, manejo de parajes/establecimientos y desambiguacion.
- Datos y documentos minimos por transportista/vehiculo, vigencia y quien puede aprobar cada uno.
- Si un conductor puede estar asociado a mas de una empresa transportista; no bloquea el modelo MVP de un carrier persona/empresa con uno o varios conductores.
- Unidades/capacidad por categoria, tipos de vehiculo/carroceria aceptados y como modelar una capacidad ya comprometida parcialmente.
- Catalogo de zonas/corredores, geografia para medir cercania/desvio, tolerancias y vencimiento de disponibilidades.
- Documentos requeridos por perfil/vehiculo, vigencia, estados de revision y retencion de imagenes.

La lista inicial de productos y la fuente geográfica están implementadas; el catálogo ya puede ampliarse desde backoffice. Falta decidir documentos obligatorios, revisar alias en operación y definir equipos/capacidad por tipo de carga. Esas decisiones no habilitan inferir datos. Si se informa una cantidad sin unidad, tanto hacienda como granos requieren aclaración antes de mostrar la confirmación final, validar o publicar.

## Recorridos y seguimiento — ampliación 2026-10-25

Las preferencias habituales no acreditan disponibilidad. Comparar nodos geográficos canónicos y ordenados, sin eliminar la provincia ni resolver homónimos por inferencia. El viaje en IN_TRANSIT habilita tres controles (salida/mitad/llegada) vinculados al chofer y al escenario, independientes de los estados de entrega. Una posición informada no constituye prueba GPS continua ni cambia el estado del viaje. Los datos propios de ubicación y la geometría temporal del proveedor se tratan por separado.
