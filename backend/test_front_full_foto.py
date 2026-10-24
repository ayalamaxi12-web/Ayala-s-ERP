"""Full ML con foto guardada (frontend): estructura y la corrección del botón trabado en «corriendo…»."""
from test_front_analisis import INDEX


def html():
    return open(INDEX, encoding='utf-8').read()


def test_pollfulljob_no_queda_trabado_si_el_job_se_perdio_o_el_servidor_no_responde():
    s = html()
    f = s[s.index('function pollFullJob('):s.index('function runFullConciliar')]
    assert "data.status==='not_found'" in f and 'fallas>=5' in f or '++fallas>=5' in f
    assert 'btn.disabled=false' in f and 'if(onFail)onFail(msg)' in f and '45*60*1000' in f


def test_al_abrir_full_ml_se_carga_la_foto_sin_leer_ml_y_hay_pie_con_actualizar():
    s = html()
    assert "if(page==='full-ml')fullFotoCargar();" in s
    for id_ in ('full-conciliar-pie', 'full-reposicion-pie'):
        assert f'id="{id_}"' in s
    f = s[s.index('async function fullFotoCargar'):s.index('async function fullAlertaVista')]
    assert '/ml-full/foto/' in f and 'Última actualización:' in f and 'Falló la última actualización, mostrando datos de' in f
    assert 'Datos incompletos para' in f and 'Marcar vista' in f and 'Reintentar' in f
    assert 'method:\'POST\'' in s[s.index('async function fullActualizar'):][:1400]


def test_los_ids_y_nombres_de_siempre_siguen_y_el_boton_se_llama_actualizar():
    s = html()
    for nombre in ('runFullConciliar', 'runFullReposicion', 'renderFullConciliar', 'renderFullReposicion', 'exportFullReposicionParaML'):
        assert f'function {nombre}' in s, nombre
    assert "'Actualizando...':'Actualizar'" in s and 'Ejecutar conciliación' not in s and 'Simular reposición</button>' not in s
