# Les seccions d'un lloc

Dins d'un lloc hi ha parts que canvien contínuament: jornades, esdeveniments, beques, convocatòries. Una **secció** permet tractar una d'aquestes parts per separat: quines pàgines la formen, cada quant es revisa, qui n'és responsable i, sobretot, que la seua actualització en l'assistent siga automàtica. Sense seccions, el lloc es rastreja sencer. Per a començar no en cal cap.

## Crear una secció

A **Llocs → Seccions del lloc → Nova secció** es demana:

- **Nom** i **Patró**. El patró diu quines pàgines són de la secció: el més habitual és un prefix de ruta, però també val una expressió regular. **Provar patró** diu quantes de les pàgines ja rastrejades hi casen. La pertinença no es guarda pàgina a pàgina: es calcula amb el patró cada vegada, així que si canvies el patró, la secció canvia amb ell.
- **Cadència pròpia** i criteris de curació. Un camp buit hereta el valor del lloc.
- **Responsable**: qui s'encarrega d'aquella part.

## Manual o automàtic

- **Manual** és el mode de tota secció nova. La plataforma rastreja i avisa del que és nou, del que ha canviat i del que ha desaparegut, però no toca el contingut de cap assistent: tot passa per una persona.
- **Automàtic**: quan la secció ja s'ha curat, la plataforma la manté al dia sola. Incorpora les pàgines noves, actualitza les que han canviat i retira les que han desaparegut del portal, amb dues salvaguardes: no incorpora res que tinga una troballa bloquejant, i **no retira mai molt de colp**. Si un rastreig n'hauria de retirar més del 30 % de la secció, no en retira cap i avisa amb les xifres.

La idea és **curar una vegada, automatitzar després**: primer la revisa una persona i després es passa a automàtic.

## El diari de passades

Cada rastreig d'una secció en deixa constància al **Diari de passades**: quantes pàgines s'han ingerit, reingerit, retirat o bloquejat. Així es pot saber per què una pàgina va entrar o va eixir.
