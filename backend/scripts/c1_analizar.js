// C1 — Campañas ML. Pegar en la consola del ERP. Elegís el Excel de la campaña y devuelve el cruce
// con PM + costo y el margen por cuota. Opcional: margenObjetivo (%) para ver el máx. % entero que lo cumple.
(async(margenObjetivo)=>{
  const inp=document.createElement('input');inp.type='file';inp.accept='.xlsx';
  inp.onchange=async()=>{
    const f=inp.files[0];if(!f)return;
    const fd=new FormData();fd.append('archivo',f);
    const q=margenObjetivo?('?margen_objetivo='+margenObjetivo):'';
    const r=await fetch(getBackendUrl().replace(/\/$/,'')+'/campanas-ml/analizar'+q,{method:'POST',body:fd});
    if(!r.ok){console.error('Error',r.status,await r.text());return;}
    const j=await r.json();window.CAMP=j;
    console.log(j.campana,'| TC',j.tc,'|',j.resumen,'| avisos',j.avisos);
    // Para contrastar: CAMP.filas.filter(x=>['SKU1','SKU2'].includes(x.sku)) o por item_id
    console.table(j.filas.filter(x=>x.margenes.contado).slice(0,20).map(x=>({item:x.item_id,sku:x.sku,pm:x.pm,pm_$:x.precio_pm,cliente:x.precio_cliente,vend:x.precio_vendedor,
      contado:x.margenes.contado.margen,c3:x.margenes['3'].margen,c6:x.margenes['6'].margen,c9:x.margenes['9'].margen,c12:x.margenes['12'].margen,avisos:x.avisos.length})));
  };
  inp.click();
})(/*margenObjetivo*/ null);
