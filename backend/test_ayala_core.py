from decimal import Decimal

import ayala_core
from ayala_core import (
    calcular_precio_condicion,
    calcular_precios_todas_condiciones,
    descubrir_publicaciones,
    detectar_condicion_pago,
    resolver_competencia_por_producto,
    resolver_condicion_pago,
)


class _CostoProviderFalso:
    def __init__(self, costos: dict):
        self._costos = costos

    def obtener(self, sku):
        return self._costos.get(sku)


class _IvaProviderFalso:
    def __init__(self, factores: dict):
        self._factores = factores

    def factor(self, sku):
        return self._factores.get(sku)


class _MLFalso:
    """`items_activos`/`detalle_items_ofertas` fakeados por cuenta -- mismo
    par de métodos que usa `descubrir_publicaciones`. `familias` opcional
    (mapa `user_product_id` -> lista de hermanas) para los tests del
    fallback por eliminación en `resolver_condicion_pago`."""
    def __init__(self, items_por_cuenta: dict, familias: dict | None = None):
        self._items = items_por_cuenta
        self._familias = familias or {}

    def items_activos(self, cuenta):
        return [i["id"] for i in self._items.get(cuenta, [])]

    def detalle_items_ofertas(self, item_ids, cuenta, progreso_cb=None):
        if progreso_cb:
            progreso_cb(0, len(item_ids), "catalogo")
        return [i for i in self._items.get(cuenta, []) if i["id"] in item_ids]

    def detalle_item_completo(self, item_id, cuenta):
        for items in self._items.values():
            for i in items:
                if i["id"] == item_id:
                    return i
        return {}

    def items_de_producto(self, product_id, cuenta):
        return self._familias.get(product_id, [])


# ── Ejemplo congelado, AYALA_CORE.md A.3.1 (PLANCHA-SUB-26X26-PORT,
# tomado de la planilla 2026-09-02) -- valida el motor al peso exacto.
# Usa las tasas de cuotas VIEJAS (8,4/12,3/15,7/19,2%) a propósito: son
# las que estaban en la planilla cuando se congeló el ejemplo, antes de
# la corrección del mismo día (ver Decisiones tomadas en el .md) -- por
# eso se pasan explícitas acá y no se lee `CUOTAS_PCT_DEFAULT` (que ya
# tiene las nuevas, 8,9/13,4/17,8/21,6%). ──
_COSTO = Decimal("56105.10")
_IVA_FACTOR = Decimal("1.105")
_ENVIO = Decimal("29410")


def test_congelado_contado():
    p = calcular_precio_condicion(
        costo_sin_iva=_COSTO, iva_factor=_IVA_FACTOR, envio_real=_ENVIO,
        financiero_pct=Decimal("0"), renta_pct=Decimal("32"),
    )
    assert p == Decimal("201258")


def test_congelado_reducida():
    p = calcular_precio_condicion(
        costo_sin_iva=_COSTO, iva_factor=_IVA_FACTOR, envio_real=_ENVIO,
        financiero_pct=Decimal("5"), renta_pct=Decimal("32"),
    )
    assert p == Decimal("230046")


def test_congelado_3_cuotas_tasa_vieja():
    p = calcular_precio_condicion(
        costo_sin_iva=_COSTO, iva_factor=_IVA_FACTOR, envio_real=_ENVIO,
        financiero_pct=Decimal("8.4"), renta_pct=Decimal("30"),
    )
    assert p == Decimal("239645")


def test_congelado_6_cuotas_tasa_vieja():
    p = calcular_precio_condicion(
        costo_sin_iva=_COSTO, iva_factor=_IVA_FACTOR, envio_real=_ENVIO,
        financiero_pct=Decimal("12.3"), renta_pct=Decimal("28"),
    )
    assert p == Decimal("254029")


def test_congelado_9_cuotas_tasa_vieja():
    p = calcular_precio_condicion(
        costo_sin_iva=_COSTO, iva_factor=_IVA_FACTOR, envio_real=_ENVIO,
        financiero_pct=Decimal("15.7"), renta_pct=Decimal("26"),
    )
    assert p == Decimal("265784")


