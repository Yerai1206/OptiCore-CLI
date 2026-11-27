# ADR 0001: acciones en JSON

Estado: aceptada para el prototipo.

Las acciones se declaran en `acciones.json` para poder cambiar nombres y añadir instrucciones de IA sin modificar la interfaz. El motor admite únicamente tipos conocidos: leer JSON no permite ejecutar comandos arbitrarios. La estructura se valida antes de iniciar una operación. Para incorporar un tipo de operación completamente nuevo sigue siendo necesario programar y probar su implementación.
