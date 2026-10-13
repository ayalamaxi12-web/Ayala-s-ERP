// C0 — Campañas ML. Pegar en la consola de la página del ERP (con la sesión/clave ya cargada).
// Elegís el Excel descargado de ML, el backend le agrega una hoja "ERP Prueba" y se descarga el resultado.
(async()=>{
  const inp=document.createElement('input');inp.type='file';inp.accept='.xlsx';
  inp.onchange=async()=>{
    const f=inp.files[0];if(!f)return;
    const fd=new FormData();fd.append('archivo',f);
    const u=getBackendUrl().replace(/\/$/,'');
    const r=await fetch(u+'/campanas-ml/probar-hoja',{method:'POST',body:fd});
    if(!r.ok){console.error('Error',r.status,await r.text());return;}
    console.log('Integridad:',r.headers.get('X-Integridad'));
    const b=await r.blob();const a=document.createElement('a');
    a.href=URL.createObjectURL(b);a.download=f.name.replace(/\.xlsx$/i,'')+'_con_hoja_prueba.xlsx';a.click();
  };
  inp.click();
})();
