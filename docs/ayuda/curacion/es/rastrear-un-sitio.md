# Dar de alta un sitio y rastrearlo

La curación revisa el contenido de un apartado del portal web antes de que alimente a un asistente. La plataforma rastrea el apartado, guarda el texto de cada página y detecta problemas: páginas duplicadas, documentos antiguos o superados por una versión más nueva, páginas con demasiado poco contenido, páginas de navegación y enlaces que ya no funcionan. Una persona revisa cada problema y decide si es real.

## Los sitios

La pestaña **Sitios** muestra los apartados dados de alta. Cada sitio es **un apartado del portal**, no el portal entero.

- **Rastrear ahora** vuelve a leer el apartado. Hace una pausa entre páginas para no cargar el servidor del portal, así que un apartado de 350 páginas tarda unos doce minutos. Si no acaba en una pasada, la siguiente continúa donde lo dejó.
- **Alcance de auditoría semántica**: para revisar antes de que nada pase al asistente, tiene que estar en «Completo». Con «Solo ingerido» solo se comprueba lo que ya está en el asistente; con «No analizar» no se buscan duplicados ni contradicciones.
- **Eliminar** borra el sitio con todo lo revisado. No lo uses sin hablarlo antes con quien administra.

## Dar de alta un sitio nuevo

Solo hace falta si el apartado todavía no está en la lista. Pulsa **Nuevo sitio** y rellena:

- **URL raíz**: la página de entrada del apartado.
- **Filtro de URL del apartado**: una expresión que limita el rastreo; solo se rastrean las direcciones que la contienen.
- **Profundidad**: cuántos clics desde la raíz se siguen. Con 4 suele llegarse a la normativa y las convocatorias enlazadas desde el índice.
- **Máx. páginas** y **Pausa (s)**: el tope y la pausa de cortesía. **Respetar robots.txt del sitio** viene marcado; desmarcarlo queda registrado.
- **Criterios de curación**: la antigüedad a partir de la cual una página se considera desactualizada y el mínimo de contenido.

Antes de crearlo puedes usar **Reconocer el sitio**: recorre el apartado sin guardar nada y dice cuántas páginas tiene y cuánto tardaría en rastrearse.