def test_congelado_12_cuotas_tasa_vieja():
    p = calcular_precio_condicion(
        costo_sin_iva=_COSTO, iva_factor=_IVA_FACTOR, envio_real=_ENVIO,
        financiero_pct=Decimal("19.2"), renta_pct=Decimal("24"),
    )
    assert p == Decimal("279649")


def test_congelado_las_6_condiciones_juntas_con_tasas_vigentes():
    # Mismo ejemplo, pero llamando al motor completo con las tasas
    # ACTUALES de CUOTAS_PCT_DEFAULT (8,9/13,4/17,8/21,6%) -- no debe dar
    # lo mismo que el ejemplo congelado en las 4 columnas de cuotas
    # (la Reducida y el Contado sí, porque no dependen de esa tabla).
    precios = calcular_precios_todas_condiciones(
        costo_sin_iva=_COSTO, iva_factor=_IVA_FACTOR, envio_real=_ENVIO,
    )
    assert precios["contado"] == Decimal("201258")
    assert precios["reducida"] == Decimal("230046")
    assert precios["3"] != Decimal("239645")  # tasa vigente subió -> precio distinto
    assert set(precios) == {"contado", "reducida", "3", "6", "9", "12"}


def test_renta_baja_2_puntos_por_escalon_de_cuotas():
    # Motor!D31:G31 real: cada escalón resta 2 puntos sobre el anterior,
    # arrancando desde Reducida (no desde Contado directo -- Reducida
    # "hereda" la renta de Contado sin cambio).
    precios_altos = calcular_precios_todas_condiciones(
        costo_sin_iva=_COSTO, iva_factor=_IVA_FACTOR, envio_real=_ENVIO,
        renta_contado_pct=Decimal("40"), diferencial_cuotas_pct=Decimal("2"),
    )
    # A mayor renta objetivo, el precio de cada condición debe subir vs.
    # el default (32%) -- prueba de sanidad, no un valor congelado.
    default = calcular_precios_todas_condiciones(
        costo_sin_iva=_COSTO, iva_factor=_IVA_FACTOR, envio_real=_ENVIO,
    )
    for cond in ayala_core.CONDICIONES:
        assert precios_altos[str(cond)] > default[str(cond)]


def test_envio_full_suma_un_medio_pct_solo_si_se_pide():
    sin_full = calcular_precio_condicion(
        costo_sin_iva=_COSTO, iva_factor=_IVA_FACTOR, envio_real=_ENVIO,
        financiero_pct=Decimal("0"), renta_pct=Decimal("32"), envio_full=False,
    )
    con_full = calcular_precio_condicion(
        costo_sin_iva=_COSTO, iva_factor=_IVA_FACTOR, envio_real=_ENVIO,
        financiero_pct=Decimal("0"), renta_pct=Decimal("32"), envio_full=True,
    )
    assert con_full > sin_full


def test_financiero_pct_condicion_no_soportada_explota():
    import pytest
    with pytest.raises(ValueError):
        calcular_precio_condicion(
            costo_sin_iva=_COSTO, iva_factor=_IVA_FACTOR, envio_real=_ENVIO,
            financiero_pct=ayala_core._financiero_pct(18), renta_pct=Decimal("32"),
        )


# ── Detección de condición de pago, A.4 ──

def test_detectar_condicion_reducida_por_tag():
    assert detectar_condicion_pago({"tags": ["pcj-co-funded", "immediate_payment"]}) == "reducida"


def test_detectar_condicion_cuotas_sin_interes_por_tag():
    assert detectar_condicion_pago({"tags": ["3x_campaign", "immediate_payment"]}) == 3


def test_detectar_condicion_contado_default():
    assert detectar_condicion_pago({"tags": ["immediate_payment"]}) == "contado"
    assert detectar_condicion_pago({}) == "contado"


def test_reducida_tiene_prioridad_si_por_algun_motivo_conviven_los_dos_tags():
    # No debería pasar en la práctica (son mutuamente excluyentes en ML,
    # confirmado en vivo), pero si convivieran, Reducida gana -- es la
    # que ML mostró priorizada al alternar campañas en el mismo item.
    assert detectar_condicion_pago({"tags": ["pcj-co-funded", "3x_campaign"]}) == "reducida"


