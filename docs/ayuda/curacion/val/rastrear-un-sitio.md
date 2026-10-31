# Donar d'alta un lloc i rastrejar-lo

La curació revisa el contingut d'un apartat del portal web abans que alimente un assistent. La plataforma rastreja l'apartat, guarda el text de cada pàgina i detecta problemes: pàgines duplicades, documents antics o superats per una versió més nova, pàgines amb massa poc contingut, pàgines de navegació i enllaços que ja no funcionen. Una persona revisa cada problema i decideix si és real.

## Els llocs

La pestanya **Llocs** mostra els apartats donats d'alta. Cada lloc és **un apartat del portal**, no el portal sencer.

- **Rastrejar ara** torna a llegir l'apartat. Fa una pausa entre pàgines per no carregar el servidor del portal, així que un apartat de 350 pàgines tarda uns dotze minuts. Si no acaba en una passada, la següent continua on ho va deixar.
- **Abast de l'auditoria semàntica**: per a revisar abans que res passe a l'assistent, ha d'estar en «Complet». Amb «Només ingerit» només es comprova el que ja és a l'assistent; amb «No analitzar» no es busquen duplicats ni contradiccions.
- **Eliminar** esborra el lloc amb tot el que s'hi ha revisat. No el faces servir sense parlar-ho abans amb qui administra.

## Donar d'alta un lloc nou

Només cal si l'apartat encara no és a la llista. Prem **Nou lloc** i ompli:

- **URL arrel**: la pàgina d'entrada de l'apartat.
- **Filtre d'URL de l'apartat**: una expressió que limita el rastreig; només es rastregen les adreces que la contenen.
- **Profunditat**: quants clics des de l'arrel se segueixen. Amb 4 se sol arribar a la normativa i les convocatòries enllaçades des de l'índex.
- **Màx. pàgines** i **Pausa (s)**: el límit i la pausa de cortesia. **Respectar el robots.txt del lloc** ve marcat; desmarcar-lo queda registrat.
- **Criteris de curació**: l'antiguitat a partir de la qual una pàgina es considera desactualitzada i el contingut mínim.

Abans de crear-lo pots fer servir **Reconéixer el lloc**: recorre l'apartat sense guardar res i diu quantes pàgines té i quant tardaria a rastrejar-se.
