# Georef localidades

`localidades.csv` is a local snapshot of Argentina's official Georef v2 locality
resource. Runtime resolution reads this file and never calls the Georef API.

- Source: [Descarga de la base completa](https://www.argentina.gob.ar/georef/descarga-de-la-base-completa)
- Resource: `https://apis.datos.gob.ar/georef/api/v2.0/localidades.csv`
- Retrieved: 2026-10-10
- Rows including header: 4,029
- SHA-256: `7743fd6a6af96fce138696680afe297e71fc41f37f8d1986b3763913d0c86197`
- Runtime catalog version: the full SHA-256, calculated from the bundled bytes.

The source contains locality records and nested entities. The resolver excludes
rows categorized as `Entidad`, matches case/accents-insensitively, and only
resolves a name when one top-level record remains. Homonyms return candidate
provinces for clarification; unrecognized place or rural-establishment text is
retained as declared text rather than guessed. Refresh this snapshot as a
reviewed data update and rerun location matching tests.