# ── resolver_condicion_pago -- fallback por eliminación, caso real
# 2026-09-04 (MLA3193414376, SKU PLANCHA-SUB-30X38-5EN1, cuenta IT): ML
# dejó de exponer cualquier tag de cuotas para esa publicación puntual
# (tags reales confirmados en vivo: solo "standard_price_by_channel" +
# genéricos, sin relación con cuotas -- ver ayala_core.py) mientras sus 5
# hermanas de la misma familia (user_product_id MLAU3909087028) seguían
# tagueadas sin ambigüedad. Precios/tags reales de las 6, confirmados en
# vivo vía /products/{id}/items ──

_FAMILIA_REAL_6_CUOTAS_HUERFANA = [
    {"item_id": "MLA3907570286", "price": 422711, "tags": ["good_quality_thumbnail", "immediate_payment", "cart_eligible"]},  # Contado real
    {"item_id": "MLA3907705288", "price": 640849, "tags": ["12x_campaign", "immediate_payment", "cart_eligible"]},
    {"item_id": "MLA3907703574", "price": 510951, "tags": ["3x_campaign", "immediate_payment", "cart_eligible"]},
    {"item_id": "MLA2058113293", "price": 483177, "tags": ["pcj-co-funded", "immediate_payment", "cart_eligible"]},
    {"item_id": "MLA3193414376", "price": 552758, "tags": ["standard_price_by_channel", "immediate_payment", "cart_eligible"]},  # huérfana -- 6 cuotas reales
    {"item_id": "MLA2058168063", "price": 599877, "tags": ["9x_campaign", "immediate_payment", "cart_eligible"]},
]


def test_resolver_condicion_pago_desambigua_huerfana_por_eliminacion():
    ml = _MLProductoFalso(_FAMILIA_REAL_6_CUOTAS_HUERFANA)
    huerfana = {"id": "MLA3193414376", "user_product_id": "MLAU3909087028",
                "tags": ["standard_price_by_channel", "immediate_payment", "cart_eligible"]}
    assert resolver_condicion_pago(ml, huerfana, "IT") == 6


def test_resolver_condicion_pago_no_toca_el_contado_real_de_la_misma_familia():
    # El "Contado" real de la MISMA familia debe seguir resolviendo
    # 'contado' -- es el de precio más bajo del balde compartido con la
    # huérfana, la eliminación no debe robarle su condición.
    ml = _MLProductoFalso(_FAMILIA_REAL_6_CUOTAS_HUERFANA)
    contado_real = {"id": "MLA3907570286", "user_product_id": "MLAU3909087028",
                     "tags": ["good_quality_thumbnail", "immediate_payment", "cart_eligible"]}
    assert resolver_condicion_pago(ml, contado_real, "IT") == "contado"


def test_resolver_condicion_pago_ignora_tag_propio_si_la_familia_no_da_ambiguedad():
    # Aunque el ítem SÍ tenga un tag propio que resuelve limpio, se sigue
    # cruzando contra la familia -- pero si esta no aporta ninguna
    # ambigüedad (familia completa, sin huecos ni duplicados), el tag
    # propio queda intacto.
    ml = _MLProductoFalso(_FAMILIA_REAL_6_CUOTAS_HUERFANA)
    con_tag = {"id": "MLA3907703574", "user_product_id": "MLAU3909087028", "tags": ["3x_campaign"]}
    assert resolver_condicion_pago(ml, con_tag, "IT") == 3


def test_resolver_condicion_pago_pasaje_de_cuotas_tag_duplicado_en_otra_condicion():
    # "Pasaje de cuotas" pedido por Maxx 2026-09-04: una hermana que es de
    # 6 cuotas reales quedó tagueada como "9x_campaign" (duplicando ese
    # balde) en vez de sin tag -- no hay ninguna hermana con 6x_campaign.
    # La de precio más bajo del par "9" debe reasignarse a 6 (6 cuesta
    # menos que 9 real).
    familia = [
        {"item_id": "MLA-CONTADO", "price": 422711, "tags": ["immediate_payment"]},
        {"item_id": "MLA-12", "price": 640849, "tags": ["12x_campaign"]},
        {"item_id": "MLA-3", "price": 510951, "tags": ["3x_campaign"]},
        {"item_id": "MLA-REDUCIDA", "price": 483177, "tags": ["pcj-co-funded"]},
        {"item_id": "MLA-6-MAL-TAGUEADA", "price": 552758, "tags": ["9x_campaign"]},  # es de 6, tag dice 9
        {"item_id": "MLA-9-REAL", "price": 599877, "tags": ["9x_campaign"]},
    ]
    ml = _MLProductoFalso(familia)
    huerfana = {"id": "MLA-6-MAL-TAGUEADA", "user_product_id": "MLAU_X", "tags": ["9x_campaign"]}
    assert resolver_condicion_pago(ml, huerfana, "IT") == 6

    real_9 = {"id": "MLA-9-REAL", "user_product_id": "MLAU_X", "tags": ["9x_campaign"]}
    assert resolver_condicion_pago(ml, real_9, "IT") == 9


