// ¿La API de ML da el CALENDARIO de campañas (futuras, con fechas) y en cuáles soy elegible? — SOLO LECTURA (todos GET).
// Pegar en la consola del ERP (con la clave del backend cargada). Usa tu token por /ml-proxy; no escribe nada en ML.
(async()=>{
  const bu=getBackendUrl().replace(/\/$/,''), AHORA=new Date(), R={cuentas:{}}, SIN=s=>JSON.stringify(s)||'';
  // /ml-proxy devuelve el cuerpo de ML SIN el código HTTP: un 403 llega como {"status":403,"error":"forbidden",...}
  const clasif=d=>{
    if(d&&d.proxyError)return {k:'ERROR',txt:d.proxyError};
    const st=d&&(d.status||d.code), msg=String((d&&(d.error||d.message))||'');
    if(st===403||/forbidden|not allowed|access.denied|scope/i.test(msg))return {k:'403',txt:msg||'forbidden'};
    if(st===401||/invalid.?token|unauthorized|expired/i.test(msg))return {k:'401',txt:msg||'token inválido'};
    if(st===404||/not.?found/i.test(msg))return {k:'404',txt:msg||'no existe'};
    if(typeof st==='number'&&st>=400)return {k:String(st),txt:msg};
    return {k:'OK',txt:''};
  };
  const ml=async(path,token)=>{
    try{const r=await fetch(`${bu}/ml-proxy?path=${encodeURIComponent(path)}`,{headers:{'x-vk-token':token}});
      const t=await r.text();let d;try{d=JSON.parse(t);}catch(e){d={proxyError:`HTTP ${r.status} no JSON: ${t.slice(0,120)}`};}
      if(r.status===401&&!d.proxyError)d={proxyError:'401 del ERP: falta/ es inválida la clave del backend (Configuración)'};
      return d;}catch(e){return {proxyError:String(e)};}
  };
  const fecha=s=>s?String(s).slice(0,10):'—', dias=s=>s?Math.round((new Date(s)-AHORA)/864e5):null;
  const lista=d=>Array.isArray(d)?d:(d&&(d.results||d.promotions||d.data))||[];
  for(const cuenta of ['IT','MT']){
    const C=R.cuentas[cuenta]={pruebas:[],promos:[]};
    let tk;try{tk=await (await fetch(`${bu}/ml/token?account=${cuenta}`)).json();}catch(e){tk={};}
    if(!tk.token){C.pruebas.push({endpoint:'/ml/token',resultado:'ERROR',detalle:'no pude obtener el token de '+cuenta});continue;}
    const uid=tk.seller_id, T=tk.token;
    const prueba=async(nombre,path)=>{const d=await ml(path,T),c=clasif(d),l=lista(d);
      C.pruebas.push({endpoint:nombre,resultado:c.k,detalle:c.txt||(l.length+' elemento(s)'+(d&&d.paging&&d.paging.total!=null?' · total '+d.paging.total:''))});return {d,c,l};};
    // 1) El listado de campañas del vendedor (el candidato a "calendario")
    const A=await prueba('GET seller-promotions/users/{id}',`seller-promotions/users/${uid}?app_version=v2`);
    C.muestra=(A.l[0]||A.d);          // forma real de una campaña, para ver qué campos trae
    // 2) ¿el filtro por estado deja pedir solo las que vienen (pending)?
    const B=await prueba('GET …/users/{id}?status=pending',`seller-promotions/users/${uid}?app_version=v2&status=pending`);
    C.promos=A.l.map(p=>({id:p.id,tipo:p.type,estado:p.status,nombre:p.name,inicio:p.start_date,fin:p.finish_date,limite_adhesion:p.deadline_date,
      empieza_en_dias:dias(p.start_date),futura:!!p.start_date&&new Date(p.start_date)>AHORA}));
    // 3) Elegibilidad: ítems candidatos / ya aceptados de cada campaña (las próximas y las vigentes, hasta 8)
    const interesantes=C.promos.filter(p=>p.estado!=='finished').slice(0,8);
    for(const p of interesantes){
      const base=`seller-promotions/promotions/${p.id}/items?promotion_type=${encodeURIComponent(p.tipo)}&app_version=v2&limit=1`;
      const cand=await ml(base+'&status=candidate',T),ok=await ml(base+'&status=started',T);
      const cc=clasif(cand),co=clasif(ok);
      p.items_elegibles=cc.k==='OK'?(cand.paging&&cand.paging.total!=null?cand.paging.total:lista(cand).length):'('+cc.k+')';
      p.items_aceptados=co.k==='OK'?(ok.paging&&ok.paging.total!=null?ok.paging.total:lista(ok).length):'('+co.k+')';
    }
    if(interesantes.length)C.pruebas.push({endpoint:'GET …/promotions/{id}/items?status=candidate|started',resultado:interesantes.every(p=>typeof p.items_elegibles==='number')?'OK':'ver tabla',detalle:interesantes.length+' campañas consultadas'});
    // 4) Por publicación: ¿qué campañas (candidatas, activas, próximas) tiene UN ítem?
    const it=await ml(`users/${uid}/items/search?status=active&limit=1`,T), mla=(it.results||[])[0];
    if(mla){const P=await prueba('GET seller-promotions/items/{MLA}',`seller-promotions/items/${mla}?app_version=v2`);
      C.item_muestra={mla,promociones:P.l.slice(0,5).map(p=>({id:p.id,tipo:p.type,estado:p.status,inicio:p.start_date,fin:p.finish_date}))};}
  }
  // ── Informe
  console.log('%cCALENDARIO DE CAMPAÑAS DE ML — resultado de la prueba','font-weight:bold;font-size:14px');
  const todas=[];
  for(const [c,C] of Object.entries(R.cuentas)){
    console.log('%c── Cuenta '+c,'font-weight:bold');console.table(C.pruebas);
    if(C.promos.length){console.table(C.promos.map(p=>({...p,inicio:fecha(p.inicio),fin:fecha(p.fin),limite_adhesion:fecha(p.limite_adhesion)})));}
    todas.push(...C.promos.map(p=>({...p,cuenta:c})));
  }
  const pruebas=Object.values(R.cuentas).flatMap(C=>C.pruebas);
  const hay403=pruebas.some(x=>x.resultado==='403'), hay401=pruebas.some(x=>x.resultado==='401');
  const conFechas=todas.filter(p=>p.inicio&&p.fin), futuras=todas.filter(p=>p.futura), vigentes=todas.filter(p=>p.estado==='started'), pend=todas.filter(p=>p.estado==='pending'||p.estado==='candidate');
  const elegibles=todas.filter(p=>typeof p.items_elegibles==='number'&&p.items_elegibles>0);
  const V=[];
  V.push(`1) ¿Lista de campañas disponibles/futuras CON fechas? → ${futuras.length?'SÍ: '+futuras.length+' futura(s) con fecha de inicio/fin ('+conFechas.length+' campañas traen fechas).':conFechas.length?'NO para futuras: trae '+conFechas.length+' campaña(s) con fechas pero ninguna empieza más adelante.':todas.length?'trae campañas pero SIN fechas.':'no devolvió campañas.'}`);
  V.push(`2) ¿Solo activas / ya aceptadas? → ${todas.length?(vigentes.length===todas.length?'SÍ: todas están en estado started (solo las vigentes/aceptadas).':`NO solo esas: ${vigentes.length} vigentes, ${pend.length} pendientes/candidatas, ${todas.length-vigentes.length-pend.length} otras (finalizadas, etc.).`):'sin datos'}`);
  V.push(`3) ¿403 / bloqueado? → ${hay403?'SÍ: algún endpoint devolvió 403 (ver tabla).':hay401?'401: el token no sirve o falta la clave del backend (no es un bloqueo de ML).':'No: ningún endpoint dio 403.'}`);
  V.push(`Elegibilidad (ítems candidatos por campaña) → ${elegibles.length?'SÍ: '+elegibles.length+' campaña(s) con ítems elegibles (columna items_elegibles).':todas.some(p=>p.items_elegibles!==undefined)?'consultado, ningún ítem elegible o dio error (ver columna).':'no consultado.'}`);
  V.push(`Decisión → ${futuras.length?'AUTOMÁTICO viable: el aviso puede leer el calendario de ML solo.':conFechas.length||todas.length?'PARCIAL: ML da lo vigente/aceptado pero no el calendario futuro → cargar las fechas futuras a mano.':'MANUAL: ML no dio campañas → cargar las fechas en una planilla.'}`);
  console.log('%c'+V.join('\n'),'font-size:12px;line-height:1.6');
  R.veredicto=V;window.PROMOS_TEST=R;
  console.log('Todo el detalle quedó en window.PROMOS_TEST. Para pasarme el resultado: copy(JSON.stringify(window.PROMOS_TEST,null,1))');
})();
