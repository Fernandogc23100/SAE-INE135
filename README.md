# SAE - Sistema de Análisis Económico

SAE es una aplicación web desarrollada con **Flask** para realizar análisis económico de alternativas de inversión.  
El sistema permite calcular indicadores financieros básicos como **VPN**, **CAE/VA** y **TIR**, comparar dos alternativas y generar un reporte en PDF con los resultados.

## Características

- Cálculo del **Valor Presente Neto (VPN)**.
- Cálculo del **Costo Anual Equivalente / Valor Anual (CAE/VA)**.
- Cálculo aproximado de la **Tasa Interna de Retorno (TIR)**.
- Comparación entre dos alternativas de inversión.
- Recomendación automática de la mejor alternativa según el método seleccionado.
- Generación de reporte en formato **PDF**.
- Interfaz web sencilla y responsive.

## Tecnologías utilizadas

- Python
- Flask
- HTML
- CSS
- JavaScript
- ReportLab

## Estructura del proyecto

```text
SAE/
├── app.py
├── requirements.txt
├── INSTRUCCIONES.txt
└── templates/
    └── index.html

## Requisitos previos

Antes de ejecutar el proyecto, asegúrate de tener instalado:
Python 3.8 o superior
pip

## Instalación
1. Clona este repositorio:
    https://github.com/Fernandogc23100/SAE-INE135.git

2. Entra a la carpeta del proyecto:
    cd SAE_Sistema

3. Instala dependencias:
    pip install -r requirements.txt

4. Para iniciar la aplicacion, ejecuta:
    python app.py

5. Luego abre tu navegador y entra a:
    http://localhost:5000

```