def test_resolver_condicion_pago_sin_user_product_id_se_resigna_a_contado():
    ml = _MLProductoFalso([])
    sin_familia = {"id": "MLA1", "tags": []}
    assert resolver_condicion_pago(ml, sin_familia, "IT") == "contado"


def test_resolver_condicion_pago_no_arriesga_si_hay_mas_de_un_hueco():
    # Familia incompleta (5 en vez de 6) o con más de una condición sin
    # tag -- ambiguo, se queda con 'contado' en vez de adivinar.
    ml = _MLProductoFalso(_FAMILIA_REAL_6_CUOTAS_HUERFANA[:5])
    huerfana = {"id": "MLA3193414376", "user_product_id": "MLAU3909087028", "tags": []}
    assert resolver_condicion_pago(ml, huerfana, "IT") == "contado"


def test_descubrir_publicaciones_usa_resolver_condicion_pago(monkeypatch):
    # Integración: el mismo caso real, pero pasando por
    # descubrir_publicaciones de punta a punta (con cache_familias).
    _sin_envio(monkeypatch)
    ml = _MLFalso(
        {"IT": [{
            "id": "MLA3193414376", "title": "T", "price": 552758,
            "seller_custom_field": "PLANCHA-SUB-30X38-5EN1",
            "user_product_id": "MLAU3909087028",
            "tags": ["standard_price_by_channel", "immediate_payment", "cart_eligible"],
        }]},
        familias={"MLAU3909087028": _FAMILIA_REAL_6_CUOTAS_HUERFANA},
    )
    costo = _CostoProviderFalso({"PLANCHA-SUB-30X38-5EN1": Decimal(50)})
    iva = _IvaProviderFalso({"PLANCHA-SUB-30X38-5EN1": Decimal("1.21")})

    filas, _ = descubrir_publicaciones(ml, costo, iva, ["IT"], Decimal(1000))

    assert filas[0]["condicion_detectada"] == 6


# ── SKUs piloto ──

def test_skus_piloto_son_los_5_confirmados():
    assert ayala_core.SKUS_PILOTO == [
        "PLANCHA-SUB-26X26-PORT", "PLANCHA-SUB-30X38-10EN1", "PLANCHA-SUB-30X38-5EN1",
        "PLANCHA-SUB-GORRA", "PLANCHA-SUB-TERMO",
    ]


# ── Descubrir publicaciones -- pedido de Maxx 2026-09-02: "que detecte
# los SKU solos de las dos cuentas" ──

def _sin_envio(monkeypatch):
    monkeypatch.setattr(ayala_core, "costo_envio_real_item", lambda ml, item_id, cuenta: None)


def test_descubrir_publicaciones_filtra_por_sku_piloto(monkeypatch):
    _sin_envio(monkeypatch)
    ml = _MLFalso({"IT": [
        {"id": "MLA1", "title": "Plancha", "price": 100000, "seller_custom_field": "PLANCHA-SUB-GORRA", "tags": []},
        {"id": "MLA2", "title": "Combo", "price": 50000, "seller_custom_field": "PLANCHA-SUB-GORRA+OTRO-SKU", "tags": []},
        {"id": "MLA3", "title": "Otra cosa", "price": 20000, "seller_custom_field": "TONER-XYZ", "tags": []},
    ]})
    costo = _CostoProviderFalso({"PLANCHA-SUB-GORRA": Decimal(50)})
    iva = _IvaProviderFalso({"PLANCHA-SUB-GORRA": Decimal("1.21")})

    filas, incidencias = descubrir_publicaciones(ml, costo, iva, ["IT"], Decimal(1000))

    assert len(filas) == 1
    assert filas[0]["item_id"] == "MLA1"
    assert filas[0]["sku"] == "PLANCHA-SUB-GORRA"
    assert incidencias == []


