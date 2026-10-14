// Verificación (solo lectura) de los dos Sheets para "contexto del SKU" en Análisis de Competencia. Pegar en la consola del ERP.
// Muestra los encabezados reales de las columnas que vamos a leer y unas filas de muestra, y si el Sheet se puede leer con la API key.
(async()=>{
  const L=i=>{let s='';i++;while(i){const m=(i-1)%26;s=String.fromCharCode(65+m)+s;i=Math.floor((i-1)/26);}return s;};
  const IDX=c=>c.split('').reduce((a,ch)=>a*26+ch.charCodeAt(0)-64,0)-1;
  const leer=async(id,tabs,rango)=>{for(const t of tabs){try{return {tab:t,filas:await fetchSheet(id,`${t}!${rango}`)};}catch(e){var err=e.message;}}return {error:err};};
  const mostrar=(titulo,r,cols,sku)=>{
    console.log('%c'+titulo,'font-weight:bold;font-size:13px');
    if(r.error){console.log('❌ No se pudo leer con la API key:',r.error,'(si es 403/404, el Sheet no es legible con la key: se leería desde el backend con la cuenta de servicio)');return;}
    const f=r.filas;let h=0;while(h<8&&!f[h].some(c=>/^sku$/i.test(String(c).trim())))h++;if(h>=8)h=0;
    console.log('Pestaña leída:',r.tab,'· filas:',f.length,'· fila de encabezados detectada: n.º',h+1);
    console.table(cols.map(c=>({columna:c,encabezado:f[h][IDX(c)]??'(vacía)',muestra_1:(f[h+1]||[])[IDX(c)],muestra_2:(f[h+2]||[])[IDX(c)],muestra_3:(f[h+3]||[])[IDX(c)]})));
    if(sku){const k=String(sku).toUpperCase().replace(/\s+/g,''),hit=f.slice(h+1).filter(r=>String(r[0]||'').toUpperCase().replace(/\s+/g,'')===k||String(r[1]||'').toUpperCase().replace(/\s+/g,'')===k);
      console.log(`Filas de ${sku} (por columna A o B):`,hit.length);hit.slice(0,3).forEach(r=>console.log(cols.map(c=>c+'='+(r[IDX(c)]??'')).join(' · ')));}
    // ¿cuántos SKU hay y se repiten?
    const skus=f.slice(h+1).map(r=>String(r[0]||'').trim().toUpperCase()).filter(Boolean),dup=skus.length-new Set(skus).size;
    console.log('SKUs en la columna A:',skus.length,'· repetidos:',dup);
  };
  const SKU=prompt('Un SKU para probar el cruce (ej. SEW-MINI):','SEW-MINI');
  const st=await leer('1xtD_C07rN9Oesn277mD8x-ERPgsZxup3WqF_c_qXJp8',['Global','GLOBAL'],'A1:H6000');
  mostrar('STOCK — Sheet 1xtD… · pestaña Global (A=SKU, E/F/G = Táctica / Ecom / total)',st,['A','B','C','D','E','F','G'],SKU);
  const ve=await leer('1Wzs3SmmIGcGd_NJGfe5qJRBYkJBbyKjrl4rF7reojIE',['conjunto','CONJUNTO'],'A1:BZ3000');
  mostrar('VENTAS — Sheet 1Wzs… · pestaña conjunto (AY/AZ/BA/BB = 7/30/90/180 días)',ve,['A','B','C','D','E','AX','AY','AZ','BA','BB','BC'],SKU);
})();
