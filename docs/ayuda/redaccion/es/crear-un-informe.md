# Crear un informe y cargar los datos

Un informe se hace siempre a partir de una **plantilla**, que fija su estructura: qué tablas lleva y qué apartados valora la IA. Las tablas las copia la plataforma tal como vienen en el fichero de datos; **el modelo no escribe ni cambia ninguna cifra**. Lo que propone la IA es la valoración de cada tabla, y ninguna valoración llega al informe sin que una persona la apruebe.

## Empezar un informe nuevo

1. Entra en **Informes**. Se abre directamente la pestaña **Nuevo informe**. Las pestañas «Plantillas» y «Revisión de scripts» son para quien administra.
2. Elige la plantilla en la lista y pulsa **Crear informe**.
3. Si no encuentras la plantilla que necesitas, pídesela a quien administra la plataforma: las plantillas las crea y las publica la administración.

## Subir los datos de partida

Se abre el espacio de trabajo del informe. En **Datos de partida**:

1. Arrastra el fichero de datos al recuadro, o pulsa en él para elegirlo. Debajo se indica qué formatos acepta la plantilla.
2. Rellena los campos que la plantilla pide aparte, si los hay: son los datos que no están en el fichero.
3. Pulsa **Continuar**.

Si vuelves a esta pantalla más tarde, el fichero que ya subiste aparece como «ya subido»: se reutiliza si no eliges otro.

## El modo de anonimización

Más abajo está el **Modo de anonimización**. Sustituye los datos personales por datos sintéticos antes de enviar el texto al modelo, y al volver la respuesta vuelve a poner los reales en el informe. Las opciones son «Desactivado», «Solo detectar», «Reemplazar (Faker)» y «Reemplazar + LOPDGDD», que además enmascara DNI, NIE y pasaporte. El modo no se puede cambiar mientras el informe se está generando.

## Esperar la generación

La pantalla se actualiza sola mientras extrae las tablas y redacta las valoraciones; suele tardar unos minutos. La barra de arriba indica el estado: «Preparando», «Extrayendo datos», «En redacción» y, cuando ya se puede revisar, **«En revisión»**. El paso siguiente es revisar las valoraciones.
