                        let metodoActual = "VPN";
                        let modoA = "uniforme";
                        let modoB = "uniforme";
                        let ultimosResultados = null;
                        let ultimosDatos = null;

                        // ── SELECCIÓN DE MÉTODO ──────────────────────────────────────────────────────
                        function seleccionarMetodo(metodo, card) {
                          metodoActual = metodo;
                          document
                            .querySelectorAll(".metodo-card")
                            .forEach((c) => c.classList.remove("activo"));
                          card.classList.add("activo");
                          // Ajustar label TIR
                          const tirLabel = metodo === "TIR";
                          document.querySelectorAll('[id^="tasa_"]').forEach((el) => {
                            el.closest(".campo-grupo").querySelector("label").textContent =
                              tirLabel ? "TREMA (%)" : "Tasa de Descuento / TREMA (%)";
                          });
                         // Ocultar resultados
                          document.getElementById("resultados").style.display = "none";
                        }

                        // ── MODO FLUJOS ──────────────────────────────────────────────────────────────
                        function setModo(alt, modo, btn) {
                          const sfx = alt;
                          btn
                            .closest(".modo-selector")
                            .querySelectorAll(".modo-btn")
                            .forEach((b) => b.classList.remove("activo"));
                          btn.classList.add("activo");

                          if (alt === "a") modoA = modo;
                          else modoB = modo;

                          document.getElementById(`uniforme_${sfx}`).style.display =
                            modo === "uniforme" ? "block" : "none";
                          document.getElementById(`manual_${sfx}`).style.display =
                            modo === "manual" ? "block" : "none";

                          if (modo === "manual") {
                            const vida =
                              parseInt(document.getElementById(`vida_${sfx}`).value) || 5;
                            generarCamposFlujos(sfx, vida);
                          }
                        }

                        // Generar campos de flujos manuales cuando cambia la vida
                        document.getElementById("vida_a").addEventListener("change", () => {
                          if (modoA === "manual")
                            generarCamposFlujos(
                              "a",
                              parseInt(document.getElementById("vida_a").value) || 5,
                            );
                        });
                        document.getElementById("vida_b").addEventListener("change", () => {
                          if (modoB === "manual")
                            generarCamposFlujos(
                              "b",
                              parseInt(document.getElementById("vida_b").value) || 5,
                            );
                        });

                        function generarCamposFlujos(alt, n) {
                          const container = document.getElementById(`flujos_${alt}`);
                          container.innerHTML = "";
                          for (let t = 1; t <= n; t++) {
                            const row = document.createElement("div");
                            row.className = "flujo-row";
                            row.innerHTML = `
                        <label>Año ${t}</label>
                        <input type="number" class="flujo-input-${alt}" placeholder="Flujo neto ($)" step="0.01">
                      `;
                            container.appendChild(row);
                          }
                        }

                        // ── CÁLCULO ──────────────────────────────────────────────────────────────────
                        function obtenerNumero(id, obligatorio = false, nombreCampo = "") {
                          const input = document.getElementById(id);
                          const valorTexto = input.value.trim();

                          if (obligatorio && valorTexto === "") {
                            throw new Error(`El campo "${nombreCampo}" es obligatorio.`);
                          }

                          if (valorTexto === "") return 0;

                          const numero = parseFloat(valorTexto);

                          if (isNaN(numero)) {
                            throw new Error(`El campo "${nombreCampo}" debe ser numérico.`);
                          }

                          return numero;
                        }

                        function recopilarDatosAlt(sfx) {
                          const modo = sfx === "a" ? modoA : modoB;
                          const letra = sfx.toUpperCase();

                          const inversion = obtenerNumero(
                            `inv_${sfx}`,
                            true,
                            `Inversión inicial de la Alternativa ${letra}`,
                          );
                          const tasa = obtenerNumero(
                            `tasa_${sfx}`,
                            true,
                            `Tasa/TREMA de la Alternativa ${letra}`,
                          );
                          const vida = parseInt(
                            obtenerNumero(
                              `vida_${sfx}`,
                              true,
                              `Vida del proyecto de la Alternativa ${letra}`,
                            ),
                          );

                          if (inversion < 0) {
                            throw new Error(
                              `La inversión inicial de la Alternativa ${letra} no puede ser negativa.`,
                            );
                          }

                          if (tasa < 0) {
                            throw new Error(
                              `La tasa/TREMA de la Alternativa ${letra} no puede ser negativa.`,
                            );
                          }

                          if (vida <= 0) {
                            throw new Error(
                              `La vida del proyecto de la Alternativa ${letra} debe ser mayor que cero.`,
                            );
                          }

                          const datos = {
                            nombre:
                              document.getElementById(`nombre_${sfx}`).value ||
                              `Alternativa ${letra}`,
                            inversion: inversion,
                            tasa: tasa,
                            vida: vida,
                            salvamento: obtenerNumero(
                              `salv_${sfx}`,
                              false,
                              `Valor de salvamento de la Alternativa ${letra}`,
                            ),
                            modo: modo,
                            trema: tasa,
                          };

                          if (modo === "uniforme") {
                            datos.ingresos = obtenerNumero(
                              `ing_${sfx}`,
                              false,
                              `Ingresos anuales de la Alternativa ${letra}`,
                            );
                            datos.egresos = obtenerNumero(
                              `egr_${sfx}`,
                              false,
                              `Egresos anuales de la Alternativa ${letra}`,
                            );
                          } else {
                            datos.flujos = [];

                            const inputs = document.querySelectorAll(`.flujo-input-${sfx}`);

                            if (inputs.length !== vida) {
                              throw new Error(
                                `La cantidad de flujos de la Alternativa ${letra} debe coincidir con la vida del proyecto.`,
                              );
                            }

                            inputs.forEach((inp, index) => {
                              const valorTexto = inp.value.trim();

                              if (valorTexto === "") {
                                throw new Error(
                                  `Debe ingresar el flujo del año ${index + 1} en la Alternativa ${letra}.`,
                                );
                              }

                              const valor = parseFloat(valorTexto);

                              if (isNaN(valor)) {
                                throw new Error(
                                  `El flujo del año ${index + 1} en la Alternativa ${letra} debe ser numérico.`,
                                );
                              }

                              datos.flujos.push(valor);
                            });
                          }

                          return datos;
                        }

                        async function calcular() {
  const btn = document.getElementById("btnCalc");
  btn.innerHTML = '<span class="spinner"></span> Calculando...';
  btn.disabled = true;

  let altA;
  let altB;

  try {
    altA = recopilarDatosAlt("a");
    altB = recopilarDatosAlt("b");
  } catch (e) {
    alert(e.message);
    btn.innerHTML = "⚙️ &nbsp;Calcular y Comparar";
    btn.disabled = false;
    return;
  }

  const payload = {
    metodo: metodoActual,
    alternativa_a: altA,
    alternativa_b: altB,
  };

  try {
    const resp = await fetch("/calcular", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    const data = await resp.json();

    if (!resp.ok) {
      let mensaje = data.error || "Error al calcular.";

      if (data.detalles && Array.isArray(data.detalles)) {
        mensaje += "\n\n" + data.detalles.join("\n");
      }

      throw new Error(mensaje);
    }

    ultimosResultados = data;
    ultimosDatos = payload;

    mostrarResultados(data, altA, altB);
  } catch (e) {
    alert(e.message);
  } finally {
    btn.innerHTML = "⚙️ &nbsp;Calcular y Comparar";
    btn.disabled = false;
  }
}

                        // ── MOSTRAR RESULTADOS ────────────────────────────────────────────────────────
                        function fmt(n) {
                          return n !== null && n !== undefined
                            ? `$${parseFloat(n).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
                            : "N/A";
                        }
                        function fmtPct(n) {
                          return n !== null && n !== undefined ? `${n}%` : "No determinada";
                        }

                        function mostrarResultados(data, altA, altB) {
                          const resDiv = document.getElementById("resultados");
                          resDiv.style.display = "block";
                          resDiv.classList.add("fade-up");
                          resDiv.scrollIntoView({ behavior: "smooth", block: "start" });

                          // Ganador
                          document.getElementById("ganadorNombre").textContent = data.ganador;
                          let subTexto = "";
                          if (metodoActual === "VPN") {
                            subTexto = `VPN = ${fmt(data.val_a)} vs ${fmt(data.val_b)} — Se elige el mayor VPN`;
                          } else if (metodoActual === "CAE") {
                            subTexto = `CAE = ${fmt(data.val_a)} vs ${fmt(data.val_b)} — Se elige el mayor VA`;
                          } else {
                            subTexto = `TIR = ${fmtPct(data.val_a)} vs ${fmtPct(data.val_b)} — TREMA = ${altA.tasa}%`;
                          }
                          document.getElementById('ganadorSub').textContent = data.mensaje || subTexto;

                          // Tarjetas
                          const esMejorA = data.ganador === altA.nombre;
                          const esMejorB = data.ganador === altB.nombre;

                          renderResCard("A", altA, data.resultado_a, esMejorA);
                          renderResCard("B", altB, data.resultado_b, esMejorB);
                        }

                        function renderResCard(letra, altDatos, res, esMejorAlternativa = false) {
                          const header = document.getElementById(`resHeader${letra}`);
                          const body = document.getElementById(`resBody${letra}`);
                          header.textContent = altDatos.nombre || `Alternativa ${letra}`;

                          const esVerde = res.color_decision === "verde";
                          let html = "";

                          const textoDecision = esMejorAlternativa
                            ? `${res.decision} · MEJOR OPCIÓN`
                            : res.decision;     

                          if (metodoActual === "VPN") {
                            html += `<div class="valor-principal" style="color:${esVerde ? "var(--verde)" : "var(--ues-rojo)"}">${fmt(res.vpn)}</div>`;
                            html += `<span class="decision-badge ${res.color_decision}">${textoDecision}</span>`;
                            if (res.flujos && res.flujos.length) {
                              html += `<table class="tabla-flujos">
                          <thead><tr><th>Período</th><th>Flujo Neto</th><th>Factor P/F</th><th>VP</th></tr></thead>
                          <tbody>`;
                              res.flujos.forEach((f) => {
                                html += `<tr><td>${f.periodo}</td><td>${fmt(f.flujo)}</td><td>${f.factor_pf}</td><td>${fmt(f.vp)}</td></tr>`;
                              });
                              html += `</tbody></table>`;
                              html += `<div style="text-align:right;font-weight:700;font-size:14px;margin-top:8px;color:var(--ues-rojo)">VPN Total: ${fmt(res.vpn)}</div>`;
                            }
                          } else if (metodoActual === "CAE") {
                            html += `<div class="valor-principal" style="color:${esVerde ? "var(--verde)" : "var(--ues-rojo)"}">${fmt(res.cae)}</div>`;
                            html += `<span class="decision-badge ${res.color_decision}">${textoDecision}</span>`;
                            html += `<div class="detalle-row"><span class="label">Factor A/P</span><span class="valor">${res.ap}</span></div>`;
                            html += `<div class="detalle-row"><span class="label">Factor A/F</span><span class="valor">${res.af}</span></div>`;
                            html += `<div class="detalle-row"><span class="label">Recuperación de Capital (RC)</span><span class="valor">${fmt(res.rc)}</span></div>`;
                            html += `<div class="detalle-row"><span class="label">CAE / VA(i%)</span><span class="valor" style="color:var(--ues-rojo)">${fmt(res.cae)}</span></div>`;
                          } else {
                            // TIR
                            html += `<div class="valor-principal" style="color:${esVerde ? "var(--verde)" : "var(--ues-rojo)"}">${fmtPct(res.tir)}</div>`;
                            html += `<span class="decision-badge ${res.color_decision}">${textoDecision}</span>`;
                            html += `<div class="detalle-row"><span class="label">TIR Calculada</span><span class="valor">${fmtPct(res.tir)}</span></div>`;
                            html += `<div class="detalle-row"><span class="label">TREMA</span><span class="valor">${res.trema}%</span></div>`;
                            if (res.mensaje) {
              html += `<div style="margin-top:10px;font-size:13px;color:var(--ues-rojo);font-weight:600;">${res.mensaje}</div>`;
            }
                            if (res.tir !== null) {
                              const dif = (res.tir - res.trema).toFixed(2);
                              html += `<div class="detalle-row"><span class="label">TIR - TREMA</span><span class="valor" style="color:${dif >= 0 ? "var(--verde)" : "var(--ues-rojo)"}">${dif >= 0 ? "+" : ""}${dif}%</span></div>`;
                            }
                            if (res.flujos && res.flujos.length) {
                              html += `<table class="tabla-flujos" style="margin-top:10px">
                          <thead><tr><th>Período</th><th>Flujo Neto</th><th>Factor P/F@TIR</th><th>VP</th></tr></thead>
                          <tbody>`;
                              res.flujos.forEach((f) => {
                                html += `<tr><td>${f.periodo}</td><td>${fmt(f.flujo)}</td><td>${f.factor_pf}</td><td>${fmt(f.vp)}</td></tr>`;
                              });
                              html += `</tbody></table>`;
                            }
                          }

                          body.innerHTML = html;
                        }

                        // ── GENERAR PDF ───────────────────────────────────────────────────────────────
                        async function generarPDF() {
                          if (!ultimosResultados) return;
                          const btn = document.getElementById("btnPdf");
                          btn.textContent = "⏳ Generando PDF...";
                          btn.disabled = true;

                          let altA;
                          let altB;

                          try {
                            altA = recopilarDatosAlt("a");
                            altB = recopilarDatosAlt("b");
                          } catch (e) {
                            alert(e.message);
                            btn.innerHTML = "⚙️ &nbsp;Calcular y Comparar";
                            btn.disabled = false;
                            return;
                          }

                          const payload = {
                            metodo: metodoActual,
                            alternativa_a: altA,
                            alternativa_b: altB,
                          };

                          try {
                            const resp = await fetch("/reporte", {
                              method: "POST",
                              headers: { "Content-Type": "application/json" },
                              body: JSON.stringify(payload),
                            });
                            const blob = await resp.blob();
                            const url = URL.createObjectURL(blob);
                            const a = document.createElement("a");
                            a.href = url;
                            a.download = `SAE_Reporte_${metodoActual}.pdf`;
                            a.click();
                            URL.revokeObjectURL(url);
                          } catch (e) {
                            alert("Error generando PDF: " + e.message);
                          } finally {
                            btn.innerHTML = "📄 Exportar Reporte PDF";
                            btn.disabled = false;
                          }
                        }

                        function cargarEjemplo() {
        document.getElementById('nombre_a').value = 'Máquina A';
        document.getElementById('inv_a').value = 10000;
        document.getElementById('tasa_a').value = 10;
        document.getElementById('vida_a').value = 5;
        document.getElementById('salv_a').value = 1000;
        document.getElementById('ing_a').value = 5000;
        document.getElementById('egr_a').value = 1800;

        document.getElementById('nombre_b').value = 'Máquina B';
        document.getElementById('inv_b').value = 12000;
        document.getElementById('tasa_b').value = 10;
        document.getElementById('vida_b').value = 5;
        document.getElementById('salv_b').value = 1500;
        document.getElementById('ing_b').value = 5600;
        document.getElementById('egr_b').value = 2000;

        document.getElementById('resultados').style.display = 'none';
        ultimosResultados = null;
        ultimosDatos = null;
      }

      function limpiarDatos() {
        const inputs = document.querySelectorAll('input');

        inputs.forEach(input => {
          if (input.id === 'nombre_a') {
            input.value = 'Alternativa A';
          } else if (input.id === 'nombre_b') {
            input.value = 'Alternativa B';
          } else {
            input.value = '';
          }
        });

        document.getElementById('resultados').style.display = 'none';
        ultimosResultados = null;
        ultimosDatos = null;
      }