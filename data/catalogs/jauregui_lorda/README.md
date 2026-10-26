# Importación geográfica heredada: Jauregui Lorda

Fuente: respaldo provisto por el usuario `backup_16_jauregui_lorda_geo_localidades.json`.

- SHA-256 de la fuente original: `7d8f025febeaaf77708bbcb5bdca66601393dbf93c0da524a2c952f468a5bff3`.
- Registros originales: 2.384; campos: `id`, `departamento`, `localidad`.
- Los 24 valores distintos de `departamento` corresponden a provincias, no a partidos/departamentos administrativos. `CABA` y `Tierra del Fuego` se alinean con el nombre oficial de Georef y se guardan como alias.
- El seed Georef de `0017` ya contiene las coincidencias geográficas exactas. El conjunto de este directorio incluye solo localidades no encontradas por coincidencia exacta provincia + localidad; se deduplicó por ambos campos.
- Se prepararon 773 localidades no coincidentes como candidatas de revisión. Se excluyeron 48 valores genéricos (`Otra Localidad`, `Sin especificar`) y dos registros con formato de domicilio. No se importaron IDs ni timestamps del sistema de origen.
- Los nombres resultantes se cargan como filas `LOCALITY`, vinculadas directamente a la provincia indicada, con `source=JAUREGUI_LORDA` y `active=false`. Son candidatos para revisión manual y no los consume el agente hasta que un administrador los active. El archivo original no trae partidos; no se inventan.
- Archivo de seed: `localidades_para_revision.json`. Revisión aplicada por la migración `0018_jauregui_geo_localities`.
