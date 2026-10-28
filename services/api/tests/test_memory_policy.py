from memory.classifier import _fallback_classify
from memory.store import validate_memory_fact

import pytest


@pytest.mark.parametrize(
    "summary,category",
    [
        ("El proveedor de Medellín entrega los miércoles", "proveedores"),
        ("Miami Beach cierra a las 23:00 los fines de semana", "horarios"),
        ("El apagón programado explica las alertas repetidas de ventas en cero", "incidentes_conocidos"),
        ("El gerente prefiere reportes en tabla", "preferencias"),
    ],
)
def test_accepts_briefing_memory_classes(summary, category):
    validate_memory_fact(summary, category)


@pytest.mark.parametrize(
    "summary",
    [
        "El salario del gerente es 5000 USD",
        "El cliente Brasa Points se llama Ana y su teléfono es 555-0100",
    ],
)
def test_rejects_sensitive_memory(summary):
    with pytest.raises(ValueError):
        validate_memory_fact(summary, "general")


def test_rejects_unknown_category():
    with pytest.raises(ValueError):
        validate_memory_fact("Hecho operativo recurrente", "personal_data")


@pytest.mark.parametrize(
    "message",
    [
        "¿Cuál fue el ticket promedio de ayer en Bogotá?",
        "Gracias, eso resuelve mi duda.",
        "Traduce esto al inglés para el reporte de Ashley.",
    ],
)
def test_ambiguous_or_new_topic_is_not_approval(message):
    assert _fallback_classify("El proveedor entrega los martes", message).intention == "unrelated"


def test_only_explicit_confirmation_approves():
    assert _fallback_classify("El proveedor entrega los martes", "sí").intention == "approved"
    assert _fallback_classify("El proveedor entrega los martes", "no sé").intention == "unrelated"


def test_search_response_uses_memory_search_results():
    from memory.routes import SearchResponse

    assert SearchResponse.model_fields["results"].annotation.__args__[0].__name__ == "MemorySearchResult"