# Diseño RAG de Brasaland

## Objetivo y arquitectura

Este pipeline responde preguntas sobre la base de conocimiento interna de Brasaland usando recuperación semántica y generación fundamentada. Los cuatro documentos fuente son los Markdown de `docs/company-knowledge-base/`:

- `brasaland-loyalty-program.es.md` (aprox. 6 chunks)
- `brasaland-supplier-ordering.es.md` (aprox. 5 chunks)
- `brasaland-waste-protocol.es.md` (aprox. 6 chunks)
- `brasaland-menu-allergens.es.md` (aprox. 5 chunks)

Flujo extremo a extremo:

```text
Markdown fuente -> setup(): parseo + embed(chunk) -> Qdrant brasaland_knowledge
Pregunta -> query() -> embed(question) -> retrieve(k=5, min_score=0.35)
		 -> prompt con contexto -> LLM -> respuesta final
```

## Indexación (`setup()`)

`services/api/rag.py` localiza los documentos, los convierte en objetos `Chunk` y llama a `embed()` una vez por chunk. La colección se reconstruye con estrategia *clean-and-reload*: si existe `brasaland_knowledge`, se elimina y se crea de nuevo; después se insertan puntos con el vector y payload (`source_document`, `section`, `chunk_index`, `text`, idioma y empresa). Esto hace que una ejecución sea idempotente y no conserve chunks obsoletos.

La dimensión del vector la obtiene `setup()` del primer embedding y valida que todos los vectores tengan la misma dimensión. Qdrant usa `models.Distance.COSINE`; la dimensión concreta es la que devuelve el endpoint configurado y se valida dinámicamente.

## Chunking

El parser es híbrido y conservador: normaliza saltos de línea, separa por párrafos/bloques Markdown, detecta encabezados (`#` a `######`) y conserva la sección en metadata. Mantiene cada párrafo o lista como unidad mínima, por lo que reglas, umbrales, excepciones y condiciones no se cortan arbitrariamente. Si un bloque excede aproximadamente 1.200 caracteres, lo divide únicamente en finales de frase. Si un documento tuviera menos de tres unidades, divide el bloque más grande por frases, nunca a mitad de una línea/regla.

No se usa solapamiento fijo: en este corpus corto, las fronteras semánticas de párrafo y lista son más útiles que duplicar texto. El parser produce aproximadamente 5–6 chunks por documento (22 en total); el tamaño normal es inferior a 500 caracteres.

## Embeddings, recuperación y umbral

El modelo de embedding es `litellm/madrid-spain/openrouter/perplexity/pplx-embed-v1-0.6b`, proporcionado por 4Geeks mediante el gateway OpenAI-compatible. El modelo de generación es distinto: `litellm/madrid-spain/openrouter/deepseek/deepseek-v4-flash`, también proporcionado por 4Geeks cuando se usa ese gateway.

`embed(text)` es la única puerta de entrada al embedding: `setup()` la usa para indexar y `retrieve()` para la pregunta, con el mismo modelo, preprocesado y formato. Antes sólo se exige texto no vacío; el parser elimina espacios exteriores y normaliza `CRLF` a `LF`, sin traducir ni eliminar contenido de negocio. Los valores se convierten a `float`.

`retrieve()` solicita como máximo `k=5` vecinos y filtra después los resultados con score menor que `min_score`. El umbral predeterminado es `0.35`; no se rellenan artificialmente resultados descartados, así que pueden devolverse menos de `k`. Es un umbral conservador inicial para eliminar coincidencias débiles sin perder formulaciones con sinónimos. `data/eval/test-queries.json` contiene 8 preguntas, dos por documento, y el objetivo es Recall@3 >= 80% (al menos 7/8 con el chunk esperado entre los tres primeros).

## Consulta y generación (`query()`)

`query(question)` recupera contexto con `DEFAULT_MIN_SCORE` y lo pasa a `generate_answer()`. El prompt incluye textos recuperados con documento/sección, exige usar únicamente el contexto, declara cuándo falta información, mantiene el idioma de la pregunta y contiene reglas especiales para alérgenos, contaminación cruzada y conservación exacta de COP/USD.

`generate_answer()` invoca el endpoint compatible con OpenAI usando el modelo de generación configurado. `query()` devuelve exclusivamente `response.choices[0].message.content` limpio; nunca devuelve directamente texto de chunks. Si no hay contexto recuperado, `generate_answer()` devuelve inmediatamente «No encuentro esa información en la base de conocimiento de Brasaland.» y no llama al LLM. Una respuesta vacía del modelo produce error.

## Evaluación y pruebas

`tests/pipelines/test_rag.py` usa un stub Qdrant en memoria, sin red ni Qdrant vivo: verifica el filtrado por score y que pueden devolverse menos de `k`. También simula `retrieve()` y `generate_answer()` para verificar que `query()` devuelve la salida del modelo, no un chunk crudo.

```bash
python -m pytest tests/pipelines/test_rag.py
```

Para la evaluación, se recuperan los tres primeros resultados para cada consulta de `data/eval/test-queries.json` y se comprueba que el documento y chunk esperado aparecen entre ellos. El indicador es `aciertos / 8`; el criterio de aceptación es `7 / 8` (80%).

La colección obligatoria es `brasaland_knowledge` en Qdrant. `setup()` lee
todos los Markdown de `docs/company-knowledge-base/`, conserva párrafos y
listas como unidades mínimas y sólo divide en finales de frase. Cada documento
produce al menos tres chunks; por tanto no se parten frases ni reglas en mitad.

Cada punto incluye `source_document`, `section`, `company`, `language`,
`chunk_index` y `text`. El campo `text` es el cuerpo que debe incorporarse al
prompt después de recuperar contexto.

## Embeddings

`embed(text)` usa exclusivamente el modelo configurado en `EMBED_MODEL` a
través del gateway compatible con OpenAI configurado en `LLM_GATEWAY`, usando
`LLM_API_KEY`. La misma función debe utilizarse tanto para indexar chunks como
para vectorizar la pregunta de usuario; así se garantiza la misma dimensión y
espacio semántico.

## Idempotencia en desarrollo

Se eligió **clean-and-reload**: antes de insertar, `setup()` elimina
`brasaland_knowledge` si existe y la crea de nuevo con la dimensión devuelta
por el modelo. Después hace `upsert` con IDs deterministas derivados de
documento, índice y texto. Esto evita duplicados y elimina chunks obsoletos si
se modifica una fuente. La recreación requiere que Qdrant esté disponible.