def test_descubrir_publicaciones_marca_incidencia_sin_costo_tactica(monkeypatch):
    _sin_envio(monkeypatch)
    ml = _MLFalso({"IT": [
        {"id": "MLA1", "title": "Plancha", "price": 100000, "seller_custom_field": "PLANCHA-SUB-TERMO", "tags": []},
    ]})
    filas, incidencias = descubrir_publicaciones(ml, _CostoProviderFalso({}), _IvaProviderFalso({"PLANCHA-SUB-TERMO": Decimal("1.21")}), ["IT"], Decimal(1000))
    assert filas == []
    assert incidencias == [{"item_id": "MLA1", "cuenta": "IT", "sku": "PLANCHA-SUB-TERMO", "motivo": "SIN_COSTO_TACTICA"}]


def test_descubrir_publicaciones_recorre_las_dos_cuentas(monkeypatch):
    _sin_envio(monkeypatch)
    ml = _MLFalso({
        "IT": [{"id": "MLA1", "title": "T", "price": 100000, "seller_custom_field": "PLANCHA-SUB-TERMO", "tags": []}],
        "MT": [{"id": "MLA2", "title": "T", "price": 110000, "seller_custom_field": "PLANCHA-SUB-TERMO", "tags": []}],
    })
    costo = _CostoProviderFalso({"PLANCHA-SUB-TERMO": Decimal(50)})
    iva = _IvaProviderFalso({"PLANCHA-SUB-TERMO": Decimal("1.21")})

    filas, _ = descubrir_publicaciones(ml, costo, iva, ["IT", "MT"], Decimal(1000))

    assert {f["cuenta"] for f in filas} == {"IT", "MT"}
    assert {f["item_id"] for f in filas} == {"MLA1", "MLA2"}


def test_descubrir_publicaciones_detecta_condicion_y_calcula_diferencia(monkeypatch):
    _sin_envio(monkeypatch)
    ml = _MLFalso({"IT": [
        {"id": "MLA1", "title": "T", "price": 100000, "seller_custom_field": "PLANCHA-SUB-TERMO",
         "tags": ["cuota-simple-6"]},
    ]})
    costo = _CostoProviderFalso({"PLANCHA-SUB-TERMO": Decimal(50)})
    iva = _IvaProviderFalso({"PLANCHA-SUB-TERMO": Decimal("1.21")})

    filas, _ = descubrir_publicaciones(ml, costo, iva, ["IT"], Decimal(1000))

    assert filas[0]["condicion_detectada"] == 6
    esperado = calcular_precios_todas_condiciones(costo_sin_iva=Decimal(50000), iva_factor=Decimal("1.21"), envio_real=Decimal(0))["6"]
    assert filas[0]["precio_calculado"] == esperado
    assert filas[0]["diferencia"] == Decimal(100000) - esperado


def test_descubrir_publicaciones_usa_envio_real_solo_si_es_gratis(monkeypatch):
    # Bug real 2026-09-03, encontrado corriendo el job en vivo (Maxx):
    # "Error: 'list_cost'" -- `costo_envio_real_item` devuelve la clave
    # `costo_envio_real` (ya resuelta a 0 si no es "free"), nunca
    # `list_cost`. Este fake usa la forma REAL a propósito, para que este
    # test hubiera fallado si el código seguía leyendo `list_cost`.
    monkeypatch.setattr(ayala_core, "costo_envio_real_item",
                         lambda ml, item_id, cuenta: {"cost_type": "free", "costo_envio_real": 12000.0})
    ml = _MLFalso({"IT": [
        {"id": "MLA1", "title": "T", "price": 100000, "seller_custom_field": "PLANCHA-SUB-TERMO", "tags": []},
    ]})
    costo = _CostoProviderFalso({"PLANCHA-SUB-TERMO": Decimal(50)})
    iva = _IvaProviderFalso({"PLANCHA-SUB-TERMO": Decimal("1.21")})

    filas, _ = descubrir_publicaciones(ml, costo, iva, ["IT"], Decimal(1000))

    assert filas[0]["envio_real"] == Decimal("12000.0")


