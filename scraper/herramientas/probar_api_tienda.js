// Prueba (SOLO LECTURA) de si se puede leer el listado de una tienda de la competencia por la API de ML, vía /ml-proxy del backend.
// Pegar en la consola (F12) del ERP ya abierto y con clave. Cambiá TIENDA / SELLER_ID abajo si querés otra tienda.
(async () => {
  const TIENDA = 'TECNOVIBEARG';   // nickname del vendedor en ML (el de la columna "entidad": tecnovibe -> TECNOVIBEARG)
  const SELLER_ID = '';            // opcional: si ya lo sabés, evita el paso de resolverlo
  const bu = getBackendUrl();
  const R = [];                    // resultados de cada prueba
  const log = (...a) => console.log('%c[API tienda]', 'color:#09f', ...a);
  if (!bu) { log('❌ No hay backend configurado en Configuración.'); return; }

  let tok = '';
  try { const t = await (await fetch(`${bu}/ml/token?account=IT`)).json(); tok = t.token || ''; } catch (e) {}
  log(tok ? 'Token IT obtenido del backend.' : '⚠ Sin token explícito: el proxy usará el del servidor.');

  // El proxy responde HTTP 200 aunque ML falle: el error viene dentro del cuerpo (status / error / message).
  async function pedir(nombre, path) {
    const t0 = performance.now();
    let http = null, body = null, err = '';
    try {
      const r = await fetch(`${bu}/ml-proxy?path=${encodeURIComponent(path)}`, { headers: tok ? { 'x-vk-token': tok } : {} });
      http = r.status;
      body = await r.json().catch(() => null);
    } catch (e) { err = 'red: ' + e.message; }
    const st = body && typeof body === 'object' && !Array.isArray(body) ? (body.status || (body.error ? 'error' : null)) : null;
    const falla = err || http !== 200 || (typeof st === 'number' && st >= 400) || st === 'error';
    const msg = err || (falla ? `${st || http}: ${(body && (body.message || body.error)) || ''}`.slice(0, 120) : '');
    const res = { prueba: nombre, ok: !falla, resultado: falla ? '❌ ' + msg : '✅ OK', ms: Math.round(performance.now() - t0), body };
    R.push(res);
    return res;
  }

  // 0) ¿el token y el proxy andan? (users/me)
  const me = await pedir('0 token (users/me)', 'users/me');
  if (me.ok) log('Token válido, cuenta:', me.body.nickname || me.body.id);

  // 1) resolver el seller_id del nickname
  let sid = SELLER_ID;
  const bus = await pedir('1 búsqueda por nickname', `sites/MLA/search?nickname=${encodeURIComponent(TIENDA)}&limit=50`);
  if (bus.ok) {
    const res = bus.body.results || [];
    sid = sid || String((res[0] && res[0].seller && res[0].seller.id) || '');
    bus.resultado = `✅ OK · total ${bus.body.paging && bus.body.paging.total} · devolvió ${res.length}`;
  }
  if (!sid) {
    const u = await pedir('1b users/search por nickname', `users/search?nickname=${encodeURIComponent(TIENDA)}`);
    if (u.ok) {   // la forma de la respuesta varía: buscar el primer "id" numérico del cuerpo
      const hallar = o => { if (!o || typeof o !== 'object') return ''; if (typeof o.id === 'number' || /^\d{5,}$/.test(o.id || '')) return String(o.id); for (const v of Object.values(o)) { const r = hallar(v); if (r) return r; } return ''; };
      sid = hallar(u.body);
      log('users/search devolvió:', JSON.stringify(u.body).slice(0, 300));
    }
  }
  log('seller_id:', sid || '(no se pudo resolver)');

  // 2) listado por seller_id: páginas y límite de 1000
  let total = null, muestra = [], campos = [];
  if (sid) {
    for (const off of [0, 50, 950, 1000]) {
      const p = await pedir(`2 search seller_id offset=${off}`, `sites/MLA/search?seller_id=${sid}&limit=50&offset=${off}`);
      if (p.ok) {
        const res = p.body.results || [];
        if (off === 0) {
          total = p.body.paging && p.body.paging.total;
          muestra = res.slice(0, 3).map(x => ({ id: x.id, titulo: (x.title || '').slice(0, 50), precio: x.price, original: x.original_price, cuotas: x.installments && x.installments.quantity }));
          campos = res[0] ? Object.keys(res[0]) : [];
        }
        p.resultado = `✅ OK · total ${p.body.paging && p.body.paging.total} · devolvió ${res.length}`;
      }
    }
    // 3) listado propio del vendedor (suele pedir ser el dueño) y modo scan (sin tope de 1000)
    await pedir('3 users/{id}/items/search', `users/${sid}/items/search?limit=50`);
    await pedir('4 items/search scan', `users/${sid}/items/search?search_type=scan&limit=100`);
    await pedir('5 users/{id} (perfil público)', `users/${sid}`);
  }

  console.table(R.map(({ prueba, resultado, ms }) => ({ prueba, resultado, ms })));
  const listado = R.find(r => r.prueba.startsWith('2 search seller_id offset=0'));
  const sinListado = !listado;   // si nunca se probó el listado por seller_id, NO se puede decir que está bloqueado
  const hay403 = R.some(r => /403|forbidden|PolicyAgent/i.test(r.resultado + JSON.stringify(r.ok ? '' : r.body)));
  let veredicto;
  if (listado && listado.ok) {
    veredicto = `✅ LA API DEVUELVE EL LISTADO: ${total} publicaciones declaradas de ${TIENDA}. Muestra:`;
    console.table(muestra);
    log('Campos por publicación:', campos.join(', '));
    const tope = R.find(r => r.prueba.endsWith('offset=1000'));
    log(tope && tope.ok ? 'offset 1000 también responde.' : 'offset ≥1000 NO responde: para tiendas de >1000 publicaciones hay que usar scan o varios órdenes.');
    log('Comparalo con lo que declara ML en la tienda (p. ej. 663 en Elephant) y con lo que lee Selenium.');
  } else if (sinListado) {
    veredicto = '⚠ INCONCLUSO: no se pudo resolver el seller_id, el listado nunca se probó. Poné SELLER_ID arriba y repetí.';
  } else if (hay403) {
    veredicto = '❌ BLOQUEADA (403): la API no deja listar publicaciones ajenas con tu token. Quedate con Selenium.';
  } else {
    veredicto = '❌ NO FUNCIONA: ' + ((listado && listado.resultado) || 'no se pudo resolver el vendedor') + '. Mirá la tabla de arriba / window.__apiTienda.';
  }
  log(veredicto);
  window.__apiTienda = { tienda: TIENDA, seller_id: sid, total, veredicto, pruebas: R };
  log('Detalle crudo en window.__apiTienda (copialo con copy(JSON.stringify(window.__apiTienda)) si querés pasármelo).');
})();