def test_descubrir_publicaciones_costo_envio_real_cero_si_no_es_gratis(monkeypatch):
    monkeypatch.setattr(ayala_core, "costo_envio_real_item",
                         lambda ml, item_id, cuenta: {"cost_type": "charged", "costo_envio_real": 0.0})
    ml = _MLFalso({"IT": [
        {"id": "MLA1", "title": "T", "price": 100000, "seller_custom_field": "PLANCHA-SUB-TERMO", "tags": []},
    ]})
    costo = _CostoProviderFalso({"PLANCHA-SUB-TERMO": Decimal(50)})
    iva = _IvaProviderFalso({"PLANCHA-SUB-TERMO": Decimal("1.21")})

    filas, _ = descubrir_publicaciones(ml, costo, iva, ["IT"], Decimal(1000))

    assert filas[0]["envio_real"] == Decimal("0.0")


def test_descubrir_publicaciones_filtra_por_skus_seleccionados(monkeypatch):
    # Pedido 2026-09-03: "que selecciono 1 o varios SKU" -- no siempre
    # los 5 piloto, un subconjunto elegido a mano.
    _sin_envio(monkeypatch)
    ml = _MLFalso({"IT": [
        {"id": "MLA1", "title": "T", "price": 100000, "seller_custom_field": "PLANCHA-SUB-TERMO", "tags": []},
        {"id": "MLA2", "title": "T", "price": 100000, "seller_custom_field": "PLANCHA-SUB-GORRA", "tags": []},
    ]})
    costo = _CostoProviderFalso({"PLANCHA-SUB-TERMO": Decimal(50), "PLANCHA-SUB-GORRA": Decimal(50)})
    iva = _IvaProviderFalso({"PLANCHA-SUB-TERMO": Decimal("1.21"), "PLANCHA-SUB-GORRA": Decimal("1.21")})

    filas, _ = descubrir_publicaciones(ml, costo, iva, ["IT"], Decimal(1000), skus_filtro=["PLANCHA-SUB-TERMO"])

    assert [f["sku"] for f in filas] == ["PLANCHA-SUB-TERMO"]


def test_descubrir_publicaciones_incluye_costo_e_iva_para_recalculo_en_frontend():
    ml = _MLFalso({"IT": [
        {"id": "MLA1", "title": "T", "price": 100000, "seller_custom_field": "PLANCHA-SUB-TERMO", "tags": []},
    ]})
    costo = _CostoProviderFalso({"PLANCHA-SUB-TERMO": Decimal(50)})
    iva = _IvaProviderFalso({"PLANCHA-SUB-TERMO": Decimal("1.21")})

    filas, _ = descubrir_publicaciones(ml, costo, iva, ["IT"], Decimal(1000))

    assert filas[0]["costo_sin_iva_ars"] == Decimal(50000)
    assert filas[0]["iva_factor"] == Decimal("1.21")


# ── Competencia por producto -- pedido 2026-09-03, corregido el mismo día
# (GET /items/{id} está gateado por ownership para publicaciones ajenas,
# ver docstring de resolver_competencia_por_producto) ──

class _MLProductoFalso:
    def __init__(self, ofertas: list[dict]):
        self._ofertas = ofertas

    def items_de_producto(self, product_id, cuenta):
        return self._ofertas


def test_resolver_competencia_por_producto_excluye_cuentas_propias():
    ml = _MLProductoFalso([
        {"item_id": "MLA1", "seller_id": 115764017, "price": 77719, "tags": ["pcj-co-funded"]},  # IT, propio
        {"item_id": "MLA2", "seller_id": 1001057832, "price": 78745, "tags": ["immediate_payment"]},
        {"item_id": "MLA3", "seller_id": 1001057832, "price": 89990, "original_price": None, "tags": ["3x_campaign"]},
    ])
    r = resolver_competencia_por_producto(ml, "MLA68609606", "IT")
    assert [x["item_id"] for x in r] == ["MLA2", "MLA3"]
    assert r[0]["condicion_detectada"] == "contado"
    assert r[1]["condicion_detectada"] == 3


def test_resolver_competencia_por_producto_sin_competidores():
    ml = _MLProductoFalso([{"item_id": "MLA1", "seller_id": 115764017, "price": 77719, "tags": []}])
    assert resolver_competencia_por_producto(ml, "MLA68609606", "IT") == []